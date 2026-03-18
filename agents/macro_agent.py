"""
agents/macro_agent.py
----------------------
Analyzes broader market conditions: SPY/QQQ/VIX,
market regime, and whether macro supports or opposes the trade.
"""

from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the Macro Checker Agent in the Stock Pick Checker system.
Your job: assess whether broader market conditions favor a trade in this ticker.

Your output MUST be valid JSON:
{
  "direction": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <0-100>,
  "market_regime": "TRENDING_UP" | "TRENDING_DOWN" | "CHOPPY" | "HIGH_VOLATILITY" | "RISK_ON" | "RISK_OFF",
  "spy_direction": "up" | "down" | "flat",
  "qqq_direction": "up" | "down" | "flat",
  "cross_asset_alignment": "aligned" | "mixed" | "divergent",
  "vix_assessment": "LOW" | "NORMAL" | "ELEVATED" | "EXTREME",
  "macro_supports_trade": true | false,
  "session_context": {
    "type": "pre_market" | "regular" | "after_hours",
    "risk_note": "<one line timing risk, no prose>"
  },
  "news_sentiment": {
    "overall": "bullish" | "bearish" | "neutral",
    "key_themes": ["<theme>", ...]
  },
  "reasoning": ["• REGIME: <regime + why>", "• SPY/QQQ: <cross-asset alignment>", "• VIX: <volatility level implication>", "• SESSION: <session timing risk>", "• VERDICT: <supports or opposes trade + why>"]
}

Rules:
- VIX < 15 = LOW, 15-20 = NORMAL, 20-30 = ELEVATED, >30 = EXTREME
- If SPY and QQQ disagree → CHOPPY regime
- SPY change > +0.5% = up, < -0.5% = down, otherwise flat
- reasoning: EXACTLY 3-5 bullet strings, format "• LABEL: one line", NO prose paragraphs
- Return ONLY the JSON object
"""


class MacroAgent(BaseAgent):
    name = "MacroAgent"

    def analyze(self, market_data: dict) -> dict:
        ctx    = market_data["market_ctx"]
        spy    = ctx.get("spy", {})
        qqq    = ctx.get("qqq", {})
        vix    = ctx.get("vix", {})
        ticker = market_data["ticker"]
        quote  = market_data["quote"]
        pre    = market_data.get("pre", {})
        regime = pre.get("market_regime", {})
        timing = pre.get("timing_flags",  {})

        tomorrow = market_data.get("tomorrow_setup", False)

        user_prompt = f"""
Ticker: {ticker}  Price: {quote.get('last')}
Regime: {regime.get('regime', 'UNKNOWN')} | SPY {regime.get('spy_trend')} ({regime.get('spy_change_pct')}%) | QQQ {regime.get('qqq_trend')} ({regime.get('qqq_change_pct')}%) | VIX {regime.get('vix')} ({regime.get('vix_level')})
SPY: {spy.get('last')} H={spy.get('high')} L={spy.get('low')} Vol={spy.get('volume')}
QQQ: {qqq.get('last')} H={qqq.get('high')} L={qqq.get('low')} Vol={qqq.get('volume')}
News: [ENABLE_NEWS=false] Economic calendar: [ENABLE_ECON_CAL=false — check FOMC/CPI/NFP/earnings manually]
"""
        if tomorrow:
            user_prompt += "\nMARKET CLOSED — assess macro conditions for tomorrow's open. Skip session timing warnings (max 1 line). Focus on whether macro supports or opposes a trade at tomorrow's open."
        else:
            user_prompt += f"\nSession: {timing.get('session')} {timing.get('now_et')} near_open={timing.get('near_open')} lunch={timing.get('is_lunch')} near_close={timing.get('near_close')}\nAssess nuance: session timing, breadth/volume confirmation, does macro SUPPORT or OPPOSE {ticker}?"

        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
