"""
agents/wildcard_agent.py
-------------------------
Risk watchdog. Identifies named risks with probability/impact ratings,
contingency plans, and timing warnings.
"""

from datetime import datetime
from agents.base_agent import BaseAgent
from config import CHECKER_RULES

SYSTEM_PROMPT = """You are the Wild Card Checker Agent in the Stock Pick Checker system.
Your job: identify ALL external risks and timing factors that could invalidate the trade.
Be specific, honest, and thorough. Name each risk individually.

""" + CHECKER_RULES + """

Your output MUST be valid JSON:
{
  "risk_level": "LOW" | "MEDIUM" | "HIGH" | "DO_NOT_TRADE",
  "wild_cards_identified": [
    {
      "type": "timing" | "external_event" | "liquidity" | "systemic" | "execution",
      "description": "<specific named risk>",
      "probability": "low" | "medium" | "high",
      "impact": "minor" | "moderate" | "severe",
      "mitigation": "<specific actionable mitigation>"
    }
  ],
  "recommended_contingencies": ["<contingency 1>", "<contingency 2>"],
  "timing_considerations": ["<timing note>"],
  "time_warning": true | false,
  "manual_checks_required": ["<check>"],
  "honest_uncertainty": "<one line — what we genuinely cannot predict>",
  "reasoning": ["• RISK: <top named risk + probability>", "• TIMING: <session timing risk>", "• CATALYST: <external event risk>", "• MITIGATION: <key contingency>", "• VERDICT: <overall risk level + rationale>"]
}

Timing risks to check:
- Within 30 min of open (9:30-10:00 ET) → high volatility
- Lunch hour (12:00-13:00 ET) → low liquidity (Checker Lunch Rule: avoid new entries)
- Within 30 min of close (15:30-16:00 ET) → forced exits, MOC imbalances
- Weekend hold risk
- Earnings proximity (within 5 days = HIGH risk)
- VIX > 25 = elevated volatility risk

reasoning: EXACTLY 3-5 bullet strings, format "• LABEL: one line", NO prose paragraphs.
Return ONLY the JSON object.
"""


class WildCardAgent(BaseAgent):
    name = "WildCardAgent"

    def analyze(self, market_data: dict) -> dict:
        now   = datetime.now()
        vix   = market_data["market_ctx"].get("vix", {}).get("last", 0) or 0
        quote = market_data["quote"]
        sr    = market_data["sr_levels"]

        user_prompt = f"""
Current time (ET): {now.strftime('%H:%M')}
Current day: {now.strftime('%A')}

Ticker: {market_data['ticker']}
Current Price: {quote.get('last')}
Today Open: {quote.get('open')}   High: {quote.get('high')}   Low: {quote.get('low')}
Volume: {quote.get('volume')}
Change: {quote.get('change_pct')}%

VIX: {vix}
SPY Change: {market_data['market_ctx'].get('spy', {}).get('change_pct')}%
QQQ Change: {market_data['market_ctx'].get('qqq', {}).get('change_pct')}%

Key S/R Levels:
  PDH: {sr.get('daily', {}).get('pdh')}
  PDL: {sr.get('daily', {}).get('pdl')}
  Weekly High: {sr.get('daily', {}).get('weekly_high')}
  Weekly Low:  {sr.get('daily', {}).get('weekly_low')}
  VWAP: {sr.get('intraday', {}).get('vwap')}
  Opening Range High: {sr.get('intraday', {}).get('opening_range_high')}
  Opening Range Low:  {sr.get('intraday', {}).get('opening_range_low')}

Economic calendar: [ENABLE_ECON_CAL=false — flag if manual check needed]

Identify ALL timing risks and external risk factors for a day trade right now.
Name each risk specifically. Provide actionable contingencies.
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
