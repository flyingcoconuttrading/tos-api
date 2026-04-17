# PROMPT AUDIT — ~/tos-api
Generated: 2026-04-17

---

## 1. PROMPT-API-001 — SR Levels + Trend Analysis

| Check | Status |
|-------|--------|
| `~/tos-api/sr_levels.py` exists | ✅ FOUND |
| `~/tos-api/trend_analysis.py` exists | ✅ FOUND |
| `~/tos-api/data/sr_cache.db` exists | ✅ FOUND |

**Result: COMPLETE**

---

## 2. PROMPT-API-002 — DuckDB Migration

| Check | Status |
|-------|--------|
| `~/tos-api/db/duckdb_manager.py` exists | ✅ FOUND |
| `~/tos-api/data/trade_store_duck.py` exists | ✅ FOUND |
| `~/tos-api/data/tos_api.duckdb` exists and size > 0 | ✅ FOUND (2.6 MB) |
| `~/tos-api/data/trades_legacy.db` exists | ✅ FOUND |
| `main.py` imports `trade_store_duck` | ✅ FOUND — `from data import trade_store_duck as trade_store` (line 22) |

**Result: COMPLETE**

---

## 3. PROMPT-API-002a — Punch List Fixes

| Check | Status | Notes |
|-------|--------|-------|
| `checker.py`: `_apply_trade_wait()` exists | ✅ FOUND | line 56 |
| `checker.py`: `tomorrow_setup` excludes swing trades | ✅ FOUND | `not _is_swing` guard at line 122 |
| `preprocessor.py`: `is_lunch` starts at 12:00 | ✅ FOUND | `dtime(12, 0) <= t` at line 40 |
| `supervisor_agent.py`: `time_stop_instruction` variable exists | ❌ MISSING | Only `"time_stop"` dict key found (line 33); no `time_stop_instruction` variable |

**Result: PARTIAL** — 3/4 checks pass; `time_stop_instruction` was never added to supervisor_agent.py

---

## 4. PROMPT-API-003 — SR Chart + TRADE_WAIT

| Check | Status | Notes |
|-------|--------|-------|
| `main.py`: `GET /chart-data/{ticker}` endpoint | ✅ FOUND | line 779 |
| `App.jsx`: `SRChart` component | ✅ FOUND | line 87 |
| `App.jsx`: `TRADE_WAIT` in Badge map | ✅ FOUND | line 20 — `TRADE_WAIT: "badge-wait"` |
| `checker.py`: `runtime_ms` in response | ✅ FOUND | lines 140, 144 |

**Result: COMPLETE**

---

## 5. PROMPT-API-003a — Wildcard Swing Fix

| Check | Status | Notes |
|-------|--------|-------|
| `wildcard_agent.py`: `is_swing` branch exists | ✅ FOUND | lines 58, 68–76 |
| `supervisor_agent.py`: `_today = datetime.now(_ET).date()` | ✅ FOUND | line 111; `_ET = ZoneInfo("America/New_York")` at line 14 |
| `supervisor_agent.py`: `"SWING TRADE RULES"` instruction | ✅ FOUND | lines 88–91 in SYSTEM_PROMPT; `elif is_swing:` block at lines 163–172 |

**Result: COMPLETE** — All 3 checks pass. Confirmed via direct file read. Initial audit had false-negative grep results; latest commit `f4922be` applied these changes.

---

## 6. PROMPT-API-003b-004 — Macro Swing + Chart Cleanup + Scanner

| Check | Status | Notes |
|-------|--------|-------|
| `macro_agent.py`: `is_swing` branch exists | ✅ FOUND | lines 67, 70 |
| `~/tos-api/screener.py` exists | ✅ FOUND | |
| `~/tos-api/data/watchlists.json` exists | ✅ FOUND | |
| `main.py`: `GET /watchlist` endpoint | ✅ FOUND | line 524 |
| `main.py`: `POST /scan` endpoint | ✅ FOUND | line 672 |
| `App.jsx`: `ScanPanel` component | ✅ FOUND | line 1410 |
| `App.jsx`: `"scan"` in nav tabs | ✅ FOUND | line 2275 — `["analyze", "scan", "history", "settings"]` |

**Result: COMPLETE**

---

## 7. PROMPT-DASH-052 — SPY Context Bridge (~/tos-dash-v2)

| Check | Status | Notes |
|-------|--------|-------|
| `~/tos-dash-v2/spy_context.py` exists | ✅ FOUND | |
| `api.py`: `import spy_context` | ✅ FOUND | line 82 — `import spy_context as _spy_context` |
| `api.py`: `_spy_context.start()` | ✅ FOUND | line 88 |
| `api.py`: `GET /spy-context` endpoint | ✅ FOUND | line 1515 |
| `scalp_advisor.py`: `spy_ctx = self._cfg.get("_spy_context")` | ✅ FOUND | line 607 — with `{}` default |

**Result: COMPLETE**

---

## 8. SR-CACHE TREND PATCH

| Check | Status | Notes |
|-------|--------|-------|
| `main.py` `GET /sr-cache/{ticker}`: imports and calls `get_trend()` | ✅ FOUND | lines 507–510 — `from trend_analysis import get_trend` + `trend = get_trend(ticker)` |

**Result: COMPLETE**

---

## Summary

| Prompt | Status |
|--------|--------|
| PROMPT-API-001 | ✅ COMPLETE |
| PROMPT-API-002 | ✅ COMPLETE |
| PROMPT-API-002a | ⚠️ PARTIAL — `time_stop_instruction` missing in supervisor_agent.py |
| PROMPT-API-003 | ✅ COMPLETE |
| PROMPT-API-003a | ✅ COMPLETE — confirmed via direct file read (initial grep was a false negative) |
| PROMPT-API-003b-004 | ✅ COMPLETE |
| PROMPT-DASH-052 | ✅ COMPLETE |
| SR-CACHE TREND PATCH | ✅ COMPLETE |

### Action Items
1. **PROMPT-API-002a** — Add `time_stop_instruction` variable to `supervisor_agent.py`

> Note: The initial audit incorrectly reported API-003a as MISSING due to false-negative grep results. Direct file reads confirm all changes are present and committed in `f4922be`.
