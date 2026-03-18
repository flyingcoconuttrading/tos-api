"""
tests/smoke_test.py
-------------------
Quick smoke test for tos-api endpoints.
Run: python tests/smoke_test.py
Requires API running on localhost:8002.
Completes in < 10 seconds.
"""

import sys
import time
import urllib.request
import urllib.error
import json

BASE = "http://localhost:8002"

results = []


def check(label, fn):
    start = time.time()
    try:
        ok, detail = fn()
        elapsed = time.time() - start
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {label:<45}  {detail}  ({elapsed:.2f}s)")
        results.append(ok)
    except Exception as e:
        elapsed = time.time() - start
        print(f"  FAIL  {label:<45}  ERROR: {e}  ({elapsed:.2f}s)")
        results.append(False)


def get(path, timeout=8):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def post(path, data, timeout=8):
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        BASE + path, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


# ---------------------------------------------------------------------------

print("\ntos-api smoke tests")
print("-" * 60)

check("GET /health - status ok", lambda: (
    (lambda s, b: (s == 200 and b.get("status") == "ok",
                   f"status={b.get('status')}"))(*get("/health"))
))

check("GET /trades - returns list", lambda: (
    (lambda s, b: (s == 200 and isinstance(b, list),
                   f"{len(b)} trades"))(*get("/trades"))
))

check("GET /quote/AAPL - price present", lambda: (
    (lambda s, b: (s == 200 and b.get("price") is not None,
                   f"price={b.get('price')}"))(*get("/quote/AAPL"))
))

check("GET /quote/AAPL - has required keys", lambda: (
    (lambda s, b: (
        all(k in b for k in ("symbol", "price", "bid", "ask", "timestamp")),
        "keys=" + ",".join(
            k for k in ("symbol", "price", "bid", "ask", "timestamp") if k in b
        ),
    ))(*get("/quote/AAPL"))
))

check("GET /logs - returns list with outcome fields", lambda: (
    (lambda s, b: (
        s == 200 and isinstance(b, list),
        f"{len(b)} logs" + (
            f", out_30m_pnl={b[0].get('out_30m_pnl')}" if b else ""
        ),
    ))(*get("/logs?limit=5"))
))

check("GET /logs?ticker=AAPL - filters correctly", lambda: (
    (lambda s, b: (
        s == 200 and all(r.get("ticker") == "AAPL" for r in b),
        f"{len(b)} AAPL logs",
    ))(*get("/logs?ticker=AAPL&limit=5"))
))

check("GET /settings - returns dict", lambda: (
    (lambda s, b: (s == 200 and isinstance(b, dict),
                   f"keys={list(b.keys())}"))(*get("/settings"))
))

check("POST /trades - no target_2 (backward compat)", lambda: (
    (lambda s, b: (s == 200 and "trade_id" in b,
                   f"trade_id={b.get('trade_id')}"))(*post("/trades", {
        "symbol": "SMOKETEST", "direction": "LONG",
        "entry_price": 100.0, "stop": 98.0, "target": 104.0,
        "trade_type": "scalp",
    }))
))

check("POST /trades - with target_2", lambda: (
    (lambda s, b: (s == 200 and "trade_id" in b,
                   f"trade_id={b.get('trade_id')}"))(*post("/trades", {
        "symbol": "SMOKETEST2", "direction": "SHORT",
        "entry_price": 200.0, "stop": 205.0,
        "target": 196.0, "target_2": 192.0,
        "trade_type": "scalp",
    }))
))

check("GET /trades - target_2 field present in schema", lambda: (
    (lambda s, b: (
        s == 200 and isinstance(b, list) and len(b) > 0 and "target_2" in b[0],
        f"target_2={b[0].get('target_2') if b else 'no trades'}",
    ))(*get("/trades?limit=2"))
))

check("GET /stats - required keys present", lambda: (
    (lambda s, b: (
        s == 200 and
        all(k in b for k in ("uptime_seconds", "total_calls", "ai_calls", "endpoints", "unauthorized_ai_calls")),
        f"uptime={b.get('uptime_seconds')}s, total={b.get('total_calls')}, ai={b.get('ai_calls', {}).get('count')}",
    ))(*get("/stats"))
))

check("GET /stats - ai_calls subkeys present", lambda: (
    (lambda s, b: (
        s == 200 and
        all(k in b.get("ai_calls", {}) for k in ("count", "avg_tokens_in", "avg_tokens_out", "total_cost_est")),
        "ai_calls keys=" + str(list(b.get("ai_calls", {}).keys())),
    ))(*get("/stats"))
))

check("GET /logs/report - required keys present", lambda: (
    (lambda s, b: (
        s == 200 and
        all(k in b for k in ("total_analyses", "by_verdict", "by_symbol",
                             "outcome_summary", "by_trade_type", "confidence_buckets")),
        f"total={b.get('total_analyses')}, buckets={len(b.get('confidence_buckets', []))}",
    ))(*get("/logs/report"))
))

check("GET /logs/report - confidence_buckets has 4 entries", lambda: (
    (lambda s, b: (
        s == 200 and len(b.get("confidence_buckets", [])) == 4,
        f"bucket_count={len(b.get('confidence_buckets', []))}",
    ))(*get("/logs/report"))
))

# ---------------------------------------------------------------------------

print("-" * 60)
passed = sum(results)
total = len(results)
label = "PASSED" if passed == total else "FAILED"
print(f"\n{label}: {passed}/{total} tests passed\n")

sys.exit(0 if passed == total else 1)
