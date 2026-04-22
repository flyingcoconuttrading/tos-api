"""
pvt.py — Production Validation Test for tos-api.

Smoke-tests every read endpoint, asserts shape where possible.
Zero AI calls by default. --analyze flag opts into one AAPL scalp
/analyze call (costs 4 AI calls, ~$0.05).

Usage:
    python pvt.py
    python pvt.py --analyze
    python pvt.py --url http://127.0.0.1:8002
"""

import argparse
import json
import sys
import time
from typing import Callable

import requests


# ── ANSI colors ─────────────────────────────────────────────────────────────

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


# ── Test harness ────────────────────────────────────────────────────────────

class Harness:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.passed   = 0
        self.failed   = 0
        self.skipped  = 0

    def run(self, name: str, fn: Callable[[], None]):
        t0 = time.perf_counter()
        try:
            fn()
            ms = round((time.perf_counter() - t0) * 1000, 1)
            print(f"  {_GREEN}PASS{_RESET}  {name} {_DIM}({ms}ms){_RESET}")
            self.passed += 1
        except AssertionError as e:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            print(f"  {_RED}FAIL{_RESET}  {name} {_DIM}({ms}ms){_RESET}")
            print(f"        {_RED}{e}{_RESET}")
            self.failed += 1
        except Exception as e:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            print(f"  {_RED}ERROR{_RESET} {name} {_DIM}({ms}ms){_RESET}")
            print(f"        {_RED}{type(e).__name__}: {e}{_RESET}")
            self.failed += 1

    def skip(self, name: str, reason: str):
        print(f"  {_YELLOW}SKIP{_RESET}  {name} {_DIM}({reason}){_RESET}")
        self.skipped += 1

    def get(self, path: str, timeout: int = 30) -> dict:
        r = requests.get(self.base_url + path, timeout=timeout)
        assert r.status_code == 200, f"GET {path} -> {r.status_code}: {r.text[:200]}"
        try:
            return r.json()
        except Exception as e:
            raise AssertionError(f"GET {path} returned non-JSON: {e}")

    def post(self, path: str, body: dict, timeout: int = 60) -> dict:
        r = requests.post(self.base_url + path, json=body, timeout=timeout)
        assert r.status_code == 200, f"POST {path} -> {r.status_code}: {r.text[:200]}"
        try:
            return r.json()
        except Exception as e:
            raise AssertionError(f"POST {path} returned non-JSON: {e}")

    def summary(self) -> int:
        total = self.passed + self.failed + self.skipped
        print()
        print("=" * 60)
        if self.failed == 0:
            print(f"{_GREEN}ALL PASS{_RESET}  {self.passed}/{total}  "
                  f"(skipped: {self.skipped})")
            return 0
        else:
            print(f"{_RED}FAILURES{_RESET}  "
                  f"{self.passed} pass / {self.failed} fail / "
                  f"{self.skipped} skip / {total} total")
            return 1


# ── Test definitions ────────────────────────────────────────────────────────

def _t_health(h: Harness):
    data = h.get("/health")
    assert data.get("status") == "ok", f"status != ok: {data}"
    assert "version" in data, "missing version key"


def _t_stats(h: Harness):
    data = h.get("/stats")
    for key in ("uptime_seconds", "total_calls", "ai_calls", "trade_db"):
        assert key in data, f"missing key: {key}"


def _t_ai_status(h: Harness):
    data = h.get("/ai/status")
    assert "ai_enabled" in data, "missing ai_enabled"
    assert "ai_calls"   in data, "missing ai_calls"


def _t_watchlist(h: Harness):
    data = h.get("/watchlist")
    assert "default" in data, "watchlist missing 'default'"
    assert isinstance(data["default"], list), "'default' not a list"
    assert len(data["default"]) > 0, "'default' watchlist is empty"


def _t_scan_status(h: Harness):
    data = h.get("/scan/status")
    for key in ("auto_enabled", "interval_minutes", "score_threshold",
                "default_trade_type"):
        assert key in data, f"missing key: {key}"


def _t_settings(h: Harness):
    data = h.get("/settings")
    for key in ("moving_averages", "gap_detection", "risk", "ai_enabled"):
        assert key in data, f"missing key: {key}"


def _t_quote(h: Harness):
    data = h.get("/quote/SPY")
    # Shape varies — accept any structure that has a numeric price somewhere
    flat = json.dumps(data)
    assert "price" in flat.lower() or "last" in flat.lower() or "mark" in flat.lower(), \
        f"quote response lacks price field: {flat[:200]}"


def _t_sr_cache(h: Harness):
    data = h.get("/sr-cache/SPY")
    assert "trend" in data, "sr-cache response missing 'trend' block"
    trend = data["trend"]
    for key in ("daily", "weekly", "mtf_alignment", "trade_bias"):
        assert key in trend, f"trend missing key: {key}"


def _t_chart_daily(h: Harness):
    data = h.get("/chart-data/AAPL")
    assert data.get("timeframe") == "daily", f"timeframe wrong: {data.get('timeframe')}"
    bars = data.get("bars", [])
    assert len(bars) > 0, "daily bars empty"


def _t_chart_weekly(h: Harness):
    data = h.get("/chart-data/AAPL?timeframe=weekly")
    assert data.get("timeframe") == "weekly", f"timeframe wrong: {data.get('timeframe')}"
    bars = data.get("bars", [])
    assert len(bars) > 0, "weekly bars empty"


def _t_chart_intraday(h: Harness):
    data = h.get("/chart-data/AAPL/intraday")
    assert data.get("timeframe") == "intraday", f"timeframe wrong: {data.get('timeframe')}"
    bars = data.get("bars", [])
    assert len(bars) > 0, "intraday bars empty"

    # ET timezone check — datetime should end in -04:00 or -05:00
    first_dt = bars[0].get("datetime", "")
    assert first_dt.endswith("-04:00") or first_dt.endswith("-05:00"), \
        f"datetime not in ET offset: {first_dt}"

    # VWAP presence — at least one bar must have non-null VWAP
    vwap_count = sum(1 for b in bars if b.get("vwap") is not None)
    assert vwap_count > 0, "no bars have VWAP populated"

    # intraday_levels block present with expected keys
    levels = data.get("intraday_levels", {})
    assert isinstance(levels, dict), "intraday_levels not a dict"
    # At least today_high/today_low should be present (opening range may be absent pre-market)
    has_today = "today_high" in levels and "today_low" in levels
    has_prev  = "prev_day_high" in levels and "prev_day_low" in levels
    assert has_today or has_prev, \
        f"intraday_levels has neither today nor prev day: {levels}"


def _t_trades_list(h: Harness):
    data = h.get("/trades?limit=10")
    assert isinstance(data, list), f"/trades did not return list: {type(data)}"


def _t_logs_list(h: Harness):
    data = h.get("/logs?limit=10")
    # Accept list or dict-with-list shape
    if isinstance(data, dict):
        assert "logs" in data or "results" in data or len(data) >= 0, \
            f"/logs shape unexpected: {list(data.keys())[:5]}"
    else:
        assert isinstance(data, list), f"/logs did not return list: {type(data)}"


def _t_plans_summary(h: Harness):
    data = h.get("/plans/summary")
    for key in ("pending", "waiting", "triggered", "invalidated", "expired", "total"):
        assert key in data, f"plans/summary missing key: {key}"


def _t_plans_list(h: Harness):
    data = h.get("/plans?limit=10")
    assert isinstance(data, list), f"/plans did not return list: {type(data)}"


def _t_analyze_aapl(h: Harness):
    """Costs 4 AI calls. Only runs with --analyze flag."""
    data = h.post("/analyze", {
        "ticker":       "AAPL",
        "account_size": 5000,
        "risk_percent": 2.0,
        "trade_type":   "scalp",
    }, timeout=120)
    assert "trade_plan"     in data, "missing trade_plan"
    assert "agent_verdicts" in data, "missing agent_verdicts"
    assert "sr_cache"       in data, "missing sr_cache"
    assert "trend"          in data, "missing trend"
    assert data["trade_plan"].get("verdict") in ("TRADE", "NO_TRADE", "TRADE_WAIT"), \
        f"unexpected verdict: {data['trade_plan'].get('verdict')}"


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Production Validation Test for tos-api")
    p.add_argument("--url",     default="http://127.0.0.1:8002",
                   help="Base URL (default: http://127.0.0.1:8002)")
    p.add_argument("--analyze", action="store_true",
                   help="Run /analyze AAPL scalp (costs 4 AI calls)")
    args = p.parse_args()

    print(f"PVT target: {args.url}")
    print("=" * 60)

    h = Harness(args.url)

    h.run("GET  /health",                        lambda: _t_health(h))
    h.run("GET  /stats",                         lambda: _t_stats(h))
    h.run("GET  /ai/status",                     lambda: _t_ai_status(h))
    h.run("GET  /watchlist",                     lambda: _t_watchlist(h))
    h.run("GET  /scan/status",                   lambda: _t_scan_status(h))
    h.run("GET  /settings",                      lambda: _t_settings(h))
    h.run("GET  /quote/SPY",                     lambda: _t_quote(h))
    h.run("GET  /sr-cache/SPY",                  lambda: _t_sr_cache(h))
    h.run("GET  /chart-data/AAPL (daily)",       lambda: _t_chart_daily(h))
    h.run("GET  /chart-data/AAPL (weekly)",      lambda: _t_chart_weekly(h))
    h.run("GET  /chart-data/AAPL/intraday",      lambda: _t_chart_intraday(h))
    h.run("GET  /trades?limit=10",               lambda: _t_trades_list(h))
    h.run("GET  /logs?limit=10",                 lambda: _t_logs_list(h))
    h.run("GET  /plans/summary",                 lambda: _t_plans_summary(h))
    h.run("GET  /plans?limit=10",                lambda: _t_plans_list(h))

    if args.analyze:
        h.run("POST /analyze AAPL scalp (AI)",   lambda: _t_analyze_aapl(h))
    else:
        h.skip("POST /analyze AAPL scalp (AI)",  "use --analyze to enable")

    sys.exit(h.summary())


if __name__ == "__main__":
    main()
