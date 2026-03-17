"""
agents/supervisor_agent.py
---------------------------
Synthesizes all checker agent verdicts into a final trade plan.
Applies conflict resolution rules, position sizing, and Checker methodology.
"""

import json
from agents.base_agent import BaseAgent
from config import CHECKER_RULES

SYSTEM_PROMPT = """You are the Supervisor Checker Agent in the Stock Pick Checker system.
You receive verdicts from three specialist agents and synthesize them into ONE final trade plan.

""" + CHECKER_RULES + """

CONFLICT RESOLUTION RULES (apply in order):
1. If Wild Card says DO_NOT_TRADE → Final is NO TRADE (always, no exceptions)
2. If Technical AND Macro agree on direction → MANDATORY TRADE
3. If Technical is directional (confidence > 50) → trade Technical's direction
4. If both are NEUTRAL with confidence < 40 each → NO TRADE
5. When agents conflict → follow Technical Agent (it has actual price data)

THE CHECKER IS BIASED TOWARD TRADING. TRADERS TRADE. But only at the RIGHT levels.

POSITION SIZING RULES:
- Max risk per trade = account_size × (risk_percent / 100)
- Stop distance = abs(entry_price - stop_loss)
- Shares = max_risk / stop_distance
- Size recommendation: full (100%), half (50%), quarter (25%) based on conviction + wild card risk

Your output MUST be valid JSON:
{
  "verdict": "TRADE" | "NO_TRADE",
  "direction": "LONG" | "SHORT" | null,
  "confidence": <0-100>,
  "entry_zone": { "low": <price>, "high": <price> } | null,
  "stop_loss": <price> | null,
  "target_1": { "price": <price>, "exit_pct": 50 } | null,
  "target_2": { "price": <price>, "exit_pct": 50 } | null,
  "time_stop": "Market close 4:00 PM ET",
  "risk_reward": "<e.g. 1:2.5>",
  "position_sizing": {
    "size_recommendation": "full" | "half" | "quarter",
    "rationale": "<why this size>",
    "max_risk_dollars": <number>,
    "stop_distance": <number>,
    "suggested_shares": <number>
  },
  "options_stub": {
    "enabled": false,
    "note": "Options contract selection disabled — enable ENABLE_OPTIONS flag"
  },
  "wild_card_flags": ["<flag>", ...],
  "manual_checks_required": ["<check>", ...],
  "agent_agreement": "full" | "partial" | "conflict",
  "reasoning": ["• VERDICT: <final direction + confidence>", "• ENTRY: <entry zone + rationale>", "• SIZE: <size recommendation + why>", "• RISK: <key risk from wild card or macro>", "• NOTE: <any manual check or caveat>"],
  "no_trade_reason": "<only if NO_TRADE — one line>",
  "agent": "SupervisorAgent"
}

reasoning: EXACTLY 3-5 bullet strings, format "• LABEL: one line", NO prose paragraphs.
Return ONLY the JSON object.
"""


class SupervisorAgent(BaseAgent):
    name = "SupervisorAgent"

    def synthesize(self, market_data: dict, technical: dict, macro: dict, wildcard: dict) -> dict:
        account_size  = market_data.get("account_size", 25000)
        risk_percent  = market_data.get("risk_percent", 2.0)
        pre           = market_data.get("pre", {})
        sizing        = pre.get("position_size", {})
        timing        = pre.get("timing_flags",  {})
        regime        = pre.get("market_regime", {})
        max_risk      = sizing.get("max_risk_dollars") or round(account_size * risk_percent / 100, 2)

        user_prompt = f"""
Ticker: {market_data['ticker']}
Current Price: {market_data['quote'].get('last')}
Account Size: ${account_size:,.0f}
Risk Per Trade: {risk_percent}% = ${max_risk:,.2f} max loss

Pre-computed Context:
  Regime:    {regime.get('regime', 'UNKNOWN')}  VIX={regime.get('vix')} ({regime.get('vix_level')})
  Session:   {timing.get('session')} | {timing.get('now_et')}
  near_open={timing.get('near_open')}  is_lunch={timing.get('is_lunch')}  near_close={timing.get('near_close')}

--- TECHNICAL CHECKER AGENT ---
{json.dumps(technical, indent=2)}

--- MACRO CHECKER AGENT ---
{json.dumps(macro, indent=2)}

--- WILD CARD CHECKER AGENT ---
{json.dumps(wildcard, indent=2)}

Synthesize all three verdicts into the final trade plan.
Apply conflict resolution rules and Checker methodology.
Calculate position sizing using the account/risk values provided.
Output the complete trade plan JSON.
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
