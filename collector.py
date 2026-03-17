"""
data/collector.py
-----------------
Collects all market data needed for Day Trading analysis.
Uses schwabdev.Client (same pattern as test_connectivity.py)
which reads tokens automatically from tokens.db.
"""

import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import ta
import schwabdev
from dotenv import load_dotenv

load_dotenv()

APP_KEY      = os.environ.get("SCHWAB_APP_KEY", "")
APP_SECRET   = os.environ.get("SCHWAB_APP_SECRET", "")
CALLBACK_URL = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
TOKENS_DB    = os.environ.get("SCHWAB_TOKENS_DB", "tokens.db")

DAY_TRADE_CONFIG = {
    "timeframe":     "1min",
    "lookback_days": 5,
    "bars_to_ai":    240,
    "rsi_window":    14,
    "emas":          [9, 20],
    "smas":          [20, 50, 100, 200],
    "macd":          True,
}

# ── Schwab client (singleton) ──────────────────────────────────────────────
_client = None

def get_client() -> schwabdev.Client:
    global _client
    if _client is None:
        _client = schwabdev.Client(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            callback_url=CALLBACK_URL,
            tokens_db=TOKENS_DB,
        )
    return _client


# ── Data fetchers ──────────────────────────────────────────────────────────

def _get_quote(ticker: str) -> dict:
    client = get_client()
    resp = client.quote(ticker)
    if not resp.ok:
        return {}
    data  = resp.json()
    quote = data.get(ticker, {}).get("quote", {})
    return {
        "symbol":     ticker,
        "last":       quote.get("lastPrice"),
        "bid":        quote.get("bidPrice"),
        "ask":        quote.get("askPrice"),
        "volume":     quote.get("totalVolume"),
        "open":       quote.get("openPrice"),
        "high":       quote.get("highPrice"),
        "low":        quote.get("lowPrice"),
        "prev_close": quote.get("closePrice"),
        "change_pct": quote.get("netPercentChangeInDouble"),
    }


def _get_price_history(ticker: str) -> pd.DataFrame:
    client = get_client()
    cfg    = DAY_TRADE_CONFIG
    resp   = client.price_history(
        symbol=ticker,
        period_type="day",
        period=cfg["lookback_days"],
        frequency_type="minute",
        frequency=1,
        need_extended_hours_data=False,
    )
    if not resp.ok:
        return pd.DataFrame()

    candles = resp.json().get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    cfg = DAY_TRADE_CONFIG
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=cfg["rsi_window"]).rsi()
    for p in cfg["emas"]:
        df[f"ema_{p}"] = ta.trend.EMAIndicator(df["close"], window=p).ema_indicator()
    for p in cfg["smas"]:
        df[f"sma_{p}"] = ta.trend.SMAIndicator(df["close"], window=p).sma_indicator()
    macd = ta.trend.MACD(df["close"])
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()
    return df


def _get_market_context() -> dict:
    results = {}
    for ticker in ["SPY", "QQQ", "$VIX.X"]:
        try:
            results[ticker] = _get_quote(ticker)
        except Exception:
            results[ticker] = {}
    return {
        "spy": results.get("SPY", {}),
        "qqq": results.get("QQQ", {}),
        "vix": results.get("$VIX.X", {}),
    }


# ── Main entry point ───────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=3)

async def collect_all(ticker: str) -> dict:
    loop = asyncio.get_event_loop()

    quote_fut   = loop.run_in_executor(_executor, _get_quote,         ticker)
    history_fut = loop.run_in_executor(_executor, _get_price_history, ticker)
    context_fut = loop.run_in_executor(_executor, _get_market_context)

    quote, raw_df, market_ctx = await asyncio.gather(quote_fut, history_fut, context_fut)

    df = _compute_indicators(raw_df) if not raw_df.empty else raw_df

    bars_to_ai = DAY_TRADE_CONFIG["bars_to_ai"]
    recent_df  = df.tail(bars_to_ai).copy()

    cols = [c for c in [
        "datetime", "open", "high", "low", "close", "volume",
        "rsi", "ema_9", "ema_20", "sma_20", "sma_50", "sma_200",
        "macd", "macd_signal", "macd_hist"
    ] if c in recent_df.columns]

    bars_summary = recent_df[cols].round(4).tail(60).to_dict("records") if not recent_df.empty else []
    latest = recent_df.iloc[-1].to_dict() if not recent_df.empty else {}

    return {
        "ticker":      ticker,
        "quote":       quote,
        "market_ctx":  market_ctx,
        "latest_bars": bars_summary,
        "indicators": {
            "rsi":         round(float(latest.get("rsi")         or 0), 2),
            "ema_9":       round(float(latest.get("ema_9")       or 0), 2),
            "ema_20":      round(float(latest.get("ema_20")      or 0), 2),
            "sma_20":      round(float(latest.get("sma_20")      or 0), 2),
            "sma_50":      round(float(latest.get("sma_50")      or 0), 2),
            "sma_200":     round(float(latest.get("sma_200")     or 0), 2),
            "macd":        round(float(latest.get("macd")        or 0), 4),
            "macd_signal": round(float(latest.get("macd_signal") or 0), 4),
            "macd_hist":   round(float(latest.get("macd_hist")   or 0), 4),
        },
        "total_bars": len(df),
        "style":      "day_trading",
    }
