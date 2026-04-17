# tos-api CONTEXT.md
> Generated 2026-03-18. Full source dump for audit/refactor reference.

---

## Table of Contents
1. [checker.py — Full Source](#1-checkerpy--full-source)
2. [agents/supervisor_agent.py — Full Source](#2-agentssupervisor_agentpy--full-source)
3. [agents/technical_agent.py — Full Source](#3-agentstechnical_agentpy--full-source)
4. [/analyze Endpoint (main.py)](#4-analyze-endpoint-mainpy)
5. [System & User Prompts — All Agents](#5-system--user-prompts--all-agents)
6. [Supervisor Final Assembly Logic](#6-supervisor-final-assembly-logic)
7. [Price / Entry Validation Logic](#7-price--entry-validation-logic)

---

## 1. checker.py — Full Source

```python
"""
checker.py — Stock Pick Checker Orchestrator
Coordinates data collection + parallel agent dispatch + logging.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from data.collector import collect_all
import preprocessor
import settings as _settings_mod
from agents.technical_agent import TechnicalAgent
from agents.macro_agent import MacroAgent
from agents.wildcard_agent import WildCardAgent
from agents.supervisor_agent import SupervisorAgent
from db.database import log_trade

_technical  = TechnicalAgent()
_macro      = MacroAgent()
_wildcard   = WildCardAgent()
_supervisor = SupervisorAgent()
_executor   = ThreadPoolExecutor(max_workers=4)


async def run(ticker: str, account_size: float = 25000, risk_percent: float = 2.0, trade_type: str = "day") -> dict:
    ticker = ticker.upper().strip()

    # ── Step 1: Collect market data (dual timeframe + cache) ───────────────
    market_data = await collect_all(ticker, account_size, risk_percent)

    # ── Step 1b: Pre-processor (Python, no API cost) ───────────────────────
    market_data["pre"]        = preprocessor.run(market_data)
    market_data["trade_type"] = trade_type  # "day" or "swing"

    # ── Step 1c: Tomorrow's setup mode when market is closed ───────────────
    _session = market_data["pre"]["timing_flags"]["session"]
    market_data["tomorrow_setup"] = _session in ("after_hours", "weekend", "pre_market")
    market_data["gap_detection"]  = _settings_mod.load().get("gap_detection", {
        "atr_multiplier":   1.0,
        "excluded_symbols": ["SPY", "SPX", "QQQ", "SPXW"],
    })

    # ── Step 2: Dispatch checker agents in parallel ────────────────────────
    loop = asyncio.get_event_loop()
    technical, macro, wildcard = await asyncio.gather(
        loop.run_in_executor(_executor, _technical.analyze,  market_data),
        loop.run_in_executor(_executor, _macro.analyze,      market_data),
        loop.run_in_executor(_executor, _wildcard.analyze,   market_data),
    )

    # ── Step 3: Supervisor synthesizes final plan ──────────────────────────
    trade_plan = _supervisor.synthesize(market_data, technical, macro, wildcard)

    # ── Step 4: Assemble response ──────────────────────────────────────────
    pre = market_data["pre"]
    response = {
        "ticker":       ticker,
        "style":        trade_type,
        "price":        market_data["quote"].get("last"),
        "account_size": account_size,
        "risk_percent": risk_percent,
        "trade_plan":   trade_plan,
        "agent_verdicts": {
            "technical": technical,
            "macro":     macro,
            "wildcard":  wildcard,
        },
        "sr_levels":    market_data["sr_levels"],
        "market_context": {
            "spy_price":  market_data["market_ctx"].get("spy", {}).get("last"),
            "spy_change": market_data["market_ctx"].get("spy", {}).get("change_pct"),
            "qqq_price":  market_data["market_ctx"].get("qqq", {}).get("last"),
            "qqq_change": market_data["market_ctx"].get("qqq", {}).get("change_pct"),
            "vix":        market_data["market_ctx"].get("vix", {}).get("last"),
        },
        "pre": {
            "timing":  pre["timing_flags"],
            "regime":  pre["market_regime"],
            "sizing":  pre["position_size"],
        },
    }

    # ── Step 5: Log to PostgreSQL ──────────────────────────────────────────
    try:
        log_id = log_trade(
            {"ticker": ticker, "account_size": account_size, "risk_percent": risk_percent},
            response,
        )
        response["log_id"] = log_id
    except Exception as e:
        response["log_id"] = None
        response["log_error"] = str(e)

    return response
```

---

## 2. agents/supervisor_agent.py — Full Source

```python
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
```

---

## 3. agents/technical_agent.py — Full Source

```python
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
```

---

## 4. /analyze Endpoint (main.py)

```python
class AnalyzeRequest(BaseModel):
    ticker:       str
    account_size: float = DEFAULT_ACCOUNT_SIZE   # 25000
    risk_percent: float = DEFAULT_RISK_PERCENT   # 2.0
    trade_type:   str   = "day"                  # "day" or "swing"

@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not req.ticker or len(req.ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    try:
        result = await checker.run(
            req.ticker,
            account_size=req.account_size,
            risk_percent=req.risk_percent,
            trade_type=req.trade_type,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Validation in /analyze:**
- Only checks `not req.ticker or len(req.ticker) > 10` — rejects empty or >10-char tickers.
- No price validation, no sanity checks on account_size or risk_percent at the endpoint level.

---

## 5. System & User Prompts — All Agents

### 5a. TechnicalAgent

**System prompt** (`agents/technical_agent.py`, `SYSTEM_PROMPT`):

```
You are the Technical Checker Agent in the Stock Pick Checker system.
Your job: analyze price action, support/resistance levels, and technical indicators.

You will receive:
- Real-time quote with prev_close, prev_high, prev_low, atr_14
- 1-minute intraday OHLCV bars with indicators (RSI, EMA, SMA, MACD, VWAP)
- Daily bars (last 10 days)
- Pre-calculated S/R levels: PDH, PDL, PDC, weekly H/L, monthly H/L, opening range, VWAP

[JSON schema omitted — see Section 3]

Rules:
- Entry must be AT support/resistance, not chasing. Stop must anchor to a real S/R level.
- Use prev_close and ATR-14 to anchor entry zones. Note gaps vs prev_close if > ATR.
- reasoning: EXACTLY 3-5 bullets, format "• LABEL: one line", NO prose. Return ONLY the JSON.
```

**User prompt** (runtime-constructed, `TechnicalAgent.analyze()`):

```
Ticker: {ticker}
Current Price: {last} | Bid: {bid} | Ask: {ask}
Today: Open={open} High={high} Low={low}
Volume: {volume} | Change: {change_pct}%

Prev Day: Close={prev_close} High={prev_high} Low={prev_low} Range={prev_range}
ATR-14 (daily): {atr_14}

Indicators: RSI={rsi} VWAP={vwap} MACD={macd} Sig={macd_signal} Hist={macd_hist}
MAs: {ema_*/sma_* keys from indicators dict}

Key S/R: Intraday={sr.intraday JSON} Daily={sr.daily JSON}

Daily Bars (last 10): {daily_bars JSON}
Recent 1-min bars (last 60): {latest_bars[-60:] JSON}

[If market open]:
Session: {session} {now_et} near_open={near_open} lunch={is_lunch} near_close={near_close}
Analyze for a DAY TRADE. Identify all S/R levels, chart patterns, MTF alignment, directional verdict.

[If tomorrow_setup]:
MARKET CLOSED — analyze setup for tomorrow's open. Anchor entry zones to prev_close and ATR. Skip session timing warnings.
```

---

### 5b. MacroAgent

**System prompt** (`agents/macro_agent.py`, `SYSTEM_PROMPT`):

```
You are the Macro Checker Agent in the Stock Pick Checker system.
Your job: assess whether broader market conditions favor a trade in this ticker.

[JSON schema omitted — see agents/macro_agent.py]

Rules:
- VIX < 15 = LOW, 15-20 = NORMAL, 20-30 = ELEVATED, >30 = EXTREME
- If SPY and QQQ disagree → CHOPPY regime
- SPY change > +0.5% = up, < -0.5% = down, otherwise flat
- reasoning: EXACTLY 3-5 bullet strings, format "• LABEL: one line", NO prose paragraphs
- Return ONLY the JSON object
```

**User prompt** (runtime-constructed, `MacroAgent.analyze()`):

```
Ticker: {ticker}  Price: {last}
Regime: {regime} | SPY {spy_trend} ({spy_change_pct}%) | QQQ {qqq_trend} ({qqq_change_pct}%) | VIX {vix} ({vix_level})
SPY: {last} H={high} L={low} Vol={volume}
QQQ: {last} H={high} L={low} Vol={volume}
News: [ENABLE_NEWS=false] Economic calendar: [ENABLE_ECON_CAL=false — check FOMC/CPI/NFP/earnings manually]

[If market open]:
Session: {session} {now_et} near_open={near_open} lunch={is_lunch} near_close={near_close}
Assess nuance: session timing, breadth/volume confirmation, does macro SUPPORT or OPPOSE {ticker}?

[If tomorrow_setup]:
MARKET CLOSED — assess macro conditions for tomorrow's open. Skip session timing warnings (max 1 line). Focus on whether macro supports or opposes a trade at tomorrow's open.
```

---

### 5c. WildCardAgent

**System prompt** (`agents/wildcard_agent.py`, `SYSTEM_PROMPT`):

```
You are the Wild Card Checker Agent in the Stock Pick Checker system.
Your job: identify ALL external risks and timing factors that could invalidate the trade.
Be specific, honest, and thorough. Name each risk individually.

[JSON schema omitted — see agents/wildcard_agent.py]

Timing risks to check:
- Within 30 min of open (9:30-10:00 ET) → high volatility
- Lunch hour (12:00-13:00 ET) → low liquidity (Checker Lunch Rule: avoid new entries)
- Within 30 min of close (15:30-16:00 ET) → forced exits, MOC imbalances
- Weekend hold risk
- Earnings proximity (within 5 days = HIGH risk)
- VIX > 25 = elevated volatility risk

reasoning: EXACTLY 3-5 bullet strings, format "• LABEL: one line", NO prose paragraphs.
Return ONLY the JSON object.
```

**User prompt** (runtime-constructed, `WildCardAgent.analyze()`):

```
Time: {weekday HH:MM} ET
Ticker: {ticker}  Price: {last}  Open: {open}  H: {high}  L: {low}  Vol: {volume}  Chg: {change_pct}%
VIX: {vix}  SPY Chg: {spy.change_pct}%  QQQ Chg: {qqq.change_pct}%
PDH: {daily.pdh}  PDL: {daily.pdl}  Wkly H: {daily.weekly_high}  Wkly L: {daily.weekly_low}
VWAP: {intraday.vwap}  ORH: {intraday.opening_range_high}  ORL: {intraday.opening_range_low}
Economic calendar: [ENABLE_ECON_CAL=false — flag if manual check needed]

[If market open]:
Identify ALL timing risks and external risk factors for a day trade right now. Name each risk specifically. Provide actionable contingencies.

[If tomorrow_setup]:
MARKET CLOSED — identify risks for tomorrow's open only. Skip intraday timing warnings (lunch, near-open, near-close). Focus on overnight/gap risk, earnings proximity, macro events.
```

---

### 5d. SupervisorAgent

**System prompt** (`agents/supervisor_agent.py`, `SYSTEM_PROMPT`):

Composed as: preamble + `CHECKER_RULES` (from `config.py`) + conflict resolution rules + output schema.

```
You are the Supervisor Checker Agent in the Stock Pick Checker system.
You receive verdicts from three specialist agents and synthesize them into ONE final trade plan.

CHECKER METHODOLOGY RULES (follow strictly):
1. Buy at SUPPORT, not at breakout — enter on pullbacks that are likely to hold
2. Short at RESISTANCE — wait for rejection confirmation, not anticipation
3. Define Risk/Reward BEFORE entry — minimum 1:1.5, prefer 1:2+
4. Time stops are mandatory — day trades must close by 4:00 PM ET
5. Reduce size when Wild Card risk is HIGH or DO_NOT_TRADE
6. Never average into a losing position
7. Wait for S/R levels to be tested and confirmed — patience over FOMO

CONFLICT RESOLUTION RULES (apply in order):
1. If Wild Card says DO_NOT_TRADE → Final is NO TRADE (always, no exceptions)
2. If Technical AND Macro agree on direction → MANDATORY TRADE
3. If Technical is directional (confidence > 50) → trade Technical's direction
4. If both are NEUTRAL with confidence < 40 each → NO TRADE
5. When agents conflict → follow Technical Agent (it has actual price data)

THE CHECKER IS BIASED TOWARD TRADING. TRADERS TRADE. But only at the RIGHT levels.

POSITION SIZING: Max risk = account_size × (risk_pct / 100). Shares = max_risk / stop_distance.
Size: full (100%) / half (50%) / quarter (25%) based on conviction + wild card risk.

[Tomorrow's setup mode instructions and full JSON output schema — see Section 2]
```

**User prompt** (runtime-constructed, `SupervisorAgent.synthesize()`):

```
Ticker: {ticker}  Price: {last}
Account: ${account_size}  Risk: {risk_percent}% = ${max_risk} max loss
Regime: {regime} VIX={vix} ({vix_level})
Session: {session} {now_et} near_open={near_open} lunch={is_lunch} near_close={near_close}

--- TECHNICAL ---
{full technical dict as JSON}

--- MACRO ---
{full macro dict as JSON}

--- WILD CARD ---
{full wildcard dict as JSON}

[If market open]:
Synthesize all three verdicts. Apply conflict resolution rules. Calculate position sizing. Output complete trade plan JSON.

[If tomorrow_setup]:
market_closed: true — TOMORROW'S SETUP MODE
prev_close: {prev_close}  ATR-14: {atr_14}
gap_threshold: {gap_thresh} ({atr_mult}x ATR)  gap_check: APPLY | SKIP — excluded symbol
excluded_symbols: [...]

Set verdict=NO_TRADE. Anchor entry_zone to prev_close ± ATR. Generate tomorrow_setup with void_conditions.
```

---

## 6. Supervisor Final Assembly Logic

**File:** `agents/supervisor_agent.py`, method `SupervisorAgent.synthesize()`

The supervisor does **not** implement its own Python-level conflict resolution or assembly logic. It:

1. Pulls pre-processed context from `market_data` (`account_size`, `risk_percent`, `pre.position_size`, `pre.timing_flags`, `pre.market_regime`).
2. Computes `max_risk = sizing.get("max_risk_dollars") or round(account_size * risk_percent / 100, 2)`.
3. Builds a user prompt containing the full JSON output of all three sub-agents.
4. Detects `tomorrow_setup` mode and appends gap/ATR anchoring instructions if true.
5. Calls `self._ask_claude(SYSTEM_PROMPT, user_prompt)` — delegates **all conflict resolution, sizing, and final assembly to Claude** via the system prompt rules.
6. Tags the result with `result["agent"] = "SupervisorAgent"` and returns it.

**In-Python conflict resolution: NONE.** All logic (conflict priority order, sizing formula, tomorrow_setup, void_conditions) is expressed as natural-language instructions in `SYSTEM_PROMPT` and enforced only by the LLM.

**Position sizing formula (as instructed to Claude):**
```
max_risk = account_size × (risk_pct / 100)
suggested_shares = max_risk / stop_distance
size_recommendation = "full" | "half" | "quarter"  # based on conviction + wildcard risk
```

**Claude model used:** `claude-sonnet-4-20250514` (from `config.py`)
**Max tokens:** 1024 per call (from `agents/base_agent.py`)

---

## 7. Price / Entry Validation Logic

### What exists

#### /analyze endpoint (main.py:229)
```python
if not req.ticker or len(req.ticker) > 10:
    raise HTTPException(status_code=400, detail="Invalid ticker symbol")
```
- Ticker string length check only. No validation of account_size, risk_percent, or trade_type values.

#### /trades endpoint — TradeCreate model (main.py:166-174)
```python
class TradeCreate(BaseModel):
    symbol:      str
    direction:   str              # LONG / SHORT
    entry_price: float
    stop:        float
    target:      float
    target_2:    Optional[float] = None
    trade_type:  str  = "scalp"
    notes:       Optional[str] = ""
```
- Pydantic type coercion only. No range checks, no validation that `stop < entry_price` for LONG trades, no check that `target > entry_price`, no R:R floor enforcement.

#### Technical agent system prompt (agents/technical_agent.py)
- The LLM is instructed: *"Entry must be AT support/resistance, not chasing. Stop must anchor to a real S/R level."*
- No Python code enforces this — it is LLM guidance only.

#### Supervisor system prompt (agents/supervisor_agent.py)
- The LLM is instructed: *"Define Risk/Reward BEFORE entry — minimum 1:1.5, prefer 1:2+"*
- No Python code validates the R:R ratio in the returned JSON.

#### Price watcher (main.py:85-103, `_check_open_trades`)
- Compares live price against `stop` and `target` fields in the trade store.
- `trade_store.check_price_trigger(trade, price)` — triggers closes, but this is post-entry monitoring, not entry validation.

### What does NOT exist
- **No server-side validation** that `entry_price` is near the current market price.
- **No R:R ratio floor** enforced in Python (only instructed to Claude).
- **No check** that `stop` is below `entry_price` for LONG (or above for SHORT).
- **No check** that `account_size` > 0 or `risk_percent` is within a sane range (e.g. 0.1–10%).
- **No check** that the supervisor's returned `entry_zone`, `stop_loss`, and `target_1` satisfy the stated 1:1.5 R:R minimum.
- **No staleness guard** on the price used for analysis — if the quote cache is stale, the analysis proceeds with the cached price.
