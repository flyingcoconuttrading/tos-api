"""
agents/supervisor_agent.py
---------------------------
Synthesizes all checker agent verdicts into a final trade plan.
Applies conflict resolution rules, position sizing, and Checker methodology.
"""

import json
from agents.base_agent import BaseAgent
from config import CHECKER_RULES

SYSTEM_PROMPT = """You are the Supervisor Checker Agent in the Stock Pick Checker system.
You receive verdicts from three specialist agents and synthesize them into ONE final trade plan.

""" + CHECKER_RULES + """

CONFLICT RESOLUTION RULES (apply in order):
1. If Wild Card says DO_NOT_TRADE → Final is NO TRADE (always, no exceptions)
2. If Technical AND Macro agree on direction → MANDATORY TRADE
3. If Technical is directional (confidence > 50) → trade Technical's direction
4. If both are NEUTRAL with confidence < 40 each → NO TRADE
5. When agents conflict → follow Technical Agent (it has actual price data)

THE CHECKER IS BIASED TOWARD TRADING. TRADERS TRADE. But only at the RIGHT levels.

POSITION SIZING: Max risk = account_size × (risk_pct / 100). Shares = max_risk / stop_distance.
Size: full (100%) / half (50%) / quarter (25%) based on conviction + wild card risk.

TOMORROW'S SETUP MODE (when market_closed=true):
- Set verdict = "NO_TRADE" and no_trade_reason = "Market closed — setup for tomorrow's open"
- Confidence = current technical strength (no market-closed penalty)
- Skip intraday timing/liquidity warnings — max 2 bullets on market status
- Add "tomorrow_setup" key to your JSON output:
  {
    "bias": "LONG" | "SHORT" | "NEUTRAL",
    "entry_zone": {"low": <price>, "high": <price>},
    "stop": <price>,
    "target_1": {"price": <price>},
    "target_2": {"price": <price>},
    "confidence": <0-100>,
    "void_conditions": [
      "Opens below <stop>",
      "Gaps down ><gap_threshold> (<atr_mult>x ATR)",
      "Gaps up above <target_1.price> — check breakout continuation"
    ]
  }
- If symbol is gap-check-excluded or gap_threshold is null, omit the gap void condition.
- Base entry_zone on prev_close ± ATR for gap-adjusted anchoring.

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
  "risk_reward": "<e.g. 1:2.5>",
  "position_sizing": {
    "size_recommendation": "full" | "half" | "quarter",
    "rationale": "<why>",
    "max_risk_dollars": <number>,
    "stop_distance": <number>,
    "suggested_shares": <number>
  },
  "wild_card_flags": ["<flag>", ...],
  "manual_checks_required": ["<check>", ...],
  "agent_agreement": "full" | "partial" | "conflict",
  "reasoning": ["• VERDICT: ...", "• ENTRY: ...", "• SIZE: ...", "• RISK: ...", "• NOTE: ..."],
  "no_trade_reason": "<only if NO_TRADE>",
  "tomorrow_setup": { ... },
  "agent": "SupervisorAgent"
}

reasoning: EXACTLY 3-5 bullets, format "• LABEL: one line", NO prose. Return ONLY the JSON.
"""


class SupervisorAgent(BaseAgent):
    name = "SupervisorAgent"

    def synthesize(self, market_data: dict, technical: dict, macro: dict, wildcard: dict) -> dict:
        account_size = market_data.get("account_size", 25000)
        risk_percent = market_data.get("risk_percent", 2.0)
        pre          = market_data.get("pre", {})
        sizing       = pre.get("position_size", {})
        timing       = pre.get("timing_flags",  {})
        regime       = pre.get("market_regime", {})
        max_risk     = sizing.get("max_risk_dollars") or round(account_size * risk_percent / 100, 2)
        tomorrow     = market_data.get("tomorrow_setup", False)
        indicators   = market_data.get("indicators", {})

        user_prompt = f"""
Ticker: {market_data['ticker']}  Price: {market_data['quote'].get('last')}
Account: ${account_size:,.0f}  Risk: {risk_percent}% = ${max_risk:,.2f} max loss
Regime: {regime.get('regime', 'UNKNOWN')} VIX={regime.get('vix')} ({regime.get('vix_level')})
Session: {timing.get('session')} {timing.get('now_et')} near_open={timing.get('near_open')} lunch={timing.get('is_lunch')} near_close={timing.get('near_close')}

--- TECHNICAL ---
{json.dumps(technical, indent=2)}

--- MACRO ---
{json.dumps(macro, indent=2)}

--- WILD CARD ---
{json.dumps(wildcard, indent=2)}
"""
        if tomorrow:
            gap_cfg    = market_data.get("gap_detection", {})
            atr_mult   = float(gap_cfg.get("atr_multiplier", 1.0))
            atr_14     = float(indicators.get("atr_14") or 0)
            gap_thresh = round(atr_mult * atr_14, 2) if atr_14 else None
            excl       = gap_cfg.get("excluded_symbols", ["SPY", "SPX", "QQQ", "SPXW"])
            in_excl    = market_data["ticker"].upper() in [s.upper() for s in excl]
            prev_close = indicators.get("prev_close")
            user_prompt += f"""
market_closed: true — TOMORROW'S SETUP MODE
prev_close: {prev_close}  ATR-14: {atr_14}
gap_threshold: {gap_thresh} ({atr_mult}x ATR)  gap_check: {"SKIP — excluded symbol" if in_excl else "APPLY"}
excluded_symbols: {excl}

Set verdict=NO_TRADE. Anchor entry_zone to prev_close ± ATR. Generate tomorrow_setup with void_conditions.
"""
        else:
            user_prompt += "\nSynthesize all three verdicts. Apply conflict resolution rules. Calculate position sizing. Output complete trade plan JSON."

        result = self._ask_claude(SYSTEM_PROMPT, user_prompt)
        result["agent"] = self.name
        return result
