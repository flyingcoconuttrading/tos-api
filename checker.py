"""
checker.py — Stock Pick Checker Orchestrator
Coordinates data collection + parallel agent dispatch + logging.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from data.collector import collect_all
import preprocessor
from agents.technical_agent import TechnicalAgent
from agents.macro_agent import MacroAgent
from agents.wildcard_agent import WildCardAgent
from agents.supervisor_agent import SupervisorAgent
from db.database import log_trade

_technical  = TechnicalAgent()
_macro      = MacroAgent()
_wildcard   = WildCardAgent()
_supervisor = SupervisorAgent()
_executor   = ThreadPoolExecutor(max_workers=4)


async def run(ticker: str, account_size: float = 25000, risk_percent: float = 2.0, trade_type: str = "day") -> dict:
    ticker = ticker.upper().strip()

    # ── Step 1: Collect market data (dual timeframe + cache) ───────────────
    market_data = await collect_all(ticker, account_size, risk_percent)

    # ── Step 1b: Pre-processor (Python, no API cost) ───────────────────────
    market_data["pre"] = preprocessor.run(market_data)
    market_data["trade_type"] = trade_type  # "day" or "swing"

    # ── Step 2: Dispatch checker agents in parallel ────────────────────────
    loop = asyncio.get_event_loop()
    technical, macro, wildcard = await asyncio.gather(
        loop.run_in_executor(_executor, _technical.analyze,  market_data),
        loop.run_in_executor(_executor, _macro.analyze,      market_data),
        loop.run_in_executor(_executor, _wildcard.analyze,   market_data),
    )

    # ── Step 3: Supervisor synthesizes final plan ──────────────────────────
    trade_plan = _supervisor.synthesize(market_data, technical, macro, wildcard)

    # ── Step 4: Assemble response ──────────────────────────────────────────
    pre = market_data["pre"]
    response = {
        "ticker":       ticker,
        "style":        trade_type,
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
