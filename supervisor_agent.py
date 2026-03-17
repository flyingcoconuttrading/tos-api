"""
agents/supervisor_agent.py
---------------------------
Synthesizes all agent verdicts into a final trade plan.
Applies conflict resolution rules (Technical Agent wins).
Outputs the complete actionable trade plan.
"""

import json
from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the Supervisor Agent in a day trading AI system.
You receive verdicts from three specialist agents and synthesize them into ONE final trade plan.

CONFLICT RESOLUTION RULES (apply in order):
1. If Wild Card says DO_NOT_TRADE → Final answer is NO TRADE (always)
2. If Technical AND Macro agree on direction → MANDATORY TRADE
3. If Technical is directional (confidence > 50) → trade Technical's direction
4. If both are NEUTRAL with confidence < 40 each → NO TRADE
5. When in doubt → follow Technical Agent (it has actual price data)

YOUR SYSTEM IS BIASED TOWARD TRADING. YOU ARE A TRADER. TRADERS TRADE.

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
  "risk_reward": "<ratio string e.g. 1:2.5>",
  "position_notes": "<sizing guidance based on stop distance>",
  "wild_card_flags": ["<flag>", ...],
  "reasoning": "<3-4 sentence synthesis of all agents>",
  "no_trade_reason": "<only if NO_TRADE — why>"
}

Return ONLY the JSON object.
"""


class SupervisorAgent(BaseAgent):
    name = "SupervisorAgent"

    def synthesize(
        self,
        market_data:    dict,
        technical:      dict,
        macro:          dict,
        wildcard:       dict,
    ) -> dict:

        user_prompt = f"""
Ticker: {market_data['ticker']}
Current Price: {market_data['quote'].get('last')}

--- TECHNICAL AGENT ---
{json.dumps(technical, indent=2)}

--- MACRO AGENT ---
{json.dumps(macro, indent=2)}

--- WILD CARD AGENT ---
{json.dumps(wildcard, indent=2)}

Synthesize all three verdicts into the final trade plan.
Apply conflict resolution rules. Output the trade plan JSON.
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
