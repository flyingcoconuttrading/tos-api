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

## Session A — Python Intelligence Layer Tests (2026-04-16)

### sr_levels.py Unit Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| S1 | _init_db creates sr_levels table | Import sr_levels; call `_init_db()` twice. | No error on second call (idempotent). SQLite file created at data/sr_cache.db. | |
| S2 | _find_swings returns sorted lists | Build a 50-bar DataFrame with known swing highs/lows. Call `_find_swings(df)`. | Returns (swing_highs, swing_lows) both sorted by bars_since ascending. Each entry has keys: price, date, volume, avg_volume, volume_ratio, strength, bars_since. | |
| S3 | _find_swings strength labels | Use bars with volume_ratio ≥ 1.5, 0.8–1.5, < 0.8. | Strength values are STRONG, MODERATE, WEAK respectively. | |
| S4 | _volume_profile buckets | Call `_volume_profile(df)` on 50 daily bars. | Returns (hvn_zones, lvn_zones). HVN buckets have total_volume ≥ 1.5 × avg. LVN ≤ 0.5 × avg. Both lists sorted by low ascending. | |
| S5 | _key_levels yearly/6m | Call `_key_levels(df)` on 252-bar DataFrame. | Returns dict with yearly_high, yearly_low (with volume_ratio), 6m_high, 6m_low (no volume_ratio). Prices match df high/low maxima. | |
| S6 | get_levels cache hit | Call `get_levels("AAPL")` twice. | Second call returns same dict (from SQLite cache). No Schwab API call on second invocation. | |
| S7 | get_levels no-data error | Call get_levels for a ticker where Schwab returns empty. | Returns dict with error="no data" and all list fields empty. Does not raise. | |
| S8 | refresh_cache forces recalc | Call `refresh_cache("AAPL")` after a fresh cache exists. | Cache entry deleted, then recalculated. Returns fresh result. | |
| S9 | get_levels result shape | Call `get_levels("AAPL")` with real data. | Result contains: ticker, calculated_at, lookback_days=365, swing_highs, swing_lows, yearly_high, yearly_low, 6m_high, 6m_low, hvn_zones, lvn_zones. | |

### trend_analysis.py Unit Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| T1 | _init_db creates trend_data table | Import trend_analysis; call `_init_db()` twice. | trend_data table created in sr_cache.db. No error on repeat. | |
| T2 | _linreg direction UP | Pass 60 steadily increasing close prices. | direction="UP", slope > 0, r_squared close to 1.0. | |
| T3 | _linreg direction DOWN | Pass 60 steadily decreasing closes. | direction="DOWN", slope < 0. | |
| T4 | _linreg direction SIDEWAYS | Pass 60 flat/noisy closes. | direction="SIDEWAYS". | |
| T5 | _compute_adx returns Series | Call `_compute_adx(df)` on 50-bar DataFrame. | Returns pd.Series with length = len(df). Last value is float. | |
| T6 | _hh_hl_structure HH_HL | Pass 3 swing_highs with ascending prices and 3 swing_lows with ascending prices (most recent first). | Returns "HH_HL". | |
| T7 | _hh_hl_structure LH_LL | Pass descending highs and descending lows (most recent first). | Returns "LH_LL". | |
| T8 | _hh_hl_structure MIXED | Pass mixed/random swing prices. | Returns "MIXED". | |
| T9 | _trendline None < 3 points | Call `_trendline([], 100)` and `_trendline([p1, p2], 100)`. | Returns None for both. | |
| T10 | _resample_weekly < 20 weeks | Pass 5-week daily DataFrame to `_resample_weekly`. | Returns empty DataFrame. | |
| T11 | _resample_weekly correct OHLCV | Pass 252 daily bars. | Returns weekly DataFrame with columns: datetime, open, high, low, close, volume. open=first, high=max, low=min, close=last, volume=sum per week. | |
| T12 | _mtf_alignment ALIGNED_BULLISH | daily=UP, weekly=UP. | Returns ("ALIGNED_BULLISH", "LONG_ONLY", "Both timeframes bullish — trade long pullbacks only"). | |
| T13 | _mtf_alignment CONFLICT | daily=UP, weekly=DOWN. | Returns ("CONFLICT", "NEUTRAL", "Timeframe conflict — reduce size, wait for alignment"). | |
| T14 | get_trend cache hit | Call `get_trend("AAPL")` twice. | Second call from cache. No recalculation. | |
| T15 | get_trend result shape | Call `get_trend("AAPL")` with real data. | Result contains: ticker, calculated_at, daily (full timeframe dict), weekly (full timeframe dict), mtf_alignment, trade_bias, bias_reason. | |
| T16 | get_trend no-data graceful | Call for empty ticker. | Returns {"ticker": ..., "error": "no data"}. Does not raise. | |
| T17 | _analyze_timeframe SIDEWAYS when adx<20 | Pass DataFrame where ADX is < 20. | direction="SIDEWAYS" regardless of linreg slope. | |

### Integration Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| I1 | collect_all includes sr_cache | POST /analyze AAPL. Inspect raw response via debug log or unit test on collect_all result. | Result dict contains "sr_cache" key with swing_highs, swing_lows, hvn_zones, lvn_zones. | |
| I2 | collect_all includes trend | Same as I1. | Result dict contains "trend" key with daily.direction, weekly.direction, mtf_alignment, trade_bias. | |
| I3 | TechnicalAgent prompt includes S/R context | Mock market_data with sr_cache and trend populated. Call TechnicalAgent.analyze(). | user_prompt contains "--- 1-YEAR S/R LEVELS ---" and "--- TREND CONTEXT ---" sections with correct values. | |
| I4 | TechnicalAgent graceful on empty sr_cache | Pass market_data with sr_cache={}, trend={}. | No KeyError or AttributeError. Prompt shows "none" / "N/A" for missing values. | |
| I5 | Concurrent execution in collect_all | Time collect_all for a ticker. | sr_cache and trend computed concurrently with other futures, not sequentially after. Total time ≈ max of individual tasks, not sum. | |
| I6 | sr_cache.db created on first run | Delete data/sr_cache.db if exists. Call get_levels("AAPL"). | data/sr_cache.db created. sr_levels table present. | |
| I7 | trend_data table created | After I6, call get_trend("AAPL"). | trend_data table now also present in sr_cache.db. | |

---

## Session B — DuckDB Migration + Swing Trade Extension (v2.2.0, 2026-04-16)

### DuckDB / Migration Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| D1 | DuckDB schema init | Start API server cold. Check logs. | `[DuckDB] Schema ready: .../data/tos_api.duckdb` in startup output. No error. | |
| D2 | trades.db migration | Have data/trades.db present before first start. Start server. | trades.db renamed to trades_legacy.db. DuckDB tos_api.duckdb created. Log shows "[Migration] trades.db renamed...". | |
| D3 | Migration idempotent | Restart server a second time. | No "already exists" error. trades_legacy.db not overwritten. | |
| D4 | GET /stats trade_db key | `curl http://localhost:8002/stats` | Response includes `trade_db` with keys: engine="duckdb", total_trades, open, closed. | |
| D5 | DBeaver read_only connect | Open DBeaver. Connect to data/tos_api.duckdb with read_only=True. | Tables visible: trades, sr_levels, trend_data, price_history, scan_results. | |
| D6 | trades.csv exported on insert | POST /trades. Check data/ directory. | data/trades.csv created/updated with the new trade row. | |

### Swing Trade Type Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| SW1 | POST /trades with swing_short | `POST /trades {"symbol":"AAPL","direction":"LONG","entry_price":180,"stop":170,"target":200,"trade_type":"swing_short"}` | HTTP 200, trade_id returned. GET /trades/{id} shows trade_type="swing_short", entry_daily_trend/entry_weekly_trend populated. | |
| SW2 | POST /trades with swing_medium | Same as SW1 but trade_type="swing_medium". | HTTP 200. trade_type="swing_medium". | |
| SW3 | POST /trades with swing_long | trade_type="swing_long". | HTTP 200. trade_type="swing_long". | |
| SW4 | Swing interval snapshots — swing_short | Add swing_short trade. Manually advance entry_time 1d in DB. Wait for session_checker. | out_1d_price populated. out_3d_price still null. | |
| SW5 | Swing interval snapshots — swing_long | Wait 7d equivalent. | out_7d_price, out_14d_price etc. populated per SWING_INTERVALS schedule. | |
| SW6 | Trend snapshot refresh | Add swing trade. Check last_trend_update. Wait 24h+ (or force via test). | last_trend_update refreshed. entry_daily_trend/entry_weekly_trend updated. | |
| SW7 | POST /analyze with trade_type=swing_short | `POST /analyze {"ticker":"AAPL","trade_type":"swing_short"}` | No 500 error. Response has is_swing=true, trade_type="swing_short". Prompt used extended daily bars, not intraday. | |
| SW8 | POST /analyze with trade_type=swing_long | `POST /analyze {"ticker":"AAPL","trade_type":"swing_long"}` | weekly_bars populated in market_data. Agent prompt contains "SWING TRADE" and "26 weeks from entry". | |
| SW9 | POST /analyze with trade_type=day unchanged | `POST /analyze {"ticker":"AAPL","trade_type":"day"}` | is_swing=false. Intraday bars used. Day trade agent prompt unchanged. | |

### Frontend Swing UI Tests

| # | Feature | Test Steps | Expected Result | Pass/Fail |
|---|---------|------------|-----------------|-----------|
| FE1 | 5-option pill selector visible | Open app on Analyze tab. | Five pill buttons visible: SCALP, DAY, SWING S, SWING M, SWING L. Active = green highlight (#00ff88). Inactive = dark surface. | |
| FE2 | Pill selector sets trade_type | Click SWING S pill. | Pill turns green. POST /analyze sends trade_type="swing_short". | |
| FE3 | TAKE TRADE uses pill value | Select SWING M. Analyze ticker. Click TAKE TRADE. | Trade submitted with trade_type="swing_medium" (not "scalp"). | |
| FE4 | Add Trade form has 5 options | Click + Add Trade. Check trade_type dropdown. | Options: Scalp, Day, Swing S (1-4wk), Swing M (1-3mo), Swing L (3-6mo). | |
| FE5 | Scalp trade card shows correct outcomes | Add scalp trade. Check trade row. | Outcome snapshot row shows: 5m / 10m / 15m / 30m / 1d PnL columns. | |
| FE6 | Swing S trade card shows correct outcomes | Add swing_short trade. Check trade row. | Outcome snapshot row shows: 1d / 3d / 7d / 14d / 30d PnL columns. | |
| FE7 | Swing M trade card shows correct outcomes | swing_medium trade row. | Outcome snapshot row: 7d / 14d / 30d / 60d. | |
| FE8 | Swing L trade card shows correct outcomes | swing_long trade row. | Outcome snapshot row: 14d / 30d / 60d / 90d / 180d. | |
| FE9 | Trend context row on open swing trades | Add swing trade with trend context populated. | Below trade row: DAILY / WEEKLY / MTF / ADX / Updated relative time. Not shown on scalp/day trades. | |
| FE10 | Trend context row absent on scalp | Add scalp trade. | No trend context row below that trade. | |

---

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
