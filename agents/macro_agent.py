"""
agents/macro_agent.py
----------------------
Analyzes broader market conditions: SPY/QQQ trend, VIX regime,
and whether macro context supports or opposes the trade.
"""

from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the Macro Agent in a day trading AI system.
Your job: assess whether broader market conditions favor a trade in this ticker.

You will receive SPY, QQQ, and VIX snapshots.

Your output MUST be valid JSON with this exact structure:
{
  "direction": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <0-100 integer>,
  "market_regime": "TRENDING_UP" | "TRENDING_DOWN" | "CHOPPY" | "HIGH_VOLATILITY",
  "vix_assessment": "LOW" | "NORMAL" | "ELEVATED" | "EXTREME",
  "macro_supports_trade": true | false,
  "reasoning": "<2-3 sentence summary>"
}

Rules:
- VIX < 15 = LOW, 15-20 = NORMAL, 20-30 = ELEVATED, >30 = EXTREME
- If SPY and QQQ disagree in direction, lean CHOPPY
- Return ONLY the JSON object
"""


class MacroAgent(BaseAgent):
    name = "MacroAgent"

    def analyze(self, market_data: dict) -> dict:
        ctx   = market_data["market_ctx"]
        spy   = ctx.get("spy", {})
        qqq   = ctx.get("qqq", {})
        vix   = ctx.get("vix", {})

        user_prompt = f"""
Market Context:
SPY: Last={spy.get('last')}  Change={spy.get('change_pct')}%  Volume={spy.get('volume')}
QQQ: Last={qqq.get('last')}  Change={qqq.get('change_pct')}%  Volume={qqq.get('volume')}
VIX: Last={vix.get('last')}  Change={vix.get('change_pct')}%

Ticker being analyzed: {market_data['ticker']}
Current price: {market_data['quote'].get('last')}

Based on current market conditions, what is the macro environment?
Does it support going LONG, SHORT, or is the market too choppy (NEUTRAL)?
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
