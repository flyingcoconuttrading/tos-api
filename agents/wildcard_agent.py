"""
agents/wildcard_agent.py
-------------------------
Risk watchdog. Identifies named risks with probability/impact ratings,
contingency plans, and timing warnings.
"""

from datetime import datetime
from agents.base_agent import BaseAgent
from data.collector import _get_earnings_date

SYSTEM_PROMPT = """You are the Wild Card Checker Agent in the Stock Pick Checker system.
Your job: identify ALL external risks and timing factors that could invalidate the trade.
Be specific, honest, and thorough. Name each risk individually.

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

Timing risks to check (DAY/SCALP only — skip intraday checks for swing):
- Within 30 min of open (9:30-10:00 ET) → high volatility
- Lunch hour (12:00-13:00 ET) → low liquidity (Checker Lunch Rule: avoid new entries)
- Within 30 min of close (15:30-16:00 ET) → forced exits, MOC imbalances
- Weekend hold risk (all trade types)
- Earnings proximity: within 5 days = HIGH for day, within 2 weeks = HIGH for swing
- VIX > 25 = elevated volatility risk (all trade types)
- For SWING trades only: gap risk vs key S/R, sector rotation, macro events over hold period

reasoning: EXACTLY 3-5 bullet strings, format "• LABEL: one line", NO prose paragraphs.
Return ONLY the JSON object.
"""


class WildCardAgent(BaseAgent):
    name = "WildCardAgent"

    def analyze(self, market_data: dict) -> dict:
        now        = datetime.now()
        vix        = market_data["market_ctx"].get("vix", {}).get("last", 0) or 0
        quote      = market_data["quote"]
        sr         = market_data["sr_levels"]
        tomorrow   = market_data.get("tomorrow_setup", False)
        is_swing   = market_data.get("is_swing", False)
        trade_type = market_data.get("trade_type", "day")
        ticker     = market_data["ticker"]

        # Earnings proximity — days until next earnings
        try:
            earnings     = _get_earnings_date(ticker)
            days_until   = earnings.get("days_until")
            earnings_str = earnings.get("next_earnings_date")
            if days_until is not None:
                earnings_line = f"Earnings: {days_until} days ({earnings_str})"
            else:
                earnings_line = "Earnings: unknown (check manually)"
        except Exception:
            earnings_line = "Earnings: unknown (check manually)"

        # Gap warning from preprocessor
        gap_warning   = market_data.get("pre", {}).get("gap_warning", {})
        gap_line      = ""
        if gap_warning.get("triggered"):
            gap_line  = f"\n⚠ AFTER-HOURS GAP: {gap_warning.get('message', '')}"

        user_prompt = f"""
Time: {now.strftime('%A %H:%M')} ET
Ticker: {ticker}  Price: {quote.get('last')}  Chg: {quote.get('change_pct')}%
VIX: {vix}  SPY Chg: {market_data['market_ctx'].get('spy', {}).get('change_pct')}%  QQQ Chg: {market_data['market_ctx'].get('qqq', {}).get('change_pct')}%
PDH: {sr.get('daily', {}).get('pdh')}  PDL: {sr.get('daily', {}).get('pdl')}  Wkly H: {sr.get('daily', {}).get('weekly_high')}  Wkly L: {sr.get('daily', {}).get('weekly_low')}
{earnings_line}{gap_line}
Economic calendar: [ENABLE_ECON_CAL=false — flag if manual check needed]
"""
        if is_swing:
            user_prompt += f"""
Trade Type: {trade_type}
SWING TRADE — identify multi-week risks only.
Do NOT flag intraday timing risks (lunch, near-open, near-close, MOC imbalances).
Do NOT flag missing VWAP data.
Focus on: earnings proximity (within 2 weeks = HIGH), gap risk, macro events,
sector rotation risk, overnight/weekend holds, extended territory vs key S/R levels.
"""
        elif tomorrow:
            user_prompt += "\nMARKET CLOSED — identify risks for tomorrow's open only. Skip intraday timing warnings (lunch, near-open, near-close). Focus on overnight/gap risk, earnings proximity, macro events."
        else:
            # Day/scalp: include intraday data
            user_prompt += f"""
Open: {quote.get('open')}  H: {quote.get('high')}  L: {quote.get('low')}  Vol: {quote.get('volume')}
VWAP: {sr.get('intraday', {}).get('vwap')}  ORH: {sr.get('intraday', {}).get('opening_range_high')}  ORL: {sr.get('intraday', {}).get('opening_range_low')}
Identify ALL timing risks and external risk factors for a day trade right now. Name each risk specifically. Provide actionable contingencies.
"""

        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
