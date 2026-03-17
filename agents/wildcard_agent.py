"""
agents/wildcard_agent.py
-------------------------
Risk watchdog. Flags timing risks, known danger zones,
and contingencies that could blow up the trade.
"""

from datetime import datetime, timezone
from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the Wild Card Agent in a day trading AI system.
Your job: identify external risks and timing factors that could invalidate the trade.

Your output MUST be valid JSON with this exact structure:
{
  "risk_level": "LOW" | "MEDIUM" | "HIGH" | "DO_NOT_TRADE",
  "flags": ["<risk description>", ...],
  "contingencies": ["<what to watch for>", ...],
  "time_warning": true | false,
  "reasoning": "<2-3 sentence summary>"
}

Risk flags to check:
- Is it lunch hour? (12:00-13:00 ET) → liquidity drops for small caps
- Is it within 30 min of market open? (9:30-10:00 ET) → high volatility
- Is it within 30 min of market close? (15:30-16:00 ET) → forced exits
- Is VIX extremely elevated? → unpredictable moves
- Are there obvious gap risks?

Return ONLY the JSON object.
"""


class WildCardAgent(BaseAgent):
    name = "WildCardAgent"

    def analyze(self, market_data: dict) -> dict:
        now_et = datetime.now()  # Assumes server is in ET; adjust with pytz if needed
        hour   = now_et.hour
        minute = now_et.minute

        vix_last = market_data["market_ctx"].get("vix", {}).get("last", 0) or 0

        user_prompt = f"""
Current time (ET): {now_et.strftime('%H:%M')}
VIX: {vix_last}
Ticker: {market_data['ticker']}
Current Price: {market_data['quote'].get('last')}
Today Open: {market_data['quote'].get('open')}
Today High: {market_data['quote'].get('high')}
Today Low: {market_data['quote'].get('low')}
Volume so far: {market_data['quote'].get('volume')}

Assess all timing risks and external risk factors for a day trade right now.
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
