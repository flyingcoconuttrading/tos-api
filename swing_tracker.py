"""
swing_tracker.py
-----------------
Manages swing trade session boundaries and multi-day outcome logging.

Session boundaries logged:
  premarket_open  — 09:00 ET
  market_open     — 09:30 ET
  market_close    — 16:00 ET
  after_hours     — 20:00 ET

Multi-day outcomes checked: 1d, 3d, 7d, 14d, 30d
"""

from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

from data.trade_store import (
    get_open_trades, append_session_log, update_outcome_interval
)

ET = ZoneInfo("America/New_York")

# Session boundaries: (time_obj, label)
SESSION_BOUNDARIES = [
    (dtime(9, 0),  "premarket_open"),
    (dtime(9, 30), "market_open"),
    (dtime(16, 0), "market_close"),
    (dtime(20, 0), "after_hours"),
]

# Multi-day outcome intervals: (days, column_label)
SWING_INTERVALS = [
    (1,  "1d"),
    (3,  "3d"),
    (7,  "7d"),
    (14, "14d"),
    (30, "30d"),
]

# Window (minutes) within which we consider "at" a boundary
_BOUNDARY_WINDOW_MIN = 2


def _at_boundary() -> str | None:
    """Return boundary label if current ET time is within window of a boundary."""
    now = datetime.now(ET)
    t   = now.time()
    for boundary_t, label in SESSION_BOUNDARIES:
        delta = abs(
            timedelta(hours=t.hour, minutes=t.minute) -
            timedelta(hours=boundary_t.hour, minutes=boundary_t.minute)
        )
        if delta.total_seconds() <= _BOUNDARY_WINDOW_MIN * 60:
            return label
    return None


def log_session_price(get_quote_fn) -> None:
    """
    Called by background task. If we're at a session boundary,
    log current price for all open swing trades.

    get_quote_fn: callable(symbol) -> dict with 'last'/'mark' keys
    """
    boundary = _at_boundary()
    if not boundary:
        return

    from utils import get_price
    trades = [t for t in get_open_trades() if t.get("trade_type") == "swing"]
    if not trades:
        return

    # Deduplicate: don't log same boundary twice in the same day
    _seen: set[str] = set()
    for trade in trades:
        key = f"{trade['trade_id']}:{boundary}:{datetime.now(ET).date()}"
        if key in _seen:
            continue
        _seen.add(key)
        try:
            quote = get_quote_fn(trade["symbol"])
            price = get_price(quote)
            if price:
                append_session_log(trade["trade_id"], boundary, price)
        except Exception as e:
            print(f"[SwingTracker] boundary log error for {trade['symbol']}: {e}")


def check_multi_day_outcomes(get_quote_fn) -> None:
    """
    For each open swing trade, check if any day-interval milestone has
    elapsed since entry_time. If so, record the current price as the outcome.
    """
    from utils import get_price
    trades = [t for t in get_open_trades() if t.get("trade_type") == "swing"]

    for trade in trades:
        entry_time_str = trade.get("entry_time")
        if not entry_time_str:
            continue
        try:
            entry_dt = datetime.fromisoformat(entry_time_str)
        except ValueError:
            continue

        now     = datetime.now()
        elapsed = now - entry_dt

        for days, label in SWING_INTERVALS:
            col_price = f"out_{label}_price"
            # Only update if interval has elapsed and not yet recorded
            if elapsed >= timedelta(days=days) and trade.get(col_price) is None:
                try:
                    quote = get_quote_fn(trade["symbol"])
                    price = get_price(quote)
                    if price:
                        update_outcome_interval(trade["trade_id"], label, price)
                except Exception as e:
                    print(f"[SwingTracker] outcome error for {trade['symbol']} {label}: {e}")
