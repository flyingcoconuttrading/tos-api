"""
agents/technical_agent.py
--------------------------
Analyzes price action, S/R levels (intraday + daily), VWAP,
chart patterns, MTF alignment, and indicators.
Technical Agent has highest authority — it sees actual price data.
"""

import json
from agents.base_agent import BaseAgent

SYSTEM_PROMPT = """You are the Technical Checker Agent in the Stock Pick Checker system.
Your job: analyze price action, support/resistance levels, and technical indicators.

You will receive:
- Real-time quote with prev_close, prev_high, prev_low, atr_14
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
    "key_references": { "pdc": <price>, "pdl": <price>, "opening_range_low": <price>, "weekly_low": <price>, "vwap": <price> }
  },
  "resistance_levels": {
    "minor": [<price>, ...],
    "major": [<price>, ...],
    "key_references": { "pdh": <price>, "opening_range_high": <price>, "weekly_high": <price>, "monthly_high": <price> }
  },
  "chart_patterns": ["<pattern>", ...],
  "mtf_alignment": "aligned" | "mixed" | "conflicting",
  "volatility": "low" | "normal" | "elevated" | "extreme",
  "vwap_position": "above" | "below" | "testing",
  "entry_zone": { "low": <price>, "high": <price> },
  "stop_loss": <price>,
  "target_1": <price>,
  "target_2": <price>,
  "reasoning": ["• BIAS: <bias + why>", "• LEVEL: <key S/R + significance>", "• INDICATOR: <reading + implication>", "• ACTION: <approach>"]
}

Rules:
- Entry must be AT support/resistance, not chasing. Stop must anchor to a real S/R level.
- Use prev_close and ATR-14 to anchor entry zones. Note gaps vs prev_close if > ATR.
- reasoning: EXACTLY 3-5 bullets, format "• LABEL: one line", NO prose. Return ONLY the JSON.
"""


class TechnicalAgent(BaseAgent):
    name = "TechnicalAgent"

    def analyze(self, market_data: dict) -> dict:
        ticker   = market_data["ticker"]
        quote    = market_data["quote"]
        bars     = market_data["latest_bars"]
        inds     = market_data["indicators"]
        sr       = market_data["sr_levels"]
        daily    = market_data["daily_bars"]
        pre      = market_data.get("pre", {})
        timing   = pre.get("timing_flags", {})
        tomorrow = market_data.get("tomorrow_setup", False)

        user_prompt = f"""
Ticker: {ticker}
Current Price: {quote.get('last')} | Bid: {quote.get('bid')} | Ask: {quote.get('ask')}
Today: Open={quote.get('open')} High={quote.get('high')} Low={quote.get('low')}
Volume: {quote.get('volume')} | Change: {quote.get('change_pct')}%

Prev Day: Close={inds.get('prev_close')} High={inds.get('prev_high')} Low={inds.get('prev_low')} Range={inds.get('prev_range')}
ATR-14 (daily): {inds.get('atr_14')}

Indicators: RSI={inds.get('rsi')} VWAP={inds.get('vwap')} MACD={inds.get('macd')} Sig={inds.get('macd_signal')} Hist={inds.get('macd_hist')}
MAs: { {k: v for k, v in inds.items() if k.startswith('ema_') or k.startswith('sma_')} }

Key S/R: Intraday={json.dumps(sr.get('intraday', {}), default=str)} Daily={json.dumps(sr.get('daily', {}), default=str)}

Daily Bars (last 10): {json.dumps(daily, default=str)}
Recent 1-min bars (last 60): {json.dumps(bars[-60:], default=str)}
"""
        if tomorrow:
            user_prompt += "\nMARKET CLOSED — analyze setup for tomorrow's open. Anchor entry zones to prev_close and ATR. Skip session timing warnings."
        else:
            user_prompt += f"\nSession: {timing.get('session')} {timing.get('now_et')} near_open={timing.get('near_open')} lunch={timing.get('is_lunch')} near_close={timing.get('near_close')}\nAnalyze for a DAY TRADE. Identify all S/R levels, chart patterns, MTF alignment, directional verdict."

        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
