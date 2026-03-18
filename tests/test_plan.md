# Test Plan — tos-api
Last updated: 2026-03-18

Changes covered:
- Feature 1: TAKE TRADE button (live price fetch + auto-submit)
- Feature 2: Two targets (TARGET_1_HIT partial close, TARGET_2 full close)
- Feature 3: Automatic outcome tracking (5m/15m/30m/1d P&L snapshots)
- Background: _price_watcher now also calls _check_log_outcomes every 30s
- Feature 4: API call counter — in-memory request/token tracking, GET /stats
- Feature 5: Log report — aggregate analysis stats, GET /logs/report
- UI: Settings tab shows /stats; History tab shows Reports section

---

## UI Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| U1 | TAKE TRADE button visible | 1. Analyze a ticker (e.g. AAPL) that returns verdict=TRADE. 2. Look at the result card header. | "TAKE TRADE" button appears next to "+ ADD TRADE". Button is green-outlined. | |
| U2 | TAKE TRADE button absent on NO_TRADE | 1. Analyze a ticker that returns verdict=NO_TRADE. 2. Look at the result card. | No "TAKE TRADE" button — only the no-trade reason text. | |
| U3 | TAKE TRADE auto-submits trade | 1. Analyze a TRADE ticker. 2. Click "TAKE TRADE". | Button changes to "Trade Added ✓" for ~2s, then resets. Trade Tracker section reloads and shows the new trade with current live price as entry. | |
| U4 | TAKE TRADE fills correct fields | 1. After clicking TAKE TRADE, check the newly added trade row in Trade Tracker. | entry_price = live market price (not entry_zone.low). stop = plan.stop_loss. T1 = plan.target_1.price. T2 = plan.target_2.price (if present). direction = plan direction. | |
| U5 | TAKE TRADE scrolls to tracker | 1. Scroll up so Trade Tracker is off screen. 2. Click TAKE TRADE. | Page smoothly scrolls down to Trade Tracker section. | |
| U6 | Target 2 in trade form | 1. Click "+ Add Trade" in Trade Tracker. 2. Look at the second form row. | Four inputs visible: Entry, Stop, Target 1, Target 2 (opt). | |
| U7 | Target 2 pre-fills from analysis | 1. Analyze a TRADE ticker. 2. Click "+ Add Trade". | Target 2 input is pre-filled with plan.target_2.price. | |
| U8 | Trade table shows T1/T2 columns | 1. Open Trade Tracker with at least one trade. | Table headers show T1 and T2 columns (replacing single Target column). | |
| U9 | TARGET_1_HIT display | 1. Have a trade reach target_1 (or manually set status via API). 2. Observe Trade Tracker row. | T1 cell shows green "✓". T2 cell still shows target_2 price. Status shows TARGET_1_HIT in gold. | |
| U10 | History tab — hit rate bar | 1. Click HISTORY nav tab. 2. If there are resolved TRADE logs. | Hit rate bar shows "X% of TRADE verdicts were profitable at 30m" with green/red color based on rate. | |
| U11 | History tab — filter buttons | 1. In History tab, click "TRADE" filter. | Table only shows rows where verdict=TRADE. Click "NO_TRADE" — only NO_TRADE rows. "Correct" — only out_30m_correct=true. "Wrong" — only false. "ALL" resets. | |
| U12 | History tab — outcome P&L columns | 1. In History tab, check a log that has been resolved (>30m old). | 5m P&L, 15m P&L, 30m P&L columns show colored percentages. Pending entries show "—" or "…". | |
| U13 | History tab — Correct? checkmark | 1. In History tab, look at the ✓? column. | Resolved logs show ✓ (green) or ✗ (red). Unresolved show "…" in muted color. | |

---

## API Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| A1 | GET /quote/{ticker} exists | `curl http://localhost:8002/quote/AAPL` | JSON with keys: symbol, price, bid, ask, timestamp. price is a non-zero float. | |
| A2 | GET /quote/{ticker} invalid | `curl http://localhost:8002/quote/TOOLONGTICKER123` | HTTP 400 with detail "Invalid ticker". | |
| A3 | GET /quote/{ticker} bad symbol | `curl http://localhost:8002/quote/ZZZZZZ` | HTTP 503 "Price unavailable" OR valid response if market is open. | |
| A4 | POST /trades with target_2 | `curl -X POST .../trades -d '{"symbol":"AAPL","direction":"LONG","entry_price":180,"stop":175,"target":185,"target_2":190,"trade_type":"scalp"}'` | HTTP 200, returns trade_id. GET /trades/{id} shows target_2=190. | |
| A5 | POST /trades without target_2 | Same as A4 but omit target_2 field. | HTTP 200. GET /trades/{id} shows target_2=null. Backward compatible. | |
| A6 | GET /trades returns target_2 | `curl http://localhost:8002/trades` | Each trade object includes a target_2 field (null or float). | |
| A7 | GET /logs returns outcome columns | `curl http://localhost:8002/logs` | Response includes out_5m_pnl, out_15m_pnl, out_30m_pnl, out_30m_correct fields (may be null). | |

---

## Background Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| B1 | TARGET_1 partial close | 1. Add a LONG trade with target=current_price+0.01 and target_2=current_price+5. 2. Wait up to 60s. | Trade status changes to TARGET_1_HIT. out_t1_price and out_t1_pnl populated. Trade still visible in Open section of tracker. exit_price remains null. | |
| B2 | TARGET_2 full close | 1. After B1, set target_2 to current_price+0.01 by re-adding trade. 2. Wait up to 60s. | Trade status changes to TARGET_HIT. closed_at and exit_price populated. Trade moves to Closed section. | |
| B3 | STOP close still works | 1. Add a LONG trade with stop=current_price+1 (above market). 2. Wait up to 60s. | Trade auto-closes with status=STOPPED. exit_reason=STOP. | |
| B4 | Log outcome 5m snapshot | 1. Run /analyze on any ticker. Note the log id from /logs. 2. Wait 5+ minutes. | GET /logs shows out_5m_price and out_5m_pnl populated for that log_id. out_5m_correct is true/false. | |
| B5 | Log outcome 30m snapshot | 1. Wait 30+ minutes after an /analyze call with verdict=TRADE. | out_30m_price, out_30m_pnl, out_30m_correct populated. out_1d_price still null. | |
| B6 | Old logs not tracked | 1. Check logs older than 24h. | out_30m_price is NOT updated retroactively (get_unresolved_logs excludes logs > 24h). | |

---

## API Usage Counter Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| C1 | GET /stats exists | `curl http://localhost:8002/stats` | JSON with keys: uptime_seconds, total_calls, ai_calls, endpoints, unauthorized_ai_calls. | |
| C2 | /stats total_calls increments | 1. GET /stats, note total_calls. 2. Make any request. 3. GET /stats again. | total_calls is higher by at least 2 (the two /stats calls). | |
| C3 | /stats ai_calls count | 1. POST /analyze once. 2. GET /stats. | ai_calls.count ≥ 1. avg_tokens_in and avg_tokens_out are non-zero. total_cost_est > 0. | |
| C4 | /stats endpoints map | GET /stats after mixing /analyze, /quote, /trades calls. | endpoints dict contains "/analyze", "/quote", "/trades" keys with correct counts. | |
| C5 | /stats resets on restart | Restart the API server. GET /stats. | total_calls = 1 (just this request), uptime_seconds < 60. | |
| C6 | unauthorized_ai_calls = 0 | Normal operation — POST /analyze with valid ticker. | unauthorized_ai_calls is always 0 in normal use. | |

## Log Report Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| L1 | GET /logs/report exists | `curl http://localhost:8002/logs/report` | JSON with keys: total_analyses, by_verdict, by_symbol, outcome_summary, by_trade_type, confidence_buckets. | |
| L2 | confidence_buckets has 4 entries | GET /logs/report. | confidence_buckets array has exactly 4 items with ranges: "0-25", "26-50", "51-75", "76-100". | |
| L3 | outcome_summary correct_pct | GET /logs/report after >30 min from an /analyze TRADE call. | correct_5m_pct, correct_15m_pct, correct_30m_pct are floats (or null if no resolved data). | |
| L4 | by_symbol top 5 | Run /analyze for ≥2 different tickers multiple times. GET /logs/report. | by_symbol is sorted by count descending. Each entry has symbol, count, avg_confidence, trade_rate, outcome_rate. | |
| L5 | by_trade_type split | POST /analyze with trade_type=day and trade_type=swing. GET /logs/report. | by_trade_type has keys "day" and/or "swing" with count, trade_rate, correct_30m_pct. | |
| L6 | Reports section in History tab | 1. Open app, click HISTORY tab. | Reports section visible at top with hit rate cards, top symbols table, confidence chart, AI cost. | |
| L7 | Settings tab shows /stats | 1. Click SETTINGS tab. | API Usage panel shows uptime, total calls, AI calls, cost estimate, endpoint breakdown. | |

## Regression Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| R1 | /analyze still works | `curl -X POST .../analyze -d '{"ticker":"AAPL"}'` | Returns full result with trade_plan, agent_verdicts, market_context. No 500 errors. | |
| R2 | Existing trades without target_2 | GET /trades for trades created before this update. | target_2 field is null — no crash, no missing field error. | |
| R3 | Single-target trade still auto-closes | Add trade with only target (no target_2). Let price hit target. | check_price_trigger returns "TARGET" (legacy path). Trade closes with TARGET_HIT. | |
| R4 | Manual close still works | Click Close on an open trade, enter exit price. | Trade closes with status=CLOSED, exit_reason=MANUAL. | |
| R5 | History Re-analyze button | In History tab, click Re-analyze on a log row. | Switches to Analyze tab, pre-fills ticker, runs analysis. | |
| R6 | /health endpoint | `curl http://localhost:8002/health` | `{"status":"ok","version":"2.1.0"}` | |
| R7 | DB migration is idempotent | Restart the API server twice. | No errors in startup logs about duplicate columns. target_2 column exists once. | |
| R8 | Scalp interval snapshots still fire | Add a scalp trade. Wait 5m. | out_5m_price populated via check_scalp_intervals (existing behavior unchanged). | |
