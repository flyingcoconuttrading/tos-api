"""
data/collector.py
-----------------
Dual-timeframe data collection with in-memory caching.
- Intraday (1-min bars): cached 60s
- Daily bars (S/R levels): cached 6hrs
- Quotes: cached 15s
- Options chain: cached 5min (behind ENABLE_OPTIONS flag)
"""

import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
import pandas as pd

logger = logging.getLogger("tos_api.collector")
import ta
import schwabdev
from dotenv import load_dotenv

from config import (
    SCHWAB_APP_KEY, SCHWAB_APP_SECRET, SCHWAB_CALLBACK_URL, SCHWAB_TOKENS_DB,
    DAY_TRADE_CONFIG, ENABLE_OPTIONS,
    CACHE_TTL_INTRADAY, CACHE_TTL_DAILY, CACHE_TTL_QUOTE, CACHE_TTL_OPTIONS,
)
from cache.store import get as cache_get, set as cache_set
import settings as _settings

# Polygon fallback — used when Schwab unavailable or for historical context
try:
    from data.polygon_adapter import fetch_daily_bars as _polygon_daily
    from data.historical_store import get_bars as _get_cached_bars, insert_bars as _cache_bars
    _POLYGON_AVAILABLE = True
except ImportError:
    _POLYGON_AVAILABLE = False

load_dotenv()

# ── Schwab client singleton ────────────────────────────────────────────────

import threading
_client = None
_client_lock = threading.Lock()

def get_client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                _client = schwabdev.Client(
                    app_key=SCHWAB_APP_KEY,
                    app_secret=SCHWAB_APP_SECRET,
                    callback_url=SCHWAB_CALLBACK_URL,
                    tokens_db=SCHWAB_TOKENS_DB,
                )
    return _client


# ── Quote ──────────────────────────────────────────────────────────────────

def _get_quote(ticker: str) -> dict:
    key = f"{ticker}:quote"
    cached = cache_get(key)
    if cached:
        return cached

    resp = get_client().quote(ticker)
    if not resp.ok:
        return {}
    data  = resp.json()
    quote = data.get(ticker, {}).get("quote", {})
    result = {
        "symbol":     ticker,
        "last":       quote.get("lastPrice"),
        "bid":        quote.get("bidPrice"),
        "ask":        quote.get("askPrice"),
        "volume":     quote.get("totalVolume"),
        "open":       quote.get("openPrice"),
        "high":       quote.get("highPrice"),
        "low":        quote.get("lowPrice"),
        "prev_close": quote.get("closePrice"),
        "change_pct": quote.get("netPercentChange"),
    }
    cache_set(key, result, CACHE_TTL_QUOTE)
    return result


# ── Intraday bars ──────────────────────────────────────────────────────────

def _get_intraday(ticker: str) -> pd.DataFrame:
    key = f"{ticker}:intraday"
    cached = cache_get(key)
    if cached is not None:
        return cached

    cfg  = DAY_TRADE_CONFIG
    resp = get_client().price_history(
        symbol=ticker,
        periodType="day",
        period=cfg["lookback_days"],
        frequencyType="minute",
        frequency=1,
        needExtendedHoursData=False,
    )
    if not resp.ok:
        return pd.DataFrame()

    candles = resp.json().get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
    df = df.sort_values("datetime").reset_index(drop=True)
    cache_set(key, df, CACHE_TTL_INTRADAY)
    return df


# ── Daily bars ────────────────────────────────────────────────────────────

def _get_daily(ticker: str) -> pd.DataFrame:
    key = f"{ticker}:daily"
    cached = cache_get(key)
    if cached is not None:
        return cached

    resp = get_client().price_history(
        symbol=ticker,
        periodType="month",
        period=1,
        frequencyType="daily",
        frequency=1,
        needExtendedHoursData=False,
    )
    if not resp.ok:
        return pd.DataFrame()

    candles = resp.json().get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
    df = df.sort_values("datetime").reset_index(drop=True)
    cache_set(key, df, CACHE_TTL_DAILY)
    return df


# ── S/R level calculator ───────────────────────────────────────────────────

def _calc_sr_levels(intraday_df: pd.DataFrame, daily_df: pd.DataFrame, quote: dict) -> dict:
    """
    Calculate key S/R levels from daily and intraday bars.
    Returns structured levels matching Checker methodology.
    """
    levels = {
        "intraday": {},
        "daily":    {},
        "key_references": {},
    }

    # ── Daily levels ──────────────────────────────────────────────────────
    if not daily_df.empty and len(daily_df) >= 2:
        today_row  = daily_df.iloc[-1]
        yest_row   = daily_df.iloc[-2]

        # Previous day
        levels["daily"]["pdc"] = round(float(yest_row["close"]), 4)
        levels["daily"]["pdh"] = round(float(yest_row["high"]),  4)
        levels["daily"]["pdl"] = round(float(yest_row["low"]),   4)

        # Weekly high/low (last 5 trading days)
        week = daily_df.tail(5)
        levels["daily"]["weekly_high"] = round(float(week["high"].max()), 4)
        levels["daily"]["weekly_low"]  = round(float(week["low"].min()),  4)

        # Monthly high/low (all available daily bars)
        levels["daily"]["monthly_high"] = round(float(daily_df["high"].max()), 4)
        levels["daily"]["monthly_low"]  = round(float(daily_df["low"].min()),  4)

    # ── Intraday levels ───────────────────────────────────────────────────
    if not intraday_df.empty:
        # Today's bars only
        today = intraday_df[intraday_df["datetime"].dt.date == date.today()]
        if not today.empty:
            # Opening range (first 30 min = first 30 bars)
            opening = today.head(30)
            levels["intraday"]["opening_range_high"] = round(float(opening["high"].max()), 4)
            levels["intraday"]["opening_range_low"]  = round(float(opening["low"].min()),  4)

            # Today's high/low so far
            levels["intraday"]["today_high"] = round(float(today["high"].max()), 4)
            levels["intraday"]["today_low"]  = round(float(today["low"].min()),  4)

            # VWAP
            typical = (today["high"] + today["low"] + today["close"]) / 3
            vwap = (typical * today["volume"]).cumsum() / today["volume"].cumsum()
            levels["intraday"]["vwap"] = round(float(vwap.iloc[-1]), 4)

    # ── Key references summary ─────────────────────────────────────────────
    levels["key_references"] = {
        k: v for d in [levels["daily"], levels["intraday"]] for k, v in d.items()
    }

    return levels


# ── VWAP (added to intraday df) ────────────────────────────────────────────

def _add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    today = df[df["datetime"].dt.date == date.today()].copy()
    if today.empty:
        df["vwap"] = None
        return df
    typical = (today["high"] + today["low"] + today["close"]) / 3
    vwap    = (typical * today["volume"]).cumsum() / today["volume"].cumsum()
    df.loc[today.index, "vwap"] = vwap
    return df


# ── Indicators ─────────────────────────────────────────────────────────────

def _compute_indicators(df: pd.DataFrame, trade_type: str = "day") -> pd.DataFrame:
    cfg    = DAY_TRADE_CONFIG
    # Indicator sets by trade type
    if trade_type in ("swing_medium", "swing_long"):
        emas = [21]
        smas = [50, 200]
    elif trade_type == "swing_short":
        emas = [9]
        smas = [100]
    else:
        # scalp / day — use settings.json MAs, default SMA50
        ma_cfg = _settings.get_ma_config()
        emas   = ma_cfg.get("emas") or cfg["emas"]
        smas   = ma_cfg.get("smas") or [50, 200]

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=cfg["rsi_window"]).rsi()
    for p in emas:
        df[f"ema_{p}"] = ta.trend.EMAIndicator(df["close"], window=p).ema_indicator()
    for p in smas:
        df[f"sma_{p}"] = ta.trend.SMAIndicator(df["close"], window=p).sma_indicator()
    macd = ta.trend.MACD(df["close"])
    df["macd"]        = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"]   = macd.macd_diff()
    df["atr_14"]      = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
    df = _add_vwap(df)
    return df


# ── Market context ─────────────────────────────────────────────────────────

def _get_market_context() -> dict:
    out = {}
    for t in ["SPY", "QQQ", "$VIX"]:
        try:
            out[t] = _get_quote(t)
        except Exception:
            out[t] = {}
    return {
        "spy": out.get("SPY", {}),
        "qqq": out.get("QQQ", {}),
        "vix": out.get("$VIX", {}),
    }


# ── Options chain (disabled by default) ───────────────────────────────────

def _get_options_chain(ticker: str) -> dict:
    # TODO: GAMMA — add GEX calculation here when options enabled
    if not ENABLE_OPTIONS:
        return {"enabled": False}

    key = f"{ticker}:options"
    cached = cache_get(key)
    if cached:
        return cached

    resp = get_client().option_chains(ticker, strikeCount=10)
    if not resp.ok:
        return {"enabled": True, "error": resp.text}

    data = resp.json()
    result = {
        "enabled":          True,
        "underlying_price": data.get("underlyingPrice"),
        "put_call_ratio":   data.get("putCallRatio"),
        "volatility":       data.get("volatility"),
        "call_exp_map":     data.get("callExpDateMap", {}),
        "put_exp_map":      data.get("putExpDateMap",  {}),
    }
    cache_set(key, result, CACHE_TTL_OPTIONS)
    return result


# ── RTD stub ───────────────────────────────────────────────────────────────

def _get_rtd_quote(ticker: str) -> dict:
    # TODO: RTD — replace with WebSocket stream cache when ENABLE_RTD=true
    return {}


# ── Extended daily bars (swing) ────────────────────────────────────────────

def _get_daily_extended(ticker: str, period_years: int = 1) -> pd.DataFrame:
    key = f"{ticker}:daily_ext_{period_years}y"
    cached = cache_get(key)
    if cached is not None:
        return cached

    resp = get_client().price_history(
        symbol=ticker,
        periodType="year",
        period=period_years,
        frequencyType="daily",
        frequency=1,
        needExtendedHoursData=False,
    )
    if not resp.ok:
        return pd.DataFrame()

    candles = resp.json().get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
    df = df.sort_values("datetime").reset_index(drop=True)
    cache_set(key, df, CACHE_TTL_DAILY)
    return df


def _get_weekly(ticker: str) -> pd.DataFrame:
    key = f"{ticker}:weekly"
    cached = cache_get(key)
    if cached is not None:
        return cached

    resp = get_client().price_history(
        symbol=ticker,
        periodType="year",
        period=2,
        frequencyType="weekly",
        frequency=1,
        needExtendedHoursData=False,
    )
    if not resp.ok:
        return pd.DataFrame()

    candles = resp.json().get("candles", [])
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
    df = df.sort_values("datetime").reset_index(drop=True)
    cache_set(key, df, CACHE_TTL_DAILY)
    return df


# ── Main entry point ───────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=5)

async def collect_all(ticker: str, account_size: float = 25000, risk_percent: float = 2.0, trade_type: str = "day") -> dict:
    loop = asyncio.get_event_loop()

    is_swing    = trade_type in ("swing_short", "swing_medium", "swing_long")
    period_years = 1 if trade_type == "swing_short" else 2

    quote_fut   = loop.run_in_executor(_executor, _get_quote,          ticker)
    context_fut = loop.run_in_executor(_executor, _get_market_context)
    options_fut = loop.run_in_executor(_executor, _get_options_chain,  ticker)

    if is_swing:
        daily_fut    = loop.run_in_executor(_executor, _get_daily_extended, ticker, period_years)
        weekly_fut   = loop.run_in_executor(_executor, _get_weekly,         ticker)
        intraday_fut = loop.run_in_executor(_executor, lambda: pd.DataFrame())
    else:
        daily_fut    = loop.run_in_executor(_executor, _get_daily,    ticker)
        weekly_fut   = loop.run_in_executor(_executor, lambda: pd.DataFrame())
        intraday_fut = loop.run_in_executor(_executor, _get_intraday, ticker)

    quote, intraday_df, daily_df, weekly_df, market_ctx, options = await asyncio.gather(
        quote_fut, intraday_fut, daily_fut, weekly_fut, context_fut, options_fut
    )

    # Compute indicators
    if is_swing:
        df        = _compute_indicators(daily_df, trade_type) if not daily_df.empty else daily_df
        recent_df = df.tail(60).copy()
    else:
        df        = _compute_indicators(intraday_df, trade_type) if not intraday_df.empty else intraday_df
        recent_df = df.tail(DAY_TRADE_CONFIG["bars_to_ai"]).copy()

    # S/R levels from both timeframes
    sr_levels = _calc_sr_levels(intraday_df, daily_df, quote)

    # Long-term S/R cache + trend analysis (concurrent, lazy imports avoid circular dep)
    from sr_levels import get_levels as _get_sr_levels
    from trend_analysis import get_trend as _get_trend
    sr_cache_fut = loop.run_in_executor(_executor, _get_sr_levels, ticker)
    trend_fut    = loop.run_in_executor(_executor, _get_trend, ticker, daily_df)
    sr_cache, trend = await asyncio.gather(sr_cache_fut, trend_fut)

    # Bars for AI prompt — include all computed MA columns dynamically
    ma_cfg  = _settings.get_ma_config()
    ma_cols = ([f"ema_{p}" for p in (ma_cfg.get("emas") or [])] +
               [f"sma_{p}" for p in (ma_cfg.get("smas") or [])])
    cols = [c for c in (
        ["datetime", "open", "high", "low", "close", "volume", "rsi"]
        + ma_cols
        + ["macd", "macd_signal", "macd_hist", "vwap"]
    ) if c in recent_df.columns]
    bars_summary = recent_df[cols].round(4).tail(60).to_dict("records") if not recent_df.empty else []

    latest = recent_df.iloc[-1].to_dict() if not recent_df.empty else {}

    # Polygon fallback — if Schwab daily bars empty or client unavailable
    if daily_df.empty and _POLYGON_AVAILABLE:
        from config import POLYGON_API_KEY
        from datetime import date, timedelta
        if POLYGON_API_KEY:
            try:
                _to   = date.today().isoformat()
                _from = (date.today() - timedelta(days=30)).isoformat()
                # Check cache first
                _cached = _get_cached_bars(ticker, "1d")
                if _cached:
                    # Convert cached normalized bars to collector format
                    daily_bars = [{
                        "open":    b["open"],   "high":  b["high"],
                        "low":     b["low"],    "close": b["close"],
                        "volume":  b["volume"], "datetime": b["timestamp"],
                    } for b in _cached[-30:]]
                else:
                    _raw = _polygon_daily(ticker, _from, _to, POLYGON_API_KEY)
                    if _raw:
                        _cache_bars(_raw)
                        daily_bars = [{
                            "open":    b["open"],   "high":  b["high"],
                            "low":     b["low"],    "close": b["close"],
                            "volume":  b["volume"], "datetime": b["timestamp"],
                        } for b in _raw[-30:]]
                if daily_bars:
                    import pandas as _pd
                    daily_df = _pd.DataFrame(daily_bars)
                    daily_df["datetime"] = _pd.to_datetime(daily_df["datetime"], unit="ms")
                    daily_df = daily_df.sort_values("datetime").reset_index(drop=True)
            except Exception as _pe:
                logger.warning("Polygon daily fallback failed: %s", _pe)

    # Daily bars summary for AI
    daily_summary = []
    if not daily_df.empty:
        daily_cols = [c for c in ["datetime", "open", "high", "low", "close", "volume"] if c in daily_df.columns]
        daily_summary = daily_df[daily_cols].tail(10).round(4).to_dict("records")

    # Prev-day stats and daily ATR-14 from daily bars
    atr_14_daily = prev_close = prev_high = prev_low = prev_range = None
    if not daily_df.empty and len(daily_df) >= 2:
        _datr = ta.volatility.AverageTrueRange(
            daily_df["high"], daily_df["low"], daily_df["close"], window=14
        ).average_true_range()
        if not _datr.empty and not pd.isna(_datr.iloc[-1]):
            atr_14_daily = round(float(_datr.iloc[-1]), 4)
        _prev      = daily_df.iloc[-2]
        prev_close = round(float(_prev["close"]), 4)
        prev_high  = round(float(_prev["high"]),  4)
        prev_low   = round(float(_prev["low"]),   4)
        prev_range = round(prev_high - prev_low,  4)

    # Build indicators dict dynamically from computed MA columns
    indicators: dict = {
        "rsi":         round(float(latest.get("rsi")         or 0), 2),
        "macd":        round(float(latest.get("macd")        or 0), 4),
        "macd_signal": round(float(latest.get("macd_signal") or 0), 4),
        "macd_hist":   round(float(latest.get("macd_hist")   or 0), 4),
        "vwap":        round(float(latest.get("vwap") or 0), 4) if latest.get("vwap") else None,
        "prev_close":  prev_close,
        "prev_high":   prev_high,
        "prev_low":    prev_low,
        "prev_range":  prev_range,
        "atr_14":      atr_14_daily,
    }
    for col in ma_cols:
        indicators[col] = round(float(latest.get(col) or 0), 4) if latest.get(col) is not None else None

    # Weekly bars summary for swing
    weekly_summary = []
    if not weekly_df.empty:
        weekly_cols = [c for c in ["datetime", "open", "high", "low", "close", "volume"]
                       if c in weekly_df.columns]
        weekly_summary = weekly_df[weekly_cols].tail(20).round(4).to_dict("records")

    return {
        "ticker":       ticker,
        "quote":        quote,
        "market_ctx":   market_ctx,
        "latest_bars":  bars_summary,
        "daily_bars":   daily_summary,
        "weekly_bars":  weekly_summary,
        "sr_levels":    sr_levels,
        "sr_cache":     sr_cache,
        "trend":        trend,
        "options":      options,
        "indicators":   indicators,
        "total_bars":   len(df),
        "style":        "day_trading",
        "trade_type":   trade_type,
        "is_swing":     is_swing,
        "account_size": account_size,
        "risk_percent": risk_percent,
    }
