"""
checker.py — Stock Pick Checker Orchestrator
Coordinates data collection + parallel agent dispatch + logging.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from data.collector import collect_all
import preprocessor
import settings as _settings_mod
from agents.technical_agent import TechnicalAgent
from agents.macro_agent import MacroAgent
from agents.wildcard_agent import WildCardAgent
from agents.supervisor_agent import SupervisorAgent
from db.database import log_trade
from datetime import datetime
from zoneinfo import ZoneInfo
_ET = ZoneInfo("America/New_York")

_technical  = TechnicalAgent()
_macro      = MacroAgent()
_wildcard   = WildCardAgent()
_supervisor = SupervisorAgent()
_executor   = ThreadPoolExecutor(max_workers=4)


def _volume_pace_ratio(quote: dict) -> float:
    """
    Compare current volume vs expected volume at this time of day.
    Returns ratio: >1.0 = above pace, <1.0 = below pace.
    Uses a simple linear model: expected = avg_daily_volume * (elapsed_minutes / 390)
    avg_daily_volume approximated from quote if available, else returns 1.0 (neutral).
    """
    try:
        current_vol = float(quote.get("volume") or 0)
        if current_vol == 0:
            return 1.0
        now_et = datetime.now(_ET)
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        elapsed_min = max((now_et - market_open).total_seconds() / 60, 1)
        # Use prev_close volume as proxy for avg daily volume if not available
        # Simple heuristic: if current pace extrapolates to > 80% of a normal day = active
        pace_pct = elapsed_min / 390.0  # fraction of trading day elapsed
        if pace_pct <= 0:
            return 1.0
        projected_full_day = current_vol / pace_pct
        # Without historical avg, use 50M shares as SPY baseline
        # For other tickers this is approximate — good enough for lunch gate
        avg_estimate = float(quote.get("avg_volume") or 50_000_000)
        return round(projected_full_day / avg_estimate, 2)
    except Exception:
        return 1.0


def _apply_trade_wait(trade_plan: dict, market_data: dict) -> dict:
    """
    Post-supervisor Python gate.
    If verdict is TRADE and lunch is active:
      - Check volume pace ratio
      - If volume pace < 0.8 (below average) → downgrade to TRADE_WAIT
      - If volume pace >= 0.8 (on pace or above) → keep as TRADE
    TRADE_WAIT = valid setup, wait for lunch to pass.
    Swing trades are exempt — lunch rule is intraday only.
    """
    if trade_plan.get("verdict") != "TRADE":
        return trade_plan

    is_swing = market_data.get("is_swing", False)
    if is_swing:
        return trade_plan

    timing = market_data.get("pre", {}).get("timing_flags", {})
    if not timing.get("lunch_active", False):
        return trade_plan

    # Lunch is active — check volume pace
    quote     = market_data.get("quote", {})
    vol_ratio = _volume_pace_ratio(quote)

    if vol_ratio < 0.8:
        trade_plan["verdict"]        = "TRADE_WAIT"
        trade_plan["wait_reason"]    = (
            f"Valid setup — volume below pace ({vol_ratio:.1f}x) during lunch. "
            f"Wait until 13:00 ET for liquidity to return."
        )
        trade_plan["vol_pace_ratio"] = vol_ratio
    else:
        # Volume is on pace — lunch has less impact, allow TRADE but add note
        trade_plan["vol_pace_ratio"] = vol_ratio
        existing = trade_plan.get("reasoning", [])
        trade_plan["reasoning"] = existing + [
            f"• TIMING: Lunch hour but volume on pace ({vol_ratio:.1f}x avg) — reduced liquidity risk"
        ]

    return trade_plan


async def run(ticker: str, account_size: float = 25000, risk_percent: float = 2.0, trade_type: str = "day") -> dict:
    import time as _time
    ticker     = ticker.upper().strip()
    _run_start = _time.time()

    # ── Step 1: Collect market data (dual timeframe + cache) ───────────────
    market_data = await collect_all(ticker, account_size, risk_percent, trade_type)

    # ── Step 1b: Pre-processor (Python, no API cost) ───────────────────────
    market_data["pre"]        = preprocessor.run(market_data)
    market_data["trade_type"] = trade_type  # "day" or "swing"

    # ── Step 1c: Tomorrow's setup mode when market is closed ───────────────
    _session  = market_data["pre"]["timing_flags"]["session"]
    _is_swing = market_data.get("is_swing", False)
    # Swing trades always analyze for next session regardless of time
    # Day/scalp: outside market hours → tomorrow's setup mode
    market_data["tomorrow_setup"] = (
        _session in ("after_hours", "weekend", "pre_market") and not _is_swing
    )
    market_data["gap_detection"]  = _settings_mod.load().get("gap_detection", {
        "atr_multiplier":   1.0,
        "excluded_symbols": ["SPY", "SPX", "QQQ", "SPXW"],
    })

    # ── Step 2: Dispatch checker agents in parallel ────────────────────────
    loop = asyncio.get_event_loop()
    technical, macro, wildcard = await asyncio.gather(
        loop.run_in_executor(_executor, _technical.analyze,  market_data),
        loop.run_in_executor(_executor, _macro.analyze,      market_data),
        loop.run_in_executor(_executor, _wildcard.analyze,   market_data),
    )

    # ── Step 3: Supervisor synthesizes final plan ──────────────────────────
    trade_plan = _supervisor.synthesize(market_data, technical, macro, wildcard)

    # ── Step 3b: Post-supervisor Python gates ─────────────────────────────
    trade_plan = _apply_trade_wait(trade_plan, market_data)

    # ── Step 4: Assemble response ──────────────────────────────────────────
    pre         = market_data["pre"]
    _runtime_ms = round((_time.time() - _run_start) * 1000)
    response = {
        "ticker":       ticker,
        "style":        trade_type,
        "runtime_ms":   _runtime_ms,
        "price":        market_data["quote"].get("last"),
        "account_size": account_size,
        "risk_percent": risk_percent,
        "trade_plan":   trade_plan,
        "agent_verdicts": {
            "technical": technical,
            "macro":     macro,
            "wildcard":  wildcard,
        },
        "sr_levels":    market_data["sr_levels"],
        "market_context": {
            "spy_price":  market_data["market_ctx"].get("spy", {}).get("last"),
            "spy_change": market_data["market_ctx"].get("spy", {}).get("change_pct"),
            "qqq_price":  market_data["market_ctx"].get("qqq", {}).get("last"),
            "qqq_change": market_data["market_ctx"].get("qqq", {}).get("change_pct"),
            "vix":        market_data["market_ctx"].get("vix", {}).get("last"),
        },
        "pre": {
            "timing":  pre["timing_flags"],
            "regime":  pre["market_regime"],
            "sizing":  pre["position_size"],
        },
    }

    # ── Step 5: Log to PostgreSQL ──────────────────────────────────────────
    try:
        log_id = log_trade(
            {"ticker": ticker, "account_size": account_size, "risk_percent": risk_percent},
            response,
        )
        response["log_id"] = log_id
    except Exception as e:
        response["log_id"] = None
        response["log_error"] = str(e)

    return response
