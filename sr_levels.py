"""
sr_levels.py
------------
S/R cache engine. Pure Python — zero AI calls.
Uses pandas + numpy only (no scipy). Uses ta library for any indicator needs.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("tos_api.sr_levels")

# ── Constants ──────────────────────────────────────────────────────────────
LOOKBACK_DAYS       = 365
SWING_N             = 5
CACHE_TTL_HOURS     = 24
DB_PATH             = Path(__file__).parent / "data" / "sr_cache.db"
VOLUME_BUCKET_COUNT = 50


# ── DB init ────────────────────────────────────────────────────────────────

def _init_db():
    """Create sr_levels table if not exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sr_levels (
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
    """
    Load cached levels for ticker.
    Return None if no cache entry or cache older than CACHE_TTL_HOURS.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT calculated_at, data FROM sr_levels WHERE ticker = ?", (ticker,)
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
        logger.warning("sr_levels cache load error: %s", e)
        return None


def _save_cache(ticker: str, data: dict):
    """Upsert cache entry for ticker with current timestamp."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT OR REPLACE INTO sr_levels (ticker, calculated_at, data) VALUES (?, ?, ?)",
            (ticker, now, json.dumps(data, default=str))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("sr_levels cache save error: %s", e)


# ── Schwab history fetch ───────────────────────────────────────────────────

def _fetch_daily_bars(ticker: str) -> pd.DataFrame:
    """
    Fetch LOOKBACK_DAYS of daily bars from Schwab.
    Lazy-imports get_client() to avoid circular import with data/collector.py.
    Returns DataFrame with columns: datetime, open, high, low, close, volume.
    Returns empty DataFrame on error.
    """
    try:
        from data.collector import get_client
        client = get_client()
        resp = client.price_history(
            symbol=ticker,
            periodType="year",
            period=1,
            frequencyType="daily",
            frequency=1,
            needExtendedHoursData=False,
        )
        if not resp.ok:
            logger.warning("_fetch_daily_bars: Schwab %s for %s", resp.status_code, ticker)
            return pd.DataFrame()
        candles = resp.json().get("candles", [])
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles)
        df["datetime"] = pd.to_datetime(df["datetime"], unit="ms")
        df = df.sort_values("datetime").reset_index(drop=True)
        return df[["datetime", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error("_fetch_daily_bars error for %s: %s", ticker, e)
        return pd.DataFrame()


# ── Swing point detection ──────────────────────────────────────────────────

def _find_swings(df: pd.DataFrame, n: int = SWING_N) -> tuple[list, list]:
    """
    Identify swing highs and swing lows.
    Swing high at i: high[i] > max(high[i-n:i]) AND > max(high[i+1:i+n+1])
    Swing low  at i: low[i]  < min(low[i-n:i])  AND < min(low[i+1:i+n+1])
    Sorted by bars_since ascending (most recent first).
    """
    swing_highs: list[dict] = []
    swing_lows:  list[dict] = []
    avg_volume = float(df["volume"].mean()) if len(df) > 0 else 1.0

    for i in range(n, len(df) - n):
        high_i = float(df["high"].iloc[i])
        low_i  = float(df["low"].iloc[i])
        vol_i  = float(df["volume"].iloc[i])

        volume_ratio = vol_i / avg_volume if avg_volume > 0 else 0.0
        if volume_ratio >= 1.5:
            strength = "STRONG"
        elif volume_ratio >= 0.8:
            strength = "MODERATE"
        else:
            strength = "WEAK"

        bars_since = len(df) - 1 - i
        if bars_since > LOOKBACK_DAYS:
            continue

        dt = df["datetime"].iloc[i]
        date_str = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)

        entry = {
            "volume":       int(vol_i),
            "avg_volume":   int(avg_volume),
            "volume_ratio": round(volume_ratio, 2),
            "strength":     strength,
            "bars_since":   bars_since,
            "date":         date_str,
        }

        prev_highs = df["high"].iloc[i - n:i]
        next_highs = df["high"].iloc[i + 1:i + n + 1]
        if not prev_highs.empty and not next_highs.empty:
            if high_i > prev_highs.max() and high_i > next_highs.max():
                swing_highs.append({"price": round(high_i, 4), **entry})

        prev_lows = df["low"].iloc[i - n:i]
        next_lows = df["low"].iloc[i + 1:i + n + 1]
        if not prev_lows.empty and not next_lows.empty:
            if low_i < prev_lows.min() and low_i < next_lows.min():
                swing_lows.append({"price": round(low_i, 4), **entry})

    swing_highs.sort(key=lambda x: x["bars_since"])
    swing_lows.sort(key=lambda x: x["bars_since"])
    return swing_highs, swing_lows


# ── Volume profile ─────────────────────────────────────────────────────────

def _volume_profile(df: pd.DataFrame) -> tuple[list, list]:
    """
    Build a simple volume profile by bucketing price range into
    VOLUME_BUCKET_COUNT equal buckets and summing volume per bucket.
    Returns (hvn_zones, lvn_zones) sorted by price ascending.
    """
    price_min = float(df["low"].min())
    price_max = float(df["high"].max())
    if price_max <= price_min:
        return [], []

    bucket_size = (price_max - price_min) / VOLUME_BUCKET_COUNT
    buckets = np.zeros(VOLUME_BUCKET_COUNT)

    typical = (df["high"] + df["low"] + df["close"]) / 3
    for idx in range(len(df)):
        tp  = float(typical.iloc[idx])
        vol = float(df["volume"].iloc[idx])
        b   = int((tp - price_min) / bucket_size)
        b   = min(b, VOLUME_BUCKET_COUNT - 1)
        buckets[b] += vol

    total_volume   = buckets.sum()
    avg_bucket_vol = total_volume / VOLUME_BUCKET_COUNT if VOLUME_BUCKET_COUNT > 0 else 0

    hvn_zones: list[dict] = []
    lvn_zones: list[dict] = []
    for i in range(VOLUME_BUCKET_COUNT):
        b_low  = round(price_min + i * bucket_size, 4)
        b_high = round(price_min + (i + 1) * bucket_size, 4)
        bvol   = int(buckets[i])
        if avg_bucket_vol > 0:
            if buckets[i] >= 1.5 * avg_bucket_vol:
                hvn_zones.append({"low": b_low, "high": b_high, "total_volume": bvol, "strength": "STRONG"})
            elif buckets[i] <= 0.5 * avg_bucket_vol:
                lvn_zones.append({"low": b_low, "high": b_high, "total_volume": bvol, "strength": "WEAK"})

    hvn_zones.sort(key=lambda x: x["low"])
    lvn_zones.sort(key=lambda x: x["low"])
    return hvn_zones, lvn_zones


# ── Key levels ─────────────────────────────────────────────────────────────

def _key_levels(df: pd.DataFrame) -> dict:
    """Compute yearly high/low and 6-month high/low with date and volume_ratio."""
    avg_volume = float(df["volume"].mean()) if len(df) > 0 else 1.0

    def _fmt(row, price_col: str, include_vr: bool = True) -> dict:
        price = round(float(row[price_col]), 4)
        dt    = row["datetime"]
        date  = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
        out   = {"price": price, "date": date}
        if include_vr:
            vol = float(row["volume"])
            out["volume_ratio"] = round(vol / avg_volume, 2) if avg_volume > 0 else 0.0
        return out

    yearly_high_row = df.loc[df["high"].idxmax()]
    yearly_low_row  = df.loc[df["low"].idxmin()]

    last_126    = df.tail(126)
    six_hi_row  = last_126.loc[last_126["high"].idxmax()]
    six_lo_row  = last_126.loc[last_126["low"].idxmin()]

    return {
        "yearly_high": _fmt(yearly_high_row, "high"),
        "yearly_low":  _fmt(yearly_low_row,  "low"),
        "6m_high":     _fmt(six_hi_row, "high", include_vr=False),
        "6m_low":      _fmt(six_lo_row, "low",  include_vr=False),
    }


# ── Main entry point ───────────────────────────────────────────────────────

_EMPTY = {
    "swing_highs": [], "swing_lows": [],
    "hvn_zones":   [], "lvn_zones":  [],
    "yearly_high": None, "yearly_low": None,
    "6m_high":     None, "6m_low":    None,
}


def get_levels(ticker: str) -> dict:
    """
    Public entry point. Returns S/R levels dict.
    Checks cache first (TTL = CACHE_TTL_HOURS).
    Never raises — errors in result["error"].
    """
    _init_db()

    cached = _load_cache(ticker)
    if cached:
        return cached

    df = _fetch_daily_bars(ticker)
    if df.empty:
        return {"ticker": ticker, "error": "no data", "lookback_days": LOOKBACK_DAYS, **_EMPTY}

    try:
        swing_highs, swing_lows = _find_swings(df)
        hvn_zones, lvn_zones    = _volume_profile(df)
        key_lvls                = _key_levels(df)

        result = {
            "ticker":        ticker,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days": LOOKBACK_DAYS,
            "swing_highs":   swing_highs,
            "swing_lows":    swing_lows,
            "yearly_high":   key_lvls["yearly_high"],
            "yearly_low":    key_lvls["yearly_low"],
            "6m_high":       key_lvls["6m_high"],
            "6m_low":        key_lvls["6m_low"],
            "hvn_zones":     hvn_zones,
            "lvn_zones":     lvn_zones,
        }
        _save_cache(ticker, result)
        return result
    except Exception as e:
        logger.error("get_levels error for %s: %s", ticker, e)
        return {"ticker": ticker, "error": str(e), "lookback_days": LOOKBACK_DAYS, **_EMPTY}


def refresh_cache(ticker: str) -> dict:
    """Force refresh regardless of TTL. Deletes cache entry then re-calculates."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM sr_levels WHERE ticker = ?", (ticker,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("refresh_cache delete error for %s: %s", ticker, e)
    return get_levels(ticker)
