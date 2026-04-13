"""
polygon_adapter.py — Polygon.io data adapter for tos-api.

Free tier: 5 calls/min, 2 years history, EOD only, no indices.
Output schema matches Schwab adapter for transparent source switching.
"""

import time
import threading
import logging
from datetime import datetime, date, timedelta
from typing import Optional
import requests

logger = logging.getLogger("tos_api.polygon")

POLYGON_BASE = "https://api.polygon.io"


# ── Normalized bar schema ──────────────────────────────────────────────────────
def _normalize_bar(raw: dict, symbol: str, timeframe: str) -> dict:
    return {
        "symbol":    symbol,
        "timestamp": int(raw["t"]),          # Unix ms UTC
        "open":      float(raw["o"]),
        "high":      float(raw["h"]),
        "low":       float(raw["l"]),
        "close":     float(raw["c"]),
        "volume":    float(raw.get("v", 0)),
        "vwap":      float(raw["vw"]) if "vw" in raw else None,
        "trades":    int(raw["n"]) if "n" in raw else None,
        "timeframe": timeframe,
        "source":    "polygon",
    }


def _normalize_quote(raw: dict, symbol: str) -> dict:
    day = raw.get("day", {})
    prev = raw.get("prevDay", {})
    return {
        "symbol":     symbol,
        "timestamp":  int(time.time() * 1000),
        "last":       float(raw.get("lastTrade", {}).get("p", 0) or day.get("c", 0)),
        "bid":        float(raw.get("lastQuote", {}).get("p", 0)),
        "ask":        float(raw.get("lastQuote", {}).get("P", 0)),
        "volume":     int(day.get("v", 0)),
        "open":       float(day.get("o", 0)),
        "high":       float(day.get("h", 0)),
        "low":        float(day.get("l", 0)),
        "prev_close": float(prev.get("c", 0)),
        "change_pct": float(raw.get("todaysChangePerc", 0)),
        "source":     "polygon",
    }


# ── Rate limiter — 5 calls/minute for free tier ────────────────────────────────
class RateLimiter:
    def __init__(self, calls_per_minute: int = 5):
        self._lock     = threading.Lock()
        self._calls    = []
        self._limit    = calls_per_minute
        self._window   = 60.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            # Drop calls outside the window
            self._calls = [t for t in self._calls if now - t < self._window]
            if len(self._calls) >= self._limit:
                sleep_for = self._window - (now - self._calls[0]) + 0.1
                if sleep_for > 0:
                    logger.debug("Rate limit: sleeping %.1fs", sleep_for)
                    time.sleep(sleep_for)
                now = time.monotonic()
                self._calls = [t for t in self._calls if now - t < self._window]
            self._calls.append(time.monotonic())


_rate_limiter = RateLimiter(calls_per_minute=4)  # 4 to leave headroom


# ── Core HTTP ──────────────────────────────────────────────────────────────────
def _get(path: str, params: dict, api_key: str) -> dict:
    _rate_limiter.wait()
    params["apiKey"] = api_key
    r = requests.get(f"{POLYGON_BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "ERROR":
        raise ValueError(f"Polygon error: {data.get('error', data)}")
    if data.get("status") == "NOT_AUTHORIZED":
        raise PermissionError(f"Polygon not authorized: {data.get('message', '')}")
    return data


# ── Paginated bar fetcher ──────────────────────────────────────────────────────
def fetch_bars(
    symbol: str,
    timeframe: str,      # "1m", "5m", "15m", "1d"
    from_date: str,      # YYYY-MM-DD
    to_date: str,        # YYYY-MM-DD
    api_key: str,
    limit: int = 50000,
) -> list[dict]:
    """
    Fetch all bars for symbol between from_date and to_date.
    Handles pagination automatically. Returns normalized bar dicts.
    timeframe: "1m" | "5m" | "15m" | "1d"
    """
    tf_map = {"1m": ("minute", 1), "5m": ("minute", 5),
              "15m": ("minute", 15), "1d": ("day", 1)}
    if timeframe not in tf_map:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    freq_type, freq = tf_map[timeframe]

    path   = f"/v2/aggs/ticker/{symbol}/range/{freq}/{freq_type}/{from_date}/{to_date}"
    params = {"adjusted": "true", "sort": "asc", "limit": limit}

    all_bars = []
    url      = f"{POLYGON_BASE}{path}"

    while url:
        _rate_limiter.wait()
        p = {**params, "apiKey": api_key}
        r = requests.get(url, params=p if url == f"{POLYGON_BASE}{path}" else {"apiKey": api_key},
                         timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("status") in ("ERROR", "NOT_AUTHORIZED"):
            raise ValueError(f"Polygon: {data.get('error') or data.get('message')}")

        results = data.get("results") or []
        all_bars.extend(_normalize_bar(b, symbol, timeframe) for b in results)

        url = data.get("next_url")
        logger.debug("%s %s: fetched %d bars total so far", symbol, timeframe, len(all_bars))

    logger.info("fetch_bars %s %s %s→%s: %d bars", symbol, timeframe, from_date, to_date, len(all_bars))
    return all_bars


def fetch_daily_bars(symbol: str, from_date: str, to_date: str, api_key: str) -> list[dict]:
    return fetch_bars(symbol, "1d", from_date, to_date, api_key)


def fetch_intraday_bars(symbol: str, from_date: str, to_date: str,
                        api_key: str, timeframe: str = "1m") -> list[dict]:
    return fetch_bars(symbol, timeframe, from_date, to_date, api_key)


def fetch_snapshot(symbol: str, api_key: str) -> dict:
    """Fetch latest EOD snapshot. Returns normalized quote dict."""
    data = _get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}",
                {}, api_key)
    ticker = data.get("ticker", {})
    return _normalize_quote(ticker, symbol)


def fetch_technical_indicator(
    symbol: str,
    indicator: str,      # "sma" | "ema" | "rsi" | "macd"
    timespan: str,       # "day" | "minute"
    window: int,
    api_key: str,
    limit: int = 50,
) -> list[dict]:
    """
    Fetch Polygon's built-in technical indicator.
    Returns list of {timestamp, value} dicts.
    """
    path = f"/v1/indicators/{indicator}/{symbol}"
    data = _get(path, {"timespan": timespan, "window": window,
                       "series_type": "close", "limit": limit,
                       "adjusted": "true"}, api_key)
    results = data.get("results", {}).get("values", [])
    return [{"timestamp": int(r["timestamp"]), "value": float(r["value"])}
            for r in results]
