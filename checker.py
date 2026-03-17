"""
checker.py
----------
Checker — Stock Pick Checker Orchestrator

Coordinates the full workflow:
1. Collect market data
2. Dispatch Technical, Macro, Wild Card checker agents IN PARALLEL
3. Pass all verdicts to Supervisor
4. Return the complete trade plan
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from data.collector import collect_all
from agents.technical_agent import TechnicalAgent
from agents.macro_agent import MacroAgent
from agents.wildcard_agent import WildCardAgent
from agents.supervisor_agent import SupervisorAgent


_technical  = TechnicalAgent()
_macro      = MacroAgent()
_wildcard   = WildCardAgent()
_supervisor = SupervisorAgent()

_executor = ThreadPoolExecutor(max_workers=4)


def _run_technical(market_data: dict) -> dict:
    return _technical.analyze(market_data)

def _run_macro(market_data: dict) -> dict:
    return _macro.analyze(market_data)

def _run_wildcard(market_data: dict) -> dict:
    return _wildcard.analyze(market_data)


async def run(ticker: str) -> dict:
    """
    Full Checker workflow. Returns the complete trade plan dict.
    """
    ticker = ticker.upper().strip()

    # ── Step 1: Collect all market data ───────────────────────────────────
    market_data = await collect_all(ticker)

    # ── Step 2: Dispatch checker agents in parallel ────────────────────────
    loop = asyncio.get_event_loop()

    technical_fut = loop.run_in_executor(_executor, _run_technical, market_data)
    macro_fut     = loop.run_in_executor(_executor, _run_macro,     market_data)
    wildcard_fut  = loop.run_in_executor(_executor, _run_wildcard,  market_data)

    technical, macro, wildcard = await asyncio.gather(
        technical_fut, macro_fut, wildcard_fut
    )

    # ── Step 3: Supervisor synthesizes final plan ──────────────────────────
    trade_plan = _supervisor.synthesize(market_data, technical, macro, wildcard)

    # ── Step 4: Assemble full response ─────────────────────────────────────
    return {
        "ticker":      ticker,
        "style":       "day_trading",
        "price":       market_data["quote"].get("last"),
        "trade_plan":  trade_plan,
        "agent_verdicts": {
            "technical": technical,
            "macro":     macro,
            "wildcard":  wildcard,
        },
        "market_context": {
            "spy_change": market_data["market_ctx"].get("spy", {}).get("change_pct"),
            "qqq_change": market_data["market_ctx"].get("qqq", {}).get("change_pct"),
            "vix":        market_data["market_ctx"].get("vix", {}).get("last"),
        },
    }
