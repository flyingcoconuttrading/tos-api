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
- For day/scalp: 1-minute intraday OHLCV bars with indicators (RSI, EMA, SMA, MACD, VWAP)
- For swing: daily OHLCV bars with indicators (RSI, EMA, SMA, MACD) — no VWAP (intraday only)
- Daily bars, Pre-calculated S/R levels: PDH, PDL, PDC, weekly H/L, monthly H/L, opening range
- VWAP is only available and relevant for day/scalp trades — never flag it as missing on swing

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

        is_swing   = market_data.get("is_swing", False)
        trade_type = market_data.get("trade_type", "day")

        if is_swing:
            # Swing: daily bars only, no VWAP, no intraday S/R
            user_prompt = f"""
Ticker: {ticker}
Current Price: {quote.get('last')} | Change: {quote.get('change_pct')}%
Trade Type: {trade_type}

Prev Day: Close={inds.get('prev_close')} High={inds.get('prev_high')} Low={inds.get('prev_low')} Range={inds.get('prev_range')}
ATR-14 (daily): {inds.get('atr_14')}

Indicators: RSI={inds.get('rsi')} MACD={inds.get('macd')} Sig={inds.get('macd_signal')} Hist={inds.get('macd_hist')}
MAs: { {k: v for k, v in inds.items() if k.startswith('ema_') or k.startswith('sma_')} }

Key S/R Daily: {json.dumps(sr.get('daily', {}), default=str)}

Daily Bars (last 60): {json.dumps(daily, default=str)}
"""
        else:
            # Day/scalp: intraday bars + VWAP + intraday S/R
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

        if is_swing:
            weekly_bars = market_data.get("weekly_bars", [])
            time_stop_map = {
                "swing_short":  "4 weeks from entry",
                "swing_medium": "12 weeks from entry",
                "swing_long":   "26 weeks from entry",
            }
            user_prompt += f"""
Trade Type: {trade_type}
Time Stop: {time_stop_map.get(trade_type, "4 weeks from entry")}
Weekly Bars (last 20): {json.dumps(weekly_bars, default=str)}
Analyze for a SWING TRADE. Use daily S/R levels. Time stops are weeks not hours.
Do not reference intraday session timing (no near_open, no lunch, no near_close).
Weekly trend takes priority over daily for swing_medium and swing_long.
"""
        elif tomorrow:
            user_prompt += "\nMARKET CLOSED — analyze setup for tomorrow's open. Anchor entry zones to prev_close and ATR. Skip session timing warnings."
        else:
            user_prompt += f"\nSession: {timing.get('session')} {timing.get('now_et')} near_open={timing.get('near_open')} lunch={timing.get('is_lunch')} near_close={timing.get('near_close')}\nAnalyze for a DAY TRADE. Identify all S/R levels, chart patterns, MTF alignment, directional verdict."

        sr_cache = market_data.get("sr_cache", {})
        trend    = market_data.get("trend", {})

        def _fmt_levels(levels: list, n: int = 5) -> str:
            if not levels:
                return "none"
            top = sorted(levels, key=lambda x: (
                0 if x.get("strength") == "STRONG" else
                1 if x.get("strength") == "MODERATE" else 2,
                x.get("bars_since", 999)
            ))[:n]
            return ", ".join(
                f"${l['price']} ({l['strength']}, {l['bars_since']}d ago,"
                f" {l['volume_ratio']:.1f}x vol)"
                for l in top
            )

        user_prompt += f"""
--- 1-YEAR S/R LEVELS ---
Swing Resistance: {_fmt_levels(sr_cache.get("swing_highs", []))}
Swing Support:    {_fmt_levels(sr_cache.get("swing_lows", []))}
Yearly High: ${sr_cache.get("yearly_high", {}).get("price") if sr_cache.get("yearly_high") else "N/A"}
Yearly Low:  ${sr_cache.get("yearly_low",  {}).get("price") if sr_cache.get("yearly_low") else "N/A"}
6M High: ${sr_cache.get("6m_high", {}).get("price") if sr_cache.get("6m_high") else "N/A"}
6M Low:  ${sr_cache.get("6m_low",  {}).get("price") if sr_cache.get("6m_low") else "N/A"}
HVN Zones: {[f"${z['low']:.2f}-${z['high']:.2f}" for z in sr_cache.get("hvn_zones", [])[:3]]}
LVN Zones: {[f"${z['low']:.2f}-${z['high']:.2f}" for z in sr_cache.get("lvn_zones", [])[:3]]}

--- TREND CONTEXT ---
Daily:  {trend.get("daily",  {}).get("direction")} | \
Strength: {trend.get("daily",  {}).get("strength")} | \
ADX: {trend.get("daily",  {}).get("adx")} | \
Structure: {trend.get("daily",  {}).get("structure")} | \
Age: {trend.get("daily",  {}).get("trend_age_bars")}d | \
Momentum: {trend.get("daily",  {}).get("momentum")}
Weekly: {trend.get("weekly", {}).get("direction")} | \
Strength: {trend.get("weekly", {}).get("strength")} | \
ADX: {trend.get("weekly", {}).get("adx")} | \
Structure: {trend.get("weekly", {}).get("structure")} | \
Age: {trend.get("weekly", {}).get("trend_age_bars")}w | \
Momentum: {trend.get("weekly", {}).get("momentum")}
MTF Alignment: {trend.get("mtf_alignment")} | \
Bias: {trend.get("trade_bias")}
Bias Reason: {trend.get("bias_reason")}
"""

        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
