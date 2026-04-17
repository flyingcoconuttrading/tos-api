"""
trend_analysis.py
-----------------
Multi-timeframe trend analysis engine. Pure Python — zero AI calls.
Uses pandas + numpy only. Reuses sr_cache.db from sr_levels.py.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import ta

from sr_levels import DB_PATH as _DB_PATH

logger = logging.getLogger("tos_api.trend_analysis")

# ── Constants ──────────────────────────────────────────────────────────────
ADX_PERIOD      = 14
LINREG_PERIOD   = 60
HH_HL_LOOKBACK  = 10
CACHE_TTL_HOURS = 24


# ── DB init ────────────────────────────────────────────────────────────────

def _init_db():
    """Create trend_data table in sr_cache.db if not exists."""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trend_data (
            ticker          TEXT NOT NULL,
            calculated_at   TEXT NOT NULL,
            data            TEXT NOT NULL,
            PRIMARY KEY (ticker)
        )
    """)
    conn.commit()
    conn.close()


# ── Cache read/write ───────────────────────────────────────────────────────

def _load_cache(ticker: str) -> dict | None:
    try:
        conn = sqlite3.connect(_DB_PATH)
        row = conn.execute(
            "SELECT calculated_at, data FROM trend_data WHERE ticker = ?", (ticker,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        calculated_at = datetime.fromisoformat(row[0])
        if calculated_at.tzinfo is None:
            calculated_at = calculated_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - calculated_at > timedelta(hours=CACHE_TTL_HOURS):
            return None
        return json.loads(row[1])
    except Exception as e:
        logger.warning("trend_data cache load error: %s", e)
        return None


def _save_cache(ticker: str, data: dict):
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO trend_data (ticker, calculated_at, data) VALUES (?, ?, ?)",
            (ticker, now, json.dumps(data, default=str))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("trend_data cache save error: %s", e)


# ── ADX calculation ────────────────────────────────────────────────────────

def _compute_adx(df: pd.DataFrame, period: int = ADX_PERIOD) -> pd.Series:
    """Compute ADX using ta library."""
    return ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=period).adx()


# ── Linear regression ──────────────────────────────────────────────────────

def _linreg(closes: list, period: int = LINREG_PERIOD) -> dict:
    """
    Fit linear regression on last `period` closes using numpy.polyfit.
    Returns slope, r_squared, and direction (UP/DOWN/SIDEWAYS).
    """
    if len(closes) < 2:
        return {"slope": 0.0, "r_squared": 0.0, "direction": "SIDEWAYS"}

    n = min(period, len(closes))
    y = np.array(closes[-n:], dtype=float)
    x = np.arange(n, dtype=float)

    slope, intercept = np.polyfit(x, y, 1)

    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2     = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    mean_price = float(np.mean(y))
    threshold  = 0.05 * mean_price / n if n > 0 else 0.0

    if slope > threshold:
        direction = "UP"
    elif slope < -threshold:
        direction = "DOWN"
    else:
        direction = "SIDEWAYS"

    return {"slope": round(float(slope), 6), "r_squared": round(r2, 4), "direction": direction}


# ── HH/HL structure ────────────────────────────────────────────────────────

def _hh_hl_structure(swing_highs: list, swing_lows: list) -> str:
    """
    Classify price structure from last HH_HL_LOOKBACK swing points.
    Uses first 3 most-recent points (smallest bars_since).
    HH + HL → HH_HL, LH + LL → LH_LL, else MIXED.
    """
    highs = sorted(swing_highs[:HH_HL_LOOKBACK], key=lambda x: x["bars_since"])[:3]
    lows  = sorted(swing_lows[:HH_HL_LOOKBACK],  key=lambda x: x["bars_since"])[:3]

    hh = (len(highs) == 3 and
          highs[0]["price"] > highs[1]["price"] > highs[2]["price"])
    hl = (len(lows) == 3 and
          lows[0]["price"] > lows[1]["price"] > lows[2]["price"])

    lh = (len(highs) == 3 and
          highs[0]["price"] < highs[1]["price"] < highs[2]["price"])
    ll = (len(lows) == 3 and
          lows[0]["price"] < lows[1]["price"] < lows[2]["price"])

    if hh and hl:
        return "HH_HL"
    if lh and ll:
        return "LH_LL"
    return "MIXED"


# ── Trendline ──────────────────────────────────────────────────────────────

def _trendline(points: list, today_bar_index: int) -> float | None:
    """
    Fit a line through the last 3 swing points and project to today_bar_index.
    Returns None if fewer than 3 points.
    """
    if len(points) < 3:
        return None
    last3 = sorted(points, key=lambda x: x["bars_since"])[:3]
    xs    = [today_bar_index - p["bars_since"] for p in last3]
    ys    = [p["price"] for p in last3]
    slope, intercept = np.polyfit(xs, ys, 1)
    return round(float(slope * today_bar_index + intercept), 4)


# ── Trend for one timeframe ────────────────────────────────────────────────

_EMPTY_TF = {
    "direction": "SIDEWAYS", "strength": "NONE", "adx": None,
    "adx_interpretation": "NO_TREND", "linreg_slope": None, "linreg_r2": None,
    "momentum": "NEUTRAL", "structure": "MIXED", "trend_age_bars": 0,
    "trendline_support": None, "trendline_resistance": None,
    "trendline_distance_pct": None,
}


def _analyze_timeframe(df: pd.DataFrame, swing_highs: list,
                       swing_lows: list, label: str) -> dict:
    """
    Full trend analysis for one timeframe (daily or weekly).
    Returns a dict with direction, strength, ADX, linreg, momentum, structure,
    trend_age_bars, trendline support/resistance, and distance_pct.
    """
    if df.empty or len(df) < ADX_PERIOD + 1:
        return dict(_EMPTY_TF)

    closes        = df["close"].tolist()
    current_price = float(df["close"].iloc[-1])
    today_bar_idx = len(df) - 1

    # 1. ADX
    adx_series = _compute_adx(df)
    adx = 0.0
    if not adx_series.empty:
        last_adx = adx_series.iloc[-1]
        if not pd.isna(last_adx):
            adx = round(float(last_adx), 2)

    if adx < 20:
        adx_interp = "NO_TREND"
    elif adx < 40:
        adx_interp = "TRENDING"
    else:
        adx_interp = "STRONG"

    # 2. Linear regression
    lr        = _linreg(closes, LINREG_PERIOD)
    direction = lr["direction"]
    r2        = lr["r_squared"]

    # 3. Direction consensus — ADX < 20 overrides to SIDEWAYS
    if adx < 20:
        direction = "SIDEWAYS"

    # 4. Strength
    if adx >= 40 and r2 >= 0.7:
        strength = "STRONG"
    elif adx >= 20:
        strength = "MODERATE"
    else:
        strength = "WEAK"

    # 5. Momentum
    if direction == "SIDEWAYS":
        momentum = "NEUTRAL"
    else:
        lr_recent  = _linreg(closes, 20)
        lr_overall = _linreg(closes, 60)
        rs = lr_recent["slope"]
        os = lr_overall["slope"]
        if os != 0:
            if rs > os * 1.2:
                momentum = "ACCELERATING"
            elif rs < os * 0.8:
                momentum = "DECELERATING"
            else:
                momentum = "STEADY"
        else:
            momentum = "STEADY"

    # 6. HH/HL structure
    structure = _hh_hl_structure(swing_highs, swing_lows)

    # 7. Trend age — bars since most recent swing point
    if structure == "MIXED":
        trend_age_bars = 0
    else:
        all_swings = swing_highs + swing_lows
        if all_swings:
            trend_age_bars = min(p["bars_since"] for p in all_swings)
        else:
            trend_age_bars = 0

    # 8. Trendlines
    trendline_support    = None
    trendline_resistance = None
    if direction == "UP":
        trendline_support = _trendline(swing_lows, today_bar_idx)
    elif direction == "DOWN":
        trendline_resistance = _trendline(swing_highs, today_bar_idx)

    # 9. Trendline distance
    trendline_distance_pct = None
    tl_val = trendline_support if trendline_support is not None else trendline_resistance
    if tl_val is not None and current_price > 0:
        trendline_distance_pct = round(abs(current_price - tl_val) / current_price * 100, 2)

    return {
        "direction":              direction,
        "strength":               strength,
        "adx":                    adx,
        "adx_interpretation":     adx_interp,
        "linreg_slope":           lr["slope"],
        "linreg_r2":              r2,
        "momentum":               momentum,
        "structure":              structure,
        "trend_age_bars":         trend_age_bars,
        "trendline_support":      trendline_support,
        "trendline_resistance":   trendline_resistance,
        "trendline_distance_pct": trendline_distance_pct,
    }


# ── Weekly resample ────────────────────────────────────────────────────────

def _resample_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample daily OHLCV to weekly.
    Returns empty DataFrame if fewer than 20 weeks available.
    """
    if daily_df.empty:
        return pd.DataFrame()
    df = daily_df.copy()
    df = df.set_index("datetime")
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    weekly = df.resample("W").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()
    weekly = weekly.reset_index()
    if len(weekly) < 20:
        return pd.DataFrame()
    return weekly


# ── MTF alignment ──────────────────────────────────────────────────────────

def _mtf_alignment(daily: dict, weekly: dict) -> tuple[str, str, str]:
    """
    Determine multi-timeframe alignment, trade bias, and bias reason.
    Returns (mtf_alignment, trade_bias, bias_reason).
    """
    dd = daily.get("direction",  "SIDEWAYS")
    wd = weekly.get("direction", "SIDEWAYS")

    if dd == "UP"   and wd == "UP":
        return ("ALIGNED_BULLISH",
                "LONG_ONLY",
                "Both timeframes bullish — trade long pullbacks only")
    if dd == "DOWN" and wd == "DOWN":
        return ("ALIGNED_BEARISH",
                "SHORT_ONLY",
                "Both timeframes bearish — trade short bounces only")
    if dd == "UP"   and wd == "SIDEWAYS":
        return ("DAILY_UP_WEEKLY_SIDEWAYS",
                "LONG_PREFERRED",
                "Weekly consolidating, daily trending up")
    if dd == "DOWN" and wd == "SIDEWAYS":
        return ("DAILY_DOWN_WEEKLY_SIDEWAYS",
                "SHORT_PREFERRED",
                "Weekly consolidating, daily trending down")
    if dd == "UP"   and wd == "DOWN":
        return ("CONFLICT",
                "NEUTRAL",
                "Timeframe conflict — reduce size, wait for alignment")
    if dd == "DOWN" and wd == "UP":
        return ("CONFLICT",
                "NEUTRAL",
                "Timeframe conflict — reduce size, wait for alignment")
    # Both SIDEWAYS (or any remaining combo)
    return ("RANGING",
            "NEUTRAL",
            "No trend both timeframes — range trade only")


# ── Main entry point ───────────────────────────────────────────────────────

def get_trend(ticker: str, daily_df: pd.DataFrame = None) -> dict:
    """
    Public entry point. Returns multi-timeframe trend analysis dict.
    Checks cache first (TTL = CACHE_TTL_HOURS).
    Never raises — errors in result["error"].
    """
    _init_db()

    cached = _load_cache(ticker)
    if cached:
        return cached

    try:
        # Lazy imports to avoid circular dependency with data/collector.py
        if daily_df is None or (hasattr(daily_df, "empty") and daily_df.empty):
            from sr_levels import _fetch_daily_bars
            daily_df = _fetch_daily_bars(ticker)

        if daily_df is None or daily_df.empty:
            return {"ticker": ticker, "error": "no data"}

        weekly_df = _resample_weekly(daily_df)

        # Reuse sr_levels cache for swing points
        from sr_levels import get_levels as _get_sr_levels
        sr          = _get_sr_levels(ticker)
        swing_highs = sr.get("swing_highs", [])
        swing_lows  = sr.get("swing_lows",  [])

        daily_result  = _analyze_timeframe(daily_df,  swing_highs, swing_lows, "daily")
        if not weekly_df.empty:
            weekly_result = _analyze_timeframe(weekly_df, swing_highs, swing_lows, "weekly")
        else:
            weekly_result = dict(_EMPTY_TF)

        mtf_alignment, trade_bias, bias_reason = _mtf_alignment(daily_result, weekly_result)

        result = {
            "ticker":        ticker,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "daily":         daily_result,
            "weekly":        weekly_result,
            "mtf_alignment": mtf_alignment,
            "trade_bias":    trade_bias,
            "bias_reason":   bias_reason,
        }
        _save_cache(ticker, result)
        return result

    except Exception as e:
        logger.error("get_trend error for %s: %s", ticker, e)
        return {"ticker": ticker, "error": str(e)}
