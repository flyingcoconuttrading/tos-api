# SCHWAB_ENGINE_CONTEXT.md
<!-- Generated 2026-03-18. Machine-readable. Source-accurate. No prose summaries. -->

---

## FILE INVENTORY

| Path | Role |
|---|---|
| `data/collector.py` | ACTIVE — primary collector used by checker.py |
| `collector.py` (root) | LEGACY — older version, no caching, no S/R, not imported by checker.py |
| `schwab_auth.py` | One-shot OAuth login helper (not used at runtime) |
| `cache/store.py` | In-memory TTL cache backing data/collector.py |
| `preprocessor.py` | Python pre-processor (no API calls) |
| `utils.py` | Shared helpers |
| `config.py` | All env keys, TTLs, feature flags |
| `settings.py` | Persistent MA config from data/settings.json |

> `checker.py` imports from `data/collector.py`, NOT root `collector.py`.

---

## 1. FULL SOURCE — data/collector.py (ACTIVE)

```python
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
import pandas as pd
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

load_dotenv()

# ── Schwab client singleton ────────────────────────────────────────────────
_client = None

def get_client():
    global _client
    if _client is None:
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
    levels = {
        "intraday": {},
        "daily":    {},
        "key_references": {},
    }

    # ── Daily levels ──────────────────────────────────────────────────────
    if not daily_df.empty and len(daily_df) >= 2:
        today_row  = daily_df.iloc[-1]
        yest_row   = daily_df.iloc[-2]

        levels["daily"]["pdc"] = round(float(yest_row["close"]), 4)
        levels["daily"]["pdh"] = round(float(yest_row["high"]),  4)
        levels["daily"]["pdl"] = round(float(yest_row["low"]),   4)

        week = daily_df.tail(5)
        levels["daily"]["weekly_high"] = round(float(week["high"].max()), 4)
        levels["daily"]["weekly_low"]  = round(float(week["low"].min()),  4)

        levels["daily"]["monthly_high"] = round(float(daily_df["high"].max()), 4)
        levels["daily"]["monthly_low"]  = round(float(daily_df["low"].min()),  4)

    # ── Intraday levels ───────────────────────────────────────────────────
    if not intraday_df.empty:
        today = intraday_df[intraday_df["datetime"].dt.date == date.today()]
        if not today.empty:
            opening = today.head(30)
            levels["intraday"]["opening_range_high"] = round(float(opening["high"].max()), 4)
            levels["intraday"]["opening_range_low"]  = round(float(opening["low"].min()),  4)

            levels["intraday"]["today_high"] = round(float(today["high"].max()), 4)
            levels["intraday"]["today_low"]  = round(float(today["low"].min()),  4)

            typical = (today["high"] + today["low"] + today["close"]) / 3
            vwap = (typical * today["volume"]).cumsum() / today["volume"].cumsum()
            levels["intraday"]["vwap"] = round(float(vwap.iloc[-1]), 4)

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

def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    cfg    = DAY_TRADE_CONFIG
    ma_cfg = _settings.get_ma_config()
    emas   = ma_cfg.get("emas") or cfg["emas"]
    smas   = ma_cfg.get("smas") or cfg["smas"]

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


# ── Main entry point ───────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=5)

async def collect_all(ticker: str, account_size: float = 25000, risk_percent: float = 2.0) -> dict:
    loop = asyncio.get_event_loop()

    quote_fut    = loop.run_in_executor(_executor, _get_quote,          ticker)
    intraday_fut = loop.run_in_executor(_executor, _get_intraday,       ticker)
    daily_fut    = loop.run_in_executor(_executor, _get_daily,          ticker)
    context_fut  = loop.run_in_executor(_executor, _get_market_context)
    options_fut  = loop.run_in_executor(_executor, _get_options_chain,  ticker)

    quote, intraday_df, daily_df, market_ctx, options = await asyncio.gather(
        quote_fut, intraday_fut, daily_fut, context_fut, options_fut
    )

    df        = _compute_indicators(intraday_df) if not intraday_df.empty else intraday_df
    recent_df = df.tail(DAY_TRADE_CONFIG["bars_to_ai"]).copy()

    sr_levels = _calc_sr_levels(intraday_df, daily_df, quote)

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

    daily_summary = []
    if not daily_df.empty:
        daily_cols = [c for c in ["datetime", "open", "high", "low", "close", "volume"] if c in daily_df.columns]
        daily_summary = daily_df[daily_cols].tail(10).round(4).to_dict("records")

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

    return {
        "ticker":       ticker,
        "quote":        quote,
        "market_ctx":   market_ctx,
        "latest_bars":  bars_summary,
        "daily_bars":   daily_summary,
        "sr_levels":    sr_levels,
        "options":      options,
        "indicators":   indicators,
        "total_bars":   len(df),
        "style":        "day_trading",
        "account_size": account_size,
        "risk_percent": risk_percent,
    }
```

---

## 2. FULL SOURCE — utils.py

```python
"""
utils.py — Shared helpers for tos-api.
"""
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def is_market_hours() -> bool:
    """True during regular session: Mon-Fri 9:30–16:00 ET."""
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dtime(9, 30) <= t < dtime(16, 0)


def get_price(quote: dict) -> float | None:
    """
    Return LAST during market hours, MARK outside hours.
    Falls back to the other if one is missing/None.
    """
    if is_market_hours():
        return quote.get("last") or quote.get("mark")
    return quote.get("mark") or quote.get("last")
```

---

## 3. FULL SOURCE — schwab_auth.py (one-shot OAuth helper, not runtime)

```python
import schwab

client = schwab.auth.client_from_login_flow(
    api_key="YOUR_APP_KEY",
    app_secret="YOUR_APP_SECRET",
    callback_url="https://127.0.0.1",
    token_path="token.json"
)

print("Success! token.json saved.")
```

> Runtime auth is handled by `schwabdev.Client(tokens_db=SCHWAB_TOKENS_DB)`.
> `schwabdev` reads/writes `tokens.db` (SQLite) and auto-refreshes tokens transparently.
> No manual token refresh logic exists in this codebase — `schwabdev` owns that lifecycle.

---

## 4. SCHWAB API ENDPOINTS CALLED

### Library: `schwabdev` (PyPI)
All calls go through `schwabdev.Client`. The underlying Schwab API base URL is:
```
https://api.schwabapi.com/marketdata/v1/
```

### 4a. Quote endpoint
```
GET https://api.schwabapi.com/marketdata/v1/quotes
```
Called via: `get_client().quote(ticker)`

**Parameters (schwabdev wraps these):**
```
symbols = ticker   (e.g. "AAPL", "SPY", "$VIX")
fields  = quote    (implicit)
```

**Raw response shape:**
```json
{
  "AAPL": {
    "quote": {
      "lastPrice":               float,
      "bidPrice":                float,
      "askPrice":                float,
      "totalVolume":             int,
      "openPrice":               float,
      "highPrice":               float,
      "lowPrice":                float,
      "closePrice":              float,
      "netPercentChange":        float,
      "netPercentChangeInDouble": float
    }
  }
}
```

**Note on field name divergence:**
- `data/collector.py` (active) uses: `quote.get("netPercentChange")`
- `collector.py` (legacy root) uses: `quote.get("netPercentChangeInDouble")`

### 4b. Price history endpoint — intraday
```
GET https://api.schwabapi.com/marketdata/v1/pricehistory
```
Called via: `get_client().price_history(...)`

**Parameters (active data/collector.py):**
```python
symbol                = ticker
periodType            = "day"
period                = 5          # lookback_days from DAY_TRADE_CONFIG
frequencyType         = "minute"
frequency             = 1
needExtendedHoursData = False
```

**Parameters (legacy root collector.py — different kwarg style):**
```python
symbol                  = ticker
period_type             = "day"
period                  = 5
frequency_type          = "minute"
frequency               = 1
need_extended_hours_data = False
```

**Raw response shape:**
```json
{
  "candles": [
    {
      "open":     float,
      "high":     float,
      "low":      float,
      "close":    float,
      "volume":   int,
      "datetime": int    // epoch milliseconds
    }
  ],
  "symbol":  "AAPL",
  "empty":   false
}
```

### 4c. Price history endpoint — daily bars
```
GET https://api.schwabapi.com/marketdata/v1/pricehistory
```
Called via: `get_client().price_history(...)`

**Parameters:**
```python
symbol                = ticker
periodType            = "month"
period                = 1
frequencyType         = "daily"
frequency             = 1
needExtendedHoursData = False
```

**Response shape:** same candles structure as intraday.

### 4d. Options chain endpoint (ENABLE_OPTIONS=false by default)
```
GET https://api.schwabapi.com/marketdata/v1/chains
```
Called via: `get_client().option_chains(ticker, strikeCount=10)`

**Parameters:**
```
symbol      = ticker
strikeCount = 10
```

**Response fields extracted:**
```python
data.get("underlyingPrice")       # float
data.get("putCallRatio")          # float
data.get("volatility")            # float
data.get("callExpDateMap", {})    # nested dict: expiry -> strike -> [contract]
data.get("putExpDateMap",  {})    # nested dict: expiry -> strike -> [contract]
```

### 4e. Authentication / token management
```
POST https://api.schwabapi.com/v1/oauth/token
```
Handled entirely by `schwabdev` internals. `tokens.db` is a SQLite file at path
`SCHWAB_TOKENS_DB` (default: `"tokens.db"`). `schwabdev.Client` auto-refreshes
access tokens before expiry without any application-level logic.

---

## 5. DATA FIELDS RETURNED AND HOW THEY ARE KEYED

### 5a. quote dict (from `_get_quote`)
```python
{
    "symbol":     str,    # ticker passed in
    "last":       float,  # lastPrice
    "bid":        float,  # bidPrice
    "ask":        float,  # askPrice
    "volume":     int,    # totalVolume
    "open":       float,  # openPrice
    "high":       float,  # highPrice (today's intraday high)
    "low":        float,  # lowPrice  (today's intraday low)
    "prev_close": float,  # closePrice (previous session close)
    "change_pct": float,  # netPercentChange
}
```

### 5b. market_ctx dict (from `_get_market_context`)
```python
{
    "spy": { ...same quote shape as 5a... },
    "qqq": { ...same quote shape as 5a... },
    "vix": { ...same quote shape as 5a... },
}
```
VIX ticker queried: `"$VIX"` in active collector, `"$VIX.X"` in legacy root collector.

### 5c. indicators dict
All values are from the last row of the intraday DataFrame after indicator computation.
ATR-14 is computed from the **daily** DataFrame, not intraday.

```python
{
    "rsi":         float,        # RSI(14) on 1-min close
    "macd":        float,        # MACD line
    "macd_signal": float,        # MACD signal line
    "macd_hist":   float,        # MACD histogram (diff)
    "vwap":        float | None, # VWAP (today's bars only; None if no today data)
    "prev_close":  float | None, # daily_df.iloc[-2]["close"]
    "prev_high":   float | None, # daily_df.iloc[-2]["high"]
    "prev_low":    float | None, # daily_df.iloc[-2]["low"]
    "prev_range":  float | None, # prev_high - prev_low
    "atr_14":      float | None, # ATR(14) on daily bars
    # Dynamic MA keys — depend on settings.json / DAY_TRADE_CONFIG:
    "ema_9":       float | None,
    "ema_20":      float | None,
    "sma_20":      float | None,
    "sma_50":      float | None,
    "sma_100":     float | None,
    "sma_200":     float | None,
    # Additional EMA/SMA keys if configured in settings.json
}
```

### 5d. sr_levels dict (from `_calc_sr_levels`)
```python
{
    "intraday": {
        "opening_range_high": float,  # high of first 30 1-min bars today
        "opening_range_low":  float,  # low  of first 30 1-min bars today
        "today_high":         float,  # max high of all today bars
        "today_low":          float,  # min low  of all today bars
        "vwap":               float,  # cumulative VWAP (today only)
    },
    "daily": {
        "pdc":          float,  # previous day close  (daily_df.iloc[-2]["close"])
        "pdh":          float,  # previous day high   (daily_df.iloc[-2]["high"])
        "pdl":          float,  # previous day low    (daily_df.iloc[-2]["low"])
        "weekly_high":  float,  # max high of last 5 daily bars
        "weekly_low":   float,  # min low  of last 5 daily bars
        "monthly_high": float,  # max high of all daily bars in window (~1 month)
        "monthly_low":  float,  # min low  of all daily bars in window
    },
    "key_references": {
        # Flat merge of intraday + daily dicts above
        "pdc": float, "pdh": float, "pdl": float,
        "weekly_high": float, "weekly_low": float,
        "monthly_high": float, "monthly_low": float,
        "opening_range_high": float, "opening_range_low": float,
        "today_high": float, "today_low": float,
        "vwap": float,
    }
}
```

### 5e. latest_bars list (intraday bars for AI)
```python
# List of dicts, up to 60 records, from recent_df.tail(60).to_dict("records")
[
    {
        "datetime":    str,    # ISO timestamp (pandas Timestamp serialized)
        "open":        float,
        "high":        float,
        "low":         float,
        "close":       float,
        "volume":      int,
        "rsi":         float,
        "ema_9":       float,  # if configured
        "ema_20":      float,  # if configured
        "sma_20":      float,  # if configured
        "sma_50":      float,  # if configured
        "sma_100":     float,  # if configured
        "sma_200":     float,  # if configured
        "macd":        float,
        "macd_signal": float,
        "macd_hist":   float,
        "vwap":        float | None,
    },
    # ... up to 60 records
]
```

### 5f. daily_bars list (daily bars for AI)
```python
# List of dicts, last 10 daily bars
[
    {
        "datetime": str,
        "open":     float,
        "high":     float,
        "low":      float,
        "close":    float,
        "volume":   int,
    },
    # ... up to 10 records
]
```

### 5g. options dict
```python
# When ENABLE_OPTIONS=false (default):
{"enabled": False}

# When ENABLE_OPTIONS=true and call succeeds:
{
    "enabled":          True,
    "underlying_price": float,
    "put_call_ratio":   float,
    "volatility":       float,
    "call_exp_map":     dict,   # Schwab callExpDateMap structure
    "put_exp_map":      dict,   # Schwab putExpDateMap structure
}
```

---

## 6. collect_all() SIGNATURE AND RETURN SHAPE

### Active (data/collector.py)
```python
async def collect_all(
    ticker:       str,
    account_size: float = 25000,
    risk_percent: float = 2.0,
) -> dict:
```

### Return shape
```python
{
    "ticker":       str,          # uppercased ticker
    "quote":        dict,         # see 5a
    "market_ctx":   dict,         # see 5b
    "latest_bars":  list[dict],   # see 5e — up to 60 1-min bars with indicators
    "daily_bars":   list[dict],   # see 5f — last 10 daily bars
    "sr_levels":    dict,         # see 5d
    "options":      dict,         # see 5g
    "indicators":   dict,         # see 5c
    "total_bars":   int,          # total rows in intraday DataFrame before tail()
    "style":        "day_trading",
    "account_size": float,
    "risk_percent": float,
}
```

### Legacy (root collector.py) — NOT imported by checker.py
```python
async def collect_all(ticker: str) -> dict:
# Returns subset: no sr_levels, no daily_bars, no options, no account_size/risk_percent
# indicators dict is hardcoded (no dynamic MA support)
```

---

## 7. HOW quotes, indicators, market_ctx, sr_levels, intraday ARE STRUCTURED

See sections 5a–5f above for full field-by-field breakdown.

**Key structural notes:**
- `quote["high"]` / `quote["low"]` = today's intraday high/low from the quote endpoint (live)
- `sr_levels["daily"]["pdh"]` / `["pdl"]` = yesterday's high/low from daily bars (computed)
- `indicators["vwap"]` = same as `sr_levels["intraday"]["vwap"]` (both computed from today's 1-min bars)
- `indicators["atr_14"]` = daily ATR, NOT intraday ATR
- `latest_bars` is capped at 60 records for AI token budget; `total_bars` reflects full intraday history
- MA columns in `latest_bars` and `indicators` are dynamic: they depend on `settings.json` via `settings.get_ma_config()`

**checker.py adds two more keys after collect_all() returns:**
```python
market_data["pre"]          = preprocessor.run(market_data)   # timing, regime, sizing
market_data["trade_type"]   = "day" | "swing"
market_data["tomorrow_setup"] = bool                           # True if market closed
market_data["gap_detection"]  = dict                          # from settings.json
```

---

## 8. RATE LIMITS, CACHING, TOKEN REFRESH

### Cache (cache/store.py)
```python
# In-memory dict, thread-safe (threading.Lock), process-lifetime only (no persistence).

# TTLs (from config.py):
CACHE_TTL_QUOTE    = 15        # seconds — quote per ticker
CACHE_TTL_INTRADAY = 60        # seconds — 1-min bars per ticker
CACHE_TTL_DAILY    = 6 * 3600  # seconds (6 hours) — daily bars per ticker
CACHE_TTL_OPTIONS  = 5 * 60    # seconds (5 min) — options chain per ticker

# Cache keys:
"{ticker}:quote"     # e.g. "AAPL:quote"
"{ticker}:intraday"  # e.g. "AAPL:intraday"
"{ticker}:daily"     # e.g. "AAPL:daily"
"{ticker}:options"   # e.g. "AAPL:options"
# Market context: SPY, QQQ, $VIX each get their own ":quote" cache entries

# Cache API:
cache_get(key)              -> Any | None   (returns None if expired or missing)
cache_set(key, value, ttl)  -> None
cache_store.delete(key)     -> None
cache_store.clear_ticker(ticker) -> None    # removes all keys prefixed "ticker:"
cache_store.stats()         -> {"total_keys": int, "live_keys": int}
```

### Schwab API rate limits
No explicit rate limit handling in application code. `schwabdev` does not implement retry
or backoff. Schwab's published limits: 120 requests/minute per app key.

### Token refresh
Fully managed by `schwabdev.Client`. Tokens stored in SQLite at `SCHWAB_TOKENS_DB`
(default path: `"tokens.db"` in working directory). Access token auto-refreshed before
expiry using the stored refresh token. No application code involved.

### Concurrency
```python
_executor = ThreadPoolExecutor(max_workers=5)
# collect_all() fires 5 concurrent fetches via asyncio.gather():
#   _get_quote(ticker)
#   _get_intraday(ticker)
#   _get_daily(ticker)
#   _get_market_context()       # internally sequential: SPY, QQQ, $VIX
#   _get_options_chain(ticker)  # no-op when ENABLE_OPTIONS=false
```

---

## 9. FULL SOURCE — preprocessor.py

```python
"""
preprocessor.py
---------------
Python pre-processor for Trade Checker.
Runs BEFORE Claude agents to compute cheap/deterministic facts:
  - timing_flags   : session timing, open/lunch/close windows
  - market_regime  : SPY/QQQ/VIX classification
  - position_size  : max risk, shares, size recommendation

No API calls. No AI. Just math.
"""

from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


# ── Timing ─────────────────────────────────────────────────────────────────

def _compute_timing() -> dict:
    now = datetime.now(ET)
    t   = now.time()
    wd  = now.weekday()  # 0=Mon … 6=Sun

    if wd >= 5:
        session = "weekend"
    elif t < dtime(9, 30):
        session = "pre_market"
    elif t >= dtime(16, 0):
        session = "after_hours"
    else:
        session = "regular"

    return {
        "now_et":      now.strftime("%H:%M ET"),
        "session":     session,
        "is_weekend":  wd >= 5,
        "near_open":   dtime(9, 30) <= t <= dtime(10, 15),
        "is_lunch":    dtime(11, 45) <= t <= dtime(13, 15),
        "near_close":  dtime(15, 30) <= t < dtime(16, 0),
    }


# ── Market regime ───────────────────────────────────────────────────────────

def _compute_regime(market_ctx: dict) -> dict:
    spy = market_ctx.get("spy", {})
    qqq = market_ctx.get("qqq", {})
    vix = market_ctx.get("vix", {})

    spy_chg = float(spy.get("change_pct") or 0)
    qqq_chg = float(qqq.get("change_pct") or 0)
    vix_val = float(vix.get("last")       or 0)

    spy_trend = "up"   if spy_chg >  0.5 else ("down" if spy_chg < -0.5 else "flat")
    qqq_trend = "up"   if qqq_chg >  0.5 else ("down" if qqq_chg < -0.5 else "flat")

    if   vix_val < 15:  vix_level = "LOW"
    elif vix_val < 20:  vix_level = "NORMAL"
    elif vix_val < 30:  vix_level = "ELEVATED"
    else:               vix_level = "EXTREME"

    if vix_val >= 30:
        regime = "HIGH_VOLATILITY"
    elif spy_trend == "up"   and qqq_trend == "up":
        regime = "TRENDING_UP"
    elif spy_trend == "down" and qqq_trend == "down":
        regime = "TRENDING_DOWN"
    elif spy_trend != qqq_trend or (spy_trend == "flat" and qqq_trend == "flat"):
        regime = "CHOPPY"
    elif spy_trend == "up":
        regime = "RISK_ON"
    else:
        regime = "RISK_OFF"

    return {
        "spy_trend":       spy_trend,
        "spy_change_pct":  round(spy_chg, 2),
        "qqq_trend":       qqq_trend,
        "qqq_change_pct":  round(qqq_chg, 2),
        "vix":             round(vix_val, 2),
        "vix_level":       vix_level,
        "regime":          regime,
    }


# ── Position size ───────────────────────────────────────────────────────────

def _compute_position(account_size: float, risk_percent: float) -> dict:
    max_risk = round(account_size * risk_percent / 100, 2)
    tiers = {
        "full":    int(max_risk / 1),
        "half":    int(max_risk / 1 * 0.5),
        "quarter": int(max_risk / 1 * 0.25),
    }
    return {
        "account_size":      account_size,
        "risk_percent":      risk_percent,
        "max_risk_dollars":  max_risk,
        "tier_max_risk":     tiers,
        "note":              "suggested_shares = max_risk / stop_distance (agents compute final)",
    }


# ── Public entry point ──────────────────────────────────────────────────────

def run(market_data: dict) -> dict:
    """
    Returns pre-computed context dict. Call this BEFORE agent dispatch.
    Inject result as market_data['pre'] so agents can read it.
    """
    return {
        "timing_flags":  _compute_timing(),
        "market_regime": _compute_regime(market_data.get("market_ctx", {})),
        "position_size": _compute_position(
            account_size = market_data.get("account_size", 25000),
            risk_percent = market_data.get("risk_percent", 2.0),
        ),
    }
```

---

## 10. ENV KEYS AND CONFIG.PY ENTRIES (KEY NAMES ONLY)

### .env keys required
```
ANTHROPIC_API_KEY
SCHWAB_APP_KEY
SCHWAB_APP_SECRET
SCHWAB_CALLBACK_URL     # default: https://127.0.0.1
SCHWAB_TOKENS_DB        # default: tokens.db
DB_HOST                 # default: localhost
DB_PORT                 # default: 5432
DB_NAME                 # default: stock_checker
DB_USER                 # default: postgres
DB_PASSWORD
ENABLE_OPTIONS          # default: false
ENABLE_RTD              # default: false
ENABLE_NEWS             # default: false
ENABLE_ECON_CAL         # default: false
```

### config.py full source
```python
import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

# ── Schwab API ─────────────────────────────────────────────────────────────
SCHWAB_APP_KEY      = os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET   = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_CALLBACK_URL = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
SCHWAB_TOKENS_DB    = os.getenv("SCHWAB_TOKENS_DB", "tokens.db")

# ── PostgreSQL ─────────────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = os.getenv("DB_PORT",     "5432")
DB_NAME     = os.getenv("DB_NAME",     "stock_checker")
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_URL      = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Feature Flags ──────────────────────────────────────────────────────────
ENABLE_OPTIONS  = os.getenv("ENABLE_OPTIONS",  "false").lower() == "true"
ENABLE_RTD      = os.getenv("ENABLE_RTD",      "false").lower() == "true"
ENABLE_NEWS     = os.getenv("ENABLE_NEWS",     "false").lower() == "true"
ENABLE_ECON_CAL = os.getenv("ENABLE_ECON_CAL", "false").lower() == "true"

# ── Cache TTLs (seconds) ───────────────────────────────────────────────────
CACHE_TTL_INTRADAY = 60
CACHE_TTL_DAILY    = 6 * 3600
CACHE_TTL_OPTIONS  = 5 * 60
CACHE_TTL_QUOTE    = 15

# ── Default Account Settings ───────────────────────────────────────────────
DEFAULT_ACCOUNT_SIZE = 25000
DEFAULT_RISK_PERCENT = 2.0

# ── Day Trading Config ─────────────────────────────────────────────────────
DAY_TRADE_CONFIG = {
    "timeframe":      "1min",
    "lookback_days":  5,
    "bars_to_ai":     240,
    "rsi_window":     14,
    "emas":           [9, 20],
    "smas":           [20, 50, 100, 200],
    "macd":           True,
    "vwap":           True,
    "daily_lookback": 30,
}

# ── Checker Methodology Rules ──────────────────────────────────────────────
CHECKER_RULES = """
CHECKER METHODOLOGY RULES (follow strictly):
1. Buy at SUPPORT, not at breakout — enter on pullbacks that are likely to hold
2. Short at RESISTANCE — wait for rejection confirmation, not anticipation
3. Define Risk/Reward BEFORE entry — minimum 1:1.5, prefer 1:2+
4. Time stops are mandatory — day trades must close by 4:00 PM ET
5. Reduce size when Wild Card risk is HIGH or DO_NOT_TRADE
6. Never average into a losing position
7. Wait for S/R levels to be tested and confirmed — patience over FOMO
"""
```

### settings.py full source
```python
"""
settings.py — Load/save persistent settings from data/settings.json.
"""
import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "data" / "settings.json"

DEFAULT_SETTINGS: dict = {
    "moving_averages": {
        "ma1": {"period": 20,  "type": "SMA"},
        "ma2": {"period": 50,  "type": "SMA"},
        "ma3": {"period": 200, "type": "SMA"},
    },
    "gap_detection": {
        "atr_multiplier":   1.0,
        "excluded_symbols": ["SPY", "SPX", "QQQ", "SPXW"],
    },
    "risk": {
        "account_size": 25000,
        "risk_percent": 2.0,
    },
    "_sections": ["moving_averages", "gap_detection", "risk"],
}


def load() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save(settings: dict) -> None:
    merged = DEFAULT_SETTINGS.copy()
    merged.update(settings)
    SETTINGS_PATH.parent.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2))


def get_ma_config() -> dict:
    try:
        s   = load()
        mas = s.get("moving_averages", {})
        emas, smas = [], []
        for key in sorted(k for k in mas if not k.startswith("_")):
            ma  = mas[key]
            p   = int(ma.get("period") or 0)
            typ = str(ma.get("type", "SMA")).upper()
            if p > 0:
                (emas if typ == "EMA" else smas).append(p)
        if emas or smas:
            return {"emas": emas, "smas": smas}
    except Exception:
        pass
    from config import DAY_TRADE_CONFIG
    return {"emas": DAY_TRADE_CONFIG["emas"], "smas": DAY_TRADE_CONFIG["smas"]}
```

### cache/store.py full source
```python
"""
cache/store.py
--------------
Simple in-memory cache with per-key TTL.
Thread-safe for use across the agent thread pool.
"""

import time
import threading
from typing import Any, Optional

_cache: dict = {}
_lock = threading.Lock()


def get(key: str) -> Optional[Any]:
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del _cache[key]
            return None
        return value


def set(key: str, value: Any, ttl: int) -> None:
    with _lock:
        _cache[key] = (value, time.time() + ttl)


def delete(key: str) -> None:
    with _lock:
        _cache.pop(key, None)


def clear_ticker(ticker: str) -> None:
    with _lock:
        keys = [k for k in _cache if k.startswith(f"{ticker}:")]
        for k in keys:
            del _cache[k]


def stats() -> dict:
    with _lock:
        now = time.time()
        live = sum(1 for _, (_, exp) in _cache.items() if exp > now)
        return {"total_keys": len(_cache), "live_keys": live}
```
