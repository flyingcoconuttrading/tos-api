# TODO — tos-api

## Pending Features

- [ ] Watchlist functionality — auto-surface swing trade candidates from a
      user-defined watchlist of symbols. Poll each symbol on a configurable
      interval, run pre-processor (regime + timing), flag symbols meeting
      entry criteria (near S/R + regime aligned + VIX acceptable).

## Known Gaps / Future Work

- [ ] ENABLE_NEWS: wire in live news feed / economic calendar (currently manual)
- [ ] ENABLE_OPTIONS: GEX calculation once options chain is enabled
- [ ] ENABLE_RTD: WebSocket stream cache (placeholder in collector.py)
- [ ] Discord webhook: POST trade alerts directly instead of clipboard-only
- [ ] Earnings calendar: auto-flag symbols within 5 days of earnings
- [ ] App.jsx port mismatch: frontend references 8001, backend runs on 8002
- [ ] Multi-account support: currently single account_size / risk_percent
- [ ] Backtesting: replay historical bars through agents, compare to outcomes
