"""
plan_validator.py — Zero-AI plan validity rule engine.

Six rules checked in order:
  1. time_stop_expired     — past time stop
  2. stop_hit_before_entry — price through stop before any fill
  3. entry_zone_blown_past — price ran through zone without filling
  4. direction_flipped     — price moved well beyond stop (trend reversal)
  5. vwap_break            — day/scalp LONG below VWAP (configurable threshold)
  6. sr_level_broken       — key support/resistance breached

Returns first rule that fires, or None (plan still valid).
Also handles WAITING promotion logic.
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import settings as _settings
from utils import is_market_hours

logger = logging.getLogger("tos_api.plan_validator")

_ET = ZoneInfo("America/New_York")

# Default thresholds — configurable via settings.json "plan_validity" block
_DEFAULT_CFG = {
    "vwap_break_threshold_pct":   0.30,   # 0.30% below VWAP triggers
    "sr_break_threshold_pct":     0.20,   # 0.20% below support triggers
    "direction_flip_atr_multiple": 2.0,   # price > stop + 2×ATR = flip
    "entry_blown_pct":            0.50,   # entry_high + 0.5× zone width = blown
}


def _cfg() -> dict:
    return _settings.load().get("plan_validity", _DEFAULT_CFG)


def _time_stop_expired(plan: dict) -> bool:
    ts = plan.get("time_stop")
    if not ts:
        return False
    try:
        now_et = datetime.now(_ET)
        ts_str = str(ts).strip()
        # Day/scalp: "Market close 4:00 PM ET"
        if "market close" in ts_str.lower() or "4:00 pm" in ts_str.lower():
            close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
            return now_et >= close
        # Swing: ISO date string "2026-05-15"
        ts_date = datetime.fromisoformat(ts_str.split("T")[0]).date()
        return now_et.date() > ts_date
    except Exception as e:
        logger.debug("time_stop parse failed: %s", e)
        return False


def _stop_hit_before_entry(plan: dict, price: float) -> bool:
    direction = str(plan.get("direction", "")).upper()
    stop      = plan.get("stop_loss")
    if not stop:
        return False
    if direction == "LONG":
        return price <= stop
    if direction == "SHORT":
        return price >= stop
    return False


def _entry_zone_blown_past(plan: dict, price: float) -> bool:
    """
    Price moved through the entry zone without filling.
    LONG: price ran above entry_high + 0.5 × zone_width
    SHORT: price dropped below entry_low - 0.5 × zone_width
    """
    direction  = str(plan.get("direction", "")).upper()
    entry_low  = plan.get("entry_low")
    entry_high = plan.get("entry_high")
    if not entry_low or not entry_high:
        return False
    zone_width = abs(entry_high - entry_low)
    buffer     = zone_width * _cfg().get("entry_blown_pct", 0.50)
    if direction == "LONG":
        return price > entry_high + buffer
    if direction == "SHORT":
        return price < entry_low - buffer
    return False


def _direction_flipped(plan: dict, price: float) -> bool:
    """
    Price moved well past the stop — trend reversal confirmed.
    Uses a simple % proxy (2% beyond stop) since no live ATR here.
    """
    direction = str(plan.get("direction", "")).upper()
    stop      = plan.get("stop_loss")
    if not stop or stop == 0:
        return False
    flip_pct = 0.02   # 2% beyond stop = reversal
    if direction == "LONG":
        return price <= stop * (1 - flip_pct)
    if direction == "SHORT":
        return price >= stop * (1 + flip_pct)
    return False


def _vwap_break(plan: dict, price: float) -> bool:
    """
    Day/scalp LONG only. If price is > threshold % below VWAP at creation,
    setup support gone. Not applied to swing trades or SHORT plans.
    """
    trade_type = plan.get("trade_type", "")
    direction  = str(plan.get("direction", "")).upper()
    if trade_type in ("swing_short", "swing_medium", "swing_long"):
        return False
    if direction != "LONG":
        return False
    vwap = plan.get("vwap_at_creation")
    if not vwap or vwap <= 0:
        return False
    threshold_pct = _cfg().get("vwap_break_threshold_pct", 0.30)
    drop_pct = (vwap - price) / vwap * 100
    return drop_pct > threshold_pct


def _sr_level_broken(plan: dict, price: float) -> bool:
    """
    LONG: nearest support broken to the downside.
    SHORT: nearest resistance broken to the upside.
    """
    direction = str(plan.get("direction", "")).upper()
    threshold = _cfg().get("sr_break_threshold_pct", 0.20) / 100.0
    if direction == "LONG":
        support = plan.get("nearest_support")
        if not support or support <= 0:
            return False
        return price < support * (1 - threshold)
    if direction == "SHORT":
        resistance = plan.get("nearest_resistance")
        if not resistance or resistance <= 0:
            return False
        return price > resistance * (1 + threshold)
    return False


def _entry_zone_touched(plan: dict, price: float) -> bool:
    """Price reached entry zone — simulate fill."""
    direction  = str(plan.get("direction", "")).upper()
    entry_low  = plan.get("entry_low")
    entry_high = plan.get("entry_high")
    if not entry_low or not entry_high:
        return False
    if direction == "LONG":
        return entry_low <= price <= entry_high
    if direction == "SHORT":
        return entry_low <= price <= entry_high
    return False


def validate_plan(plan: dict, current_price: float) -> tuple[str | None, str | None]:
    """
    Run all 6 rules against a PENDING plan.
    Returns (new_status, reason) or (None, None) if still valid.

    Priority order: time_stop > stop_hit > entry_blown > flip > vwap > sr
    TRIGGERED fires if entry zone touched before any invalidation.
    """
    if _time_stop_expired(plan):
        return ("EXPIRED", "time_stop_expired")

    if _stop_hit_before_entry(plan, current_price):
        return ("INVALIDATED", "stop_hit_before_entry")

    if _entry_zone_touched(plan, current_price):
        return ("TRIGGERED", "entry_zone_touched")

    if _entry_zone_blown_past(plan, current_price):
        return ("INVALIDATED", "entry_zone_blown_past")

    if _direction_flipped(plan, current_price):
        return ("INVALIDATED", "direction_flipped")

    if _vwap_break(plan, current_price):
        return ("INVALIDATED", "vwap_break")

    if _sr_level_broken(plan, current_price):
        return ("INVALIDATED", "sr_level_broken")

    return (None, None)


def evaluate_waiting_plan(plan: dict, current_price: float) -> tuple[str | None, str | None]:
    """
    Re-evaluate a WAITING plan.
    WAITING = TRADE_WAIT verdict, waiting for lunch to pass / volume to recover.
    If wait condition cleared (13:00 ET):
        - Entry zone still valid → promote to PENDING
        - Entry zone blown        → ABANDONED
    If time stop expired → EXPIRED.
    Returns (new_status, reason) or (None, None) if still waiting.
    """
    if _time_stop_expired(plan):
        return ("EXPIRED", "time_stop_expired")

    now_et = datetime.now(_ET)
    # Lunch gate: wait until 13:00 ET
    lunch_end = now_et.replace(hour=13, minute=0, second=0, microsecond=0)
    if now_et < lunch_end:
        return (None, None)   # still waiting

    # Lunch ended — assess entry zone
    if _entry_zone_blown_past(plan, current_price):
        return ("ABANDONED", "entry_zone_blown_past_during_wait")

    if _stop_hit_before_entry(plan, current_price):
        return ("ABANDONED", "stop_hit_during_wait")

    return ("PENDING", "wait_condition_cleared")
