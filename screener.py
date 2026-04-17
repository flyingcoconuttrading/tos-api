"""
screener.py
-----------
Pure Python watchlist screener. Zero AI calls, zero Schwab writes.
Indicators: Multi-scale VWAP cloud, Triple StochRSI (Wilder), Adaptive Donchian.
Winsorization applied to closes before indicators and to component scores before combining.
Version: v2.4.0
"""

import numpy as np
import pandas as pd
from pathlib import Path
import json

# ── Constants ──────────────────────────────────────────────────────────────────
MIN_BARS            = 45   # minimum bars for period-21 StochRSI (2×21+3 buffer)
SWING_N             = 5    # bars each side for swing detection
VOLUME_BUCKET_COUNT = 50


# ── Wilder RSI ─────────────────────────────────────────────────────────────────

def _wilder_rsi(closes: list, period: int) -> list:
    """
    RSI using Wilder's exponential smoothing (factor = 1/period).
    Returns list same length as closes. First period values are None.
    """
    if len(closes) < period + 1:
        return [None] * len(closes)

    closes = [float(c) for c in closes]
    rsi    = [None] * period

    gains  = []
    losses = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period, len(closes)):
        diff     = closes[i] - closes[i - 1]
        gain     = max(diff, 0)
        loss     = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain)  / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs  = avg_gain / avg_loss
            rsi.append(round(100 - (100 / (1 + rs)), 4))

    return rsi


# ── Multi-scale VWAP ───────────────────────────────────────────────────────────

def multi_scale_vwap(bars: list) -> dict:
    """
    Compute VWAP anchored at 3 scales: last 5, 10, and all bars.
    Each bar: dict with high, low, close, volume.
    Returns dict with vwap_5, vwap_10, vwap_full, signal, raw_score.
    """
    def _vwap(b):
        tp  = [(float(x["high"]) + float(x["low"]) + float(x["close"])) / 3 for x in b]
        vol = [float(x["volume"]) for x in b]
        sv  = sum(v for v in vol)
        if sv == 0:
            return float(tp[-1]) if tp else 0.0
        return sum(t * v for t, v in zip(tp, vol)) / sv

    current = float(bars[-1]["close"])
    v5      = _vwap(bars[-5:])  if len(bars) >= 5  else _vwap(bars)
    v10     = _vwap(bars[-10:]) if len(bars) >= 10 else _vwap(bars)
    vfull   = _vwap(bars)

    above = current > v5 and current > v10 and current > vfull
    below = current < v5 and current < v10 and current < vfull

    if above:
        signal, raw_score = "ABOVE", 30.0
    elif below:
        signal, raw_score = "BELOW", -30.0
    else:
        signal, raw_score = "INSIDE", 0.0

    return {
        "vwap_5":    round(v5,    4),
        "vwap_10":   round(v10,   4),
        "vwap_full": round(vfull, 4),
        "signal":    signal,
        "raw_score": raw_score,
    }


# ── Triple Stochastic RSI ──────────────────────────────────────────────────────

def triple_stoch_rsi(closes: list) -> dict:
    """
    StochRSI at periods 8, 14, 21 using Wilder's smoothing.
    Returns dict with stoch_8, stoch_14, stoch_21, agreement, strength, raw_score.
    """
    def _stoch(rsi_vals, period):
        valid = [v for v in rsi_vals if v is not None]
        if len(valid) < period:
            return 50.0
        window = valid[-period:]
        mn, mx = min(window), max(window)
        last   = valid[-1]
        if mx == mn:
            return 50.0
        return round((last - mn) / (mx - mn) * 100, 4)

    stoch = {}
    for p in [8, 14, 21]:
        rsi_vals   = _wilder_rsi(closes, p)
        stoch[p]   = _stoch(rsi_vals, p)

    s8, s14, s21 = stoch[8], stoch[14], stoch[21]
    strength     = round((s8 + s14 + s21) / 3, 4)

    if s8 > 50 and s14 > 50 and s21 > 50:
        agreement = "BULLISH"
        raw_score = round(((strength - 50) / 50) * 40, 4)
    elif s8 < 50 and s14 < 50 and s21 < 50:
        agreement = "BEARISH"
        raw_score = round(-((50 - strength) / 50) * 40, 4)
    else:
        agreement = "MIXED"
        raw_score = 0.0

    return {
        "stoch_8":   s8,
        "stoch_14":  s14,
        "stoch_21":  s21,
        "agreement": agreement,
        "strength":  strength,
        "raw_score": raw_score,
    }


# ── Adaptive Donchian ──────────────────────────────────────────────────────────

def adaptive_donchian(bars: list, atr_period: int = 14) -> dict:
    """
    Donchian channel with ATR-adaptive lookback N (clamped 10-30).
    Returns dict with upper, lower, mid, n_used, atr, position, raw_score.
    """
    if len(bars) < atr_period + 1:
        return {
            "upper": 0, "lower": 0, "mid": 0,
            "n_used": 14, "atr": 0,
            "position": "ABOVE_MID", "raw_score": 0.0,
        }

    # Wilder ATR
    trs = []
    for i in range(1, len(bars)):
        h  = float(bars[i]["high"])
        l  = float(bars[i]["low"])
        pc = float(bars[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    atr = trs[0]
    for tr in trs[1:]:
        atr = (atr * (atr_period - 1) + tr) / atr_period

    current = float(bars[-1]["close"])
    atr_pct = atr / current if current else 0.01

    # Adaptive N
    if atr_pct < 0.005:
        n = 10
    elif atr_pct > 0.020:
        n = 30
    else:
        n = int(10 + (atr_pct - 0.005) / (0.020 - 0.005) * 20)
    n = max(10, min(30, n))

    window = bars[-n:]
    upper  = max(float(b["high"])  for b in window)
    lower  = min(float(b["low"])   for b in window)
    mid    = (upper + lower) / 2

    if current >= upper * 0.995:
        position, raw_score = "AT_UPPER", 30.0
    elif current <= lower * 1.005:
        position, raw_score = "AT_LOWER", -30.0
    elif current > mid:
        position, raw_score = "ABOVE_MID", 15.0
    else:
        position, raw_score = "BELOW_MID", -15.0

    return {
        "upper":     round(upper, 4),
        "lower":     round(lower, 4),
        "mid":       round(mid,   4),
        "n_used":    n,
        "atr":       round(atr,   4),
        "position":  position,
        "raw_score": raw_score,
    }


# ── Winsorization ──────────────────────────────────────────────────────────────

def winsorize(values: list, lower_pct: float = 0.05, upper_pct: float = 0.95) -> list:
    """Clip values to [lower_pct, upper_pct] percentile boundaries."""
    if len(values) < 4:
        return values
    arr   = np.array(values, dtype=float)
    lo    = float(np.percentile(arr, lower_pct * 100))
    hi    = float(np.percentile(arr, upper_pct * 100))
    return [float(np.clip(v, lo, hi)) for v in values]


# ── Score combiner ─────────────────────────────────────────────────────────────

def _combine_scores(vwap_raw: float, stoch_raw: float, don_raw: float,
                    score_threshold: int = 60) -> tuple:
    """
    Combine signed component scores (-100 to +100).
    Winsorize components before summing.
    Returns (display_score: float, direction: str).
    """
    components = winsorize([vwap_raw, stoch_raw, don_raw], 0.0, 1.0)
    total      = sum(components)  # -100 to +100

    if total >= score_threshold:
        direction = "LONG"
    elif total <= -score_threshold:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    return round(abs(total), 2), direction


# ── Main entry point ───────────────────────────────────────────────────────────

def score_ticker(bars: list, trade_type: str = "day",
                 score_threshold: int = 60) -> dict:
    """
    Full pipeline for one ticker. Returns scored result dict.

    bars: list of dicts with keys: open, high, low, close, volume
    """
    # Guard
    if len(bars) < MIN_BARS:
        return {
            "score":     0,
            "direction": "NEUTRAL",
            "passed":    False,
            "vwap":      {},
            "stoch_rsi": {},
            "donchian":  {},
            "bars_used": len(bars),
            "error":     f"Insufficient bars: {len(bars)} (need {MIN_BARS})",
        }

    # Step 1: winsorize closes (clean outlier candles)
    closes       = [float(b["close"]) for b in bars]
    clean_closes = winsorize(closes, 0.02, 0.98)
    clean_bars   = []
    for i, b in enumerate(bars):
        cb = dict(b)
        cb["close"] = clean_closes[i]
        clean_bars.append(cb)

    # Step 2: run indicators on clean data
    vwap   = multi_scale_vwap(clean_bars)
    stoch  = triple_stoch_rsi(clean_closes)
    don    = adaptive_donchian(clean_bars)

    # Step 3: combine (winsorizes component scores internally)
    display_score, direction = _combine_scores(
        vwap["raw_score"], stoch["raw_score"], don["raw_score"],
        score_threshold,
    )

    passed = display_score >= score_threshold and direction != "NEUTRAL"

    return {
        "score":     display_score,
        "direction": direction,
        "passed":    passed,
        "vwap":      vwap,
        "stoch_rsi": stoch,
        "donchian":  don,
        "bars_used": len(bars),
        "error":     None,
    }
