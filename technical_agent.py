"""
agents/technical_agent.py
--------------------------
Analyzes price action, patterns, S/R levels, and indicators.
This agent has the HIGHEST authority — it sees actual price data.
When agents conflict, Technical Agent wins.
"""

import json
from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the Technical Agent in a day trading AI system.
Your job: analyze price action and technical indicators to determine trade direction.

You will receive:
- Recent 1-minute OHLCV bars with indicators (RSI, EMA, SMA, MACD)
- Current quote snapshot

Your output MUST be valid JSON with this exact structure:
{
  "direction": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <0-100 integer>,
  "entry_zone": { "low": <price>, "high": <price> },
  "stop_loss": <price>,
  "target_1": <price>,
  "target_2": <price>,
  "key_levels": { "support": [<price>, ...], "resistance": [<price>, ...] },
  "reasoning": "<2-3 sentence summary of your analysis>"
}

Rules:
- Confidence > 50 means you have a clear directional view
- Entry zone is where you'd want to get filled (not necessarily current price)
- Stop loss must be anchored to a real S/R level, not an arbitrary dollar amount
- Targets must be realistic for a day trade (closed by 4 PM ET)
- Return ONLY the JSON object, no markdown, no explanation outside JSON
"""


class TechnicalAgent(BaseAgent):
    name = "TechnicalAgent"

    def analyze(self, market_data: dict) -> dict:
        ticker    = market_data["ticker"]
        quote     = market_data["quote"]
        bars      = market_data["latest_bars"]
        inds      = market_data["indicators"]

        user_prompt = f"""
Ticker: {ticker}
Current Price: {quote.get('last')} | Bid: {quote.get('bid')} | Ask: {quote.get('ask')}
Today: Open={quote.get('open')} High={quote.get('high')} Low={quote.get('low')}
Volume: {quote.get('volume')} | Change: {quote.get('change_pct')}%

Current Indicators:
  RSI(14): {inds['rsi']}
  EMA 9:   {inds['ema_9']}   EMA 20: {inds['ema_20']}
  SMA 20:  {inds['sma_20']}  SMA 50: {inds['sma_50']}  SMA 200: {inds['sma_200']}
  MACD:    {inds['macd']}    Signal: {inds['macd_signal']}  Hist: {inds['macd_hist']}

Recent 1-min bars (last 60):
{json.dumps(bars[-60:], default=str)}

Analyze this for a DAY TRADE. What is your directional verdict?
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
