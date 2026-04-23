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
        "now_et":       now.strftime("%H:%M ET"),
        "session":      session,
        "is_weekend":   wd >= 5,
        "near_open":    dtime(9, 30) <= t <= dtime(10, 15),
        "is_lunch":     dtime(12, 0) <= t <= dtime(13, 0),
        "near_close":   dtime(15, 30) <= t < dtime(16, 0),
        "lunch_active": dtime(12, 0) <= t <= dtime(13, 0) and session == "regular",
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
    # entry/stop not known yet (agents provide them); give preliminary sizing tiers
    tiers = {
        "full":    int(max_risk / 1),    # placeholder — agents fill real stop distance
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


# ── After-hours gap warning ─────────────────────────────────────────────────

def _compute_gap_warning(timing: dict, market_ctx: dict) -> dict:
    """
    Detects significant after-hours SPY moves using mark vs prev_close.
    Only fires outside regular session (pre_market, after_hours, weekend).
    Threshold configurable via settings.json 'gap_warning.spy_threshold_pct'.
    Returns gap_warning dict injected into preprocessor output.
    """
    import settings as _s
    threshold = _s.load().get("gap_warning", {}).get("spy_threshold_pct", 0.5)

    session = timing.get("session", "regular")
    if session == "regular":
        return {"triggered": False}

    spy = market_ctx.get("spy", {})
    mark       = spy.get("mark")
    prev_close = spy.get("prev_close")

    if not mark or not prev_close or prev_close == 0:
        return {"triggered": False}

    change_pct = round((mark - prev_close) / prev_close * 100, 2)

    if abs(change_pct) < threshold:
        return {"triggered": False, "spy_change_pct": change_pct}

    direction = "up" if change_pct > 0 else "down"
    sign      = "+" if change_pct > 0 else ""
    message   = (
        f"SPY moved {sign}{change_pct}% after hours — "
        f"wait for premarket (4AM ET) before finalizing entry"
    )

    return {
        "triggered":      True,
        "spy_change_pct": change_pct,
        "direction":      direction,
        "threshold_pct":  threshold,
        "message":        message,
    }


# ── Public entry point ──────────────────────────────────────────────────────

def run(market_data: dict) -> dict:
    """
    Returns pre-computed context dict. Call this BEFORE agent dispatch.
    Inject result as market_data['pre'] so agents can read it.
    """
    timing     = _compute_timing()
    market_ctx = market_data.get("market_ctx", {})
    return {
        "timing_flags":  timing,
        "market_regime": _compute_regime(market_ctx),
        "position_size": _compute_position(
            account_size = market_data.get("account_size", 25000),
            risk_percent = market_data.get("risk_percent", 2.0),
        ),
        "gap_warning": _compute_gap_warning(timing, market_ctx),
    }
