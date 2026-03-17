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
