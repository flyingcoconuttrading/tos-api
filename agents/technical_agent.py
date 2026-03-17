"""
agents/technical_agent.py
--------------------------
Analyzes price action, S/R levels (intraday + daily), VWAP,
chart patterns, MTF alignment, and indicators.
Technical Agent has highest authority — it sees actual price data.
"""

import json
from agents.base_agent import BaseAgent
from config import CHECKER_RULES

SYSTEM_PROMPT = """You are the Technical Checker Agent in the Stock Pick Checker system.
Your job: analyze price action, support/resistance levels, and technical indicators.

""" + CHECKER_RULES + """

You will receive:
- Real-time quote
- 1-minute intraday OHLCV bars with indicators (RSI, EMA, SMA, MACD, VWAP)
- Daily bars (last 10 days)
- Pre-calculated S/R levels: PDH, PDL, PDC, weekly H/L, monthly H/L, opening range, VWAP

Your output MUST be valid JSON:
{
  "direction": "LONG" | "SHORT" | "NEUTRAL",
  "confidence": <0-100>,
  "entry_type": "support_bounce" | "resistance_rejection" | "breakout" | "breakdown" | "neutral",
  "support_levels": {
    "minor": [<price>, ...],
    "major": [<price>, ...],
    "key_references": {
      "pdc": <price>,
      "pdl": <price>,
      "opening_range_low": <price>,
      "weekly_low": <price>,
      "vwap": <price>
    }
  },
  "resistance_levels": {
    "minor": [<price>, ...],
    "major": [<price>, ...],
    "key_references": {
      "pdh": <price>,
      "opening_range_high": <price>,
      "weekly_high": <price>,
      "monthly_high": <price>
    }
  },
  "chart_patterns": ["<pattern>", ...],
  "mtf_alignment": "aligned" | "mixed" | "conflicting",
  "volatility": "low" | "normal" | "elevated" | "extreme",
  "vwap_position": "above" | "below" | "testing",
  "entry_zone": { "low": <price>, "high": <price> },
  "stop_loss": <price>,
  "target_1": <price>,
  "target_2": <price>,
  "reasoning": ["<factor 1>", "<factor 2>", "<factor 3>"]
}

Rules:
- Use PDH/PDL/VWAP as key intraday levels
- Use weekly/monthly highs/lows for major S/R
- Entry must be AT support/resistance, not chasing
- Stop must anchor to a real S/R level
- Reasoning must cite specific prices and indicators
- Return ONLY the JSON object
"""


class TechnicalAgent(BaseAgent):
    name = "TechnicalAgent"

    def analyze(self, market_data: dict) -> dict:
        ticker = market_data["ticker"]
        quote  = market_data["quote"]
        bars   = market_data["latest_bars"]
        inds   = market_data["indicators"]
        sr     = market_data["sr_levels"]
        daily  = market_data["daily_bars"]
        pre    = market_data.get("pre", {})
        timing = pre.get("timing_flags", {})

        user_prompt = f"""
Ticker: {ticker}
Current Price: {quote.get('last')} | Bid: {quote.get('bid')} | Ask: {quote.get('ask')}
Today: Open={quote.get('open')} High={quote.get('high')} Low={quote.get('low')}
Volume: {quote.get('volume')} | Change: {quote.get('change_pct')}%

Session: {timing.get('session')} | {timing.get('now_et')} | near_open={timing.get('near_open')} is_lunch={timing.get('is_lunch')} near_close={timing.get('near_close')}

Current Indicators:
  RSI(14):  {inds['rsi']}
  VWAP:     {inds.get('vwap', 'N/A')}
  EMA 9:    {inds['ema_9']}    EMA 20: {inds['ema_20']}
  SMA 20:   {inds['sma_20']}   SMA 50: {inds['sma_50']}   SMA 200: {inds['sma_200']}
  MACD:     {inds['macd']}     Signal: {inds['macd_signal']}  Hist: {inds['macd_hist']}

Key S/R Levels:
  Intraday: {json.dumps(sr.get('intraday', {}), default=str)}
  Daily:    {json.dumps(sr.get('daily', {}), default=str)}

Daily Bars (last 10 days):
{json.dumps(daily, default=str)}

Recent 1-min bars (last 60):
{json.dumps(bars[-60:], default=str)}

Analyze for a DAY TRADE using Checker Methodology.
Identify all S/R levels (minor and major), chart patterns, MTF alignment, and give your directional verdict.
"""
        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
