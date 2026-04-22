"""
main.py — Stock Pick Checker API
Run: uvicorn main:app --reload --port 8002
"""

# Silence pandas datetime .round() warnings BEFORE pandas imports
import warnings
warnings.filterwarnings(
    "ignore",
    message=".*obj.round has no effect with datetime.*",
)

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import shutil
import checker
import settings as _settings
import discord_export
import swing_tracker
from data import trade_store_duck as trade_store
from data.collector import _get_quote           # re-used by price watcher
from db.database import init_db, get_logs, update_outcome, update_log_outcome, get_unresolved_logs, get_report
from db.duckdb_manager import init_schema, fetch_one
from agents.base_agent import get_token_stats
from config import DEFAULT_ACCOUNT_SIZE, DEFAULT_RISK_PERCENT
from utils import get_price, is_market_hours
from screener import score_ticker
import json as _json

from log_config import get_logger
from data import plan_store
from notifications import send_plan_alert
import plan_validator

logger = get_logger("main")

# ── In-memory request counters (reset on restart) ────────────────────────────
_startup_time = time.time()
_req_counters: dict = {
    "total_calls":           0,
    "endpoints":             {},
    "unauthorized_ai_calls": 0,
}

app = FastAPI(
    title="Stock Pick Checker",
    description="AI-powered day trading analysis via multi-agent system",
    version="2.10.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request counter middleware ────────────────────────────────────────────────

@app.middleware("http")
async def _count_requests(request: Request, call_next):
    # Normalize /quote/AAPL → /quote, /trades/5/close → /trades, etc.
    first_segment = "/" + request.url.path.strip("/").split("/")[0]
    _req_counters["total_calls"] += 1
    _req_counters["endpoints"][first_segment] = (
        _req_counters["endpoints"].get(first_segment, 0) + 1
    )
    t0 = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - t0) * 1000, 1)
    logger.info(
        "%s %s -> %d (%sms)",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


# ── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    # Rename legacy SQLite trades.db if present
    legacy_path  = Path("data/trades.db")
    renamed_path = Path("data/trades_legacy.db")
    if legacy_path.exists() and not renamed_path.exists():
        shutil.move(str(legacy_path), str(renamed_path))
        logger.info("[Migration] trades.db renamed to trades_legacy.db (read-only archive)")

    init_schema()           # DuckDB   — main data store
    init_db()               # PostgreSQL — analysis logs

    # Ensure scan settings exist
    _s = _settings.load()
    if "scan" not in _s:
        _s["scan"] = {
            "auto_enabled": False, "interval_minutes": 5,
            "score_threshold": 60, "concurrency_limit": 5,
            "default_trade_type": "day", "last_run": None,
        }
    if "plan_validity" not in _s:
        _s["plan_validity"] = {
            "vwap_break_threshold_pct":    0.30,
            "sr_break_threshold_pct":      0.20,
            "direction_flip_atr_multiple": 2.0,
            "entry_blown_pct":             0.50,
        }
    _settings.save(_s)
    asyncio.create_task(_price_watcher())
    asyncio.create_task(_session_checker())
    asyncio.create_task(_plan_checker())


# ── Background tasks ─────────────────────────────────────────────────────────

async def _price_watcher():
    """Every 30 s: check all open trades against live price; fill analysis log outcomes."""
    while True:
        try:
            await asyncio.to_thread(_check_open_trades)
            await asyncio.to_thread(_check_log_outcomes)
        except Exception:
            logger.exception("[PriceWatcher]")
        await asyncio.sleep(30)


def _check_open_trades():
    for trade in trade_store.get_open_trades():
        try:
            quote  = _get_quote(trade["symbol"])
            price  = get_price(quote)
            if not price:
                continue
            # Record timed interval snapshots for scalp trades
            trade_store.check_scalp_intervals(trade, price)
            # Auto-close if stop or target is hit
            reason = trade_store.check_price_trigger(trade, price)
            if reason == "TARGET_1":
                trade_store.record_target1_hit(trade["trade_id"], price)
                logger.info("[PriceWatcher] %s TARGET_1 hit @ %s — watching for T2", trade["symbol"], price)
            elif reason:
                trade_store.close_trade(trade["trade_id"], price, reason)
                logger.info("[PriceWatcher] %s auto-closed: %s @ %s", trade["symbol"], reason, price)
        except Exception:
            logger.exception("[PriceWatcher] %s", trade.get("symbol"))


def _check_log_outcomes():
    """Fill in 5m/15m/30m/1d price snapshots for recent TRADE analysis logs."""
    try:
        logs = get_unresolved_logs()
    except Exception:
        logger.exception("[LogOutcomes] DB error")
        return

    now_utc = datetime.now(timezone.utc)
    for log in logs:
        try:
            created = log["created_at"]
            # psycopg2 returns tz-aware datetime
            if hasattr(created, "utcoffset"):
                elapsed_min = (now_utc - created).total_seconds() / 60
            else:
                elapsed_min = (datetime.now() - created).total_seconds() / 60

            quote = _get_quote(log["ticker"])
            price = get_price(quote)
            if not price:
                continue

            if elapsed_min >= 5   and log.get("out_5m_price")  is None:
                update_log_outcome(log["id"], "5m",  price)
            if elapsed_min >= 15  and log.get("out_15m_price") is None:
                update_log_outcome(log["id"], "15m", price)
            if elapsed_min >= 30  and log.get("out_30m_price") is None:
                update_log_outcome(log["id"], "30m", price)
            if elapsed_min >= 1440 and log.get("out_1d_price") is None:
                update_log_outcome(log["id"], "1d",  price)
        except Exception:
            logger.exception("[LogOutcomes] %s", log.get("ticker"))


def _session_checker_body():
    """Sync body — runs in thread via asyncio.to_thread()."""
    swing_tracker.log_session_price(_get_quote)
    swing_tracker.check_multi_day_outcomes(_get_quote)

    open_trades = trade_store.get_open_trades()
    for t in open_trades:
        tt = t.get("trade_type", "")
        if tt in ("swing_short", "swing_medium", "swing_long"):
            try:
                quote = _get_quote(t["symbol"])
                price = get_price(quote)
                if price:
                    trade_store.check_swing_intervals(t, price)
                    last_update = t.get("last_trend_update")
                    needs_update = True
                    if last_update:
                        if isinstance(last_update, str):
                            last_update = datetime.fromisoformat(last_update)
                        needs_update = (
                            (datetime.now(timezone.utc).replace(tzinfo=None)
                             - last_update).total_seconds() > 86400
                        )
                    if needs_update:
                        from trend_analysis import get_trend
                        trend = get_trend(t["symbol"])
                        trade_store.update_trend_snapshot(
                            t["trade_id"], trend
                        )
            except Exception:
                logger.exception("[SessionChecker] swing %s", t.get("symbol"))


async def _session_checker():
    """Every 60 s: log session boundary prices for open swing trades,
    check multi-day outcome milestones, and update swing trend snapshots."""
    await asyncio.sleep(5)  # wait for schema init to complete
    while True:
        try:
            await asyncio.to_thread(_session_checker_body)
        except Exception:
            logger.exception("[SessionChecker]")
        await asyncio.sleep(60)


async def _plan_checker():
    """Every 2 min during market hours: validate pending/waiting plans."""
    await asyncio.sleep(10)  # let startup settle
    while True:
        try:
            if is_market_hours():
                await asyncio.to_thread(_check_plans_sync)
        except Exception:
            logger.exception("[PlanChecker]")
        await asyncio.sleep(120)


def _check_plans_sync():
    """Sync body — runs in thread. Check all active plans against live prices."""
    from utils import is_market_hours as _imh
    plans = plan_store.get_active_plans()
    if not plans:
        return

    # Batch quotes — get unique tickers first
    tickers = list({p["ticker"] for p in plans})
    prices  = {}
    for t in tickers:
        try:
            q = _get_quote(t)
            p = get_price(q)
            if p:
                prices[t] = p
        except Exception:
            logger.warning("[PlanChecker] quote failed for %s", t)

    for plan in plans:
        ticker = plan["ticker"]
        price  = prices.get(ticker)
        if not price:
            continue

        plan_id = plan["plan_id"]
        status  = plan["status"]

        try:
            if status == "WAITING":
                new_status, reason = plan_validator.evaluate_waiting_plan(plan, price)
            else:  # PENDING or TRIGGERED
                new_status, reason = plan_validator.validate_plan(plan, price)

            if new_status:
                plan_store.update_plan_status(plan_id, new_status, reason, price)
                updated = plan_store.get_plan(plan_id)
                send_plan_alert(updated, new_status.lower())
                logger.info(
                    "[PlanChecker] plan %d %s → %s (%s) @ %.2f",
                    plan_id, ticker, new_status, reason, price
                )
            else:
                plan_store.touch_plan(plan_id)
        except Exception:
            logger.exception("[PlanChecker] plan %d %s", plan_id, ticker)


# ── Models ───────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    ticker:       str
    account_size: float = DEFAULT_ACCOUNT_SIZE
    risk_percent: float = DEFAULT_RISK_PERCENT
    trade_type:   str   = "day"   # "day" or "swing"

class OutcomeUpdate(BaseModel):
    outcome:       str
    outcome_price: Optional[float] = None
    notes:         Optional[str]   = None

class TradeCreate(BaseModel):
    symbol:        str
    direction:     str              # LONG / SHORT
    entry_price:   float
    stop:          float
    target:        float
    target_2:      Optional[float] = None
    trade_type:    str  = "scalp"   # scalp / day / swing_short / swing_medium / swing_long
    notes:         Optional[str] = ""
    source_plan_id: Optional[int] = None   # link back to pending_plans

class TradeClose(BaseModel):
    exit_price:  float
    exit_reason: str = "MANUAL"   # STOP / TARGET / MANUAL / EXPIRED

class SettingsUpdate(BaseModel):
    moving_averages: Optional[dict] = None
    gap_detection:   Optional[dict] = None
    risk:            Optional[dict] = None
    scan:            Optional[dict] = None


# ── Analysis endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.10.0"}


@app.get("/stats")
def stats():
    """In-memory API usage counters — resets on server restart."""
    tok = get_token_stats()
    ai_calls   = tok["total_calls"]
    tokens_in  = tok["total_tokens_in"]
    tokens_out = tok["total_tokens_out"]
    avg_in  = round(tokens_in  / ai_calls, 1) if ai_calls else 0
    avg_out = round(tokens_out / ai_calls, 1) if ai_calls else 0
    cost_est = round(tokens_in * 3e-6 + tokens_out * 15e-6, 4)
    duck = fetch_one(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open_count, "
        "SUM(CASE WHEN closed_at IS NOT NULL THEN 1 ELSE 0 END) as closed "
        "FROM trades"
    ) or {}
    return {
        "uptime_seconds":        round(time.time() - _startup_time),
        "total_calls":           _req_counters["total_calls"],
        "ai_calls": {
            "count":          ai_calls,
            "avg_tokens_in":  avg_in,
            "avg_tokens_out": avg_out,
            "total_cost_est": cost_est,
        },
        "endpoints":             dict(_req_counters["endpoints"]),
        "unauthorized_ai_calls": _req_counters["unauthorized_ai_calls"],
        "trade_db": {
            "engine":       "duckdb",
            "total_trades": duck.get("total", 0),
            "open":         duck.get("open_count", 0),
            "closed":       duck.get("closed", 0),
        },
    }


@app.get("/logs/report")
def logs_report():
    """Aggregate analysis log statistics."""
    try:
        return get_report()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ai/status")
def ai_status():
    return {
        "ai_enabled": _settings.get_ai_enabled(),
        "ai_calls":   _settings.get_ai_calls(),
    }


@app.post("/ai/toggle")
def ai_toggle():
    _settings.set_ai_enabled(not _settings.get_ai_enabled())
    return {
        "ai_enabled": _settings.get_ai_enabled(),
        "ai_calls":   _settings.get_ai_calls(),
    }


@app.post("/ai/reset-counter")
def ai_reset_counter():
    _settings.reset_session_counter()
    return {"message": "Session counter reset.", "ai_calls": _settings.get_ai_calls()}


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
        _settings.increment_ai_calls()

        # Auto-create pending plan on TRADE or TRADE_WAIT verdict
        verdict = result.get("trade_plan", {}).get("verdict")
        if verdict in ("TRADE", "TRADE_WAIT"):
            try:
                plan_id = plan_store.insert_plan(
                    result, analysis_log_id=result.get("log_id")
                )
                result["plan_id"] = plan_id
                if plan_id:
                    new_plan = plan_store.get_plan(plan_id)
                    if new_plan:
                        send_plan_alert(new_plan, "created")
                        logger.info(
                            "[Analyze] plan %d created for %s verdict=%s",
                            plan_id, req.ticker, verdict
                        )
            except Exception:
                logger.exception("[Analyze] plan auto-create failed for %s", req.ticker)

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Analysis log endpoints (PostgreSQL) ──────────────────────────────────────

@app.get("/logs")
def logs(
    ticker:  Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    limit:   int           = Query(50, le=200),
):
    return get_logs(ticker=ticker, outcome=outcome, limit=limit)


@app.patch("/logs/{log_id}/outcome")
def patch_outcome(log_id: int, body: OutcomeUpdate):
    update_outcome(log_id, body.outcome, body.outcome_price, body.notes)
    return {"status": "updated", "id": log_id}


# ── Plan validity endpoints ───────────────────────────────────────────────────

@app.get("/plans")
def list_plans(
    status: Optional[str] = Query(None),
    limit:  int           = Query(100, le=500),
):
    """List pending plans. Filter by status: PENDING, WAITING, TRIGGERED, INVALIDATED, EXPIRED, ABANDONED."""
    return plan_store.get_all_plans(limit=limit, status=status)


@app.get("/plans/summary")
def plans_summary():
    """Count of plans by status."""
    return plan_store.get_plan_summary()


@app.get("/plans/{plan_id}")
def get_plan(plan_id: int):
    p = plan_store.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    return p


@app.post("/plans/{plan_id}/check")
def manual_check_plan(plan_id: int):
    """Manually run validity rules now (works off-hours)."""
    p = plan_store.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    if p["status"] not in ("PENDING", "WAITING", "TRIGGERED"):
        return {"plan_id": plan_id, "status": p["status"], "message": "Plan already resolved"}

    ticker = p["ticker"]
    try:
        q     = _get_quote(ticker)
        price = get_price(q)
        if not price:
            return {"plan_id": plan_id, "error": "Could not fetch quote"}

        if p["status"] == "WAITING":
            new_status, reason = plan_validator.evaluate_waiting_plan(p, price)
        else:
            new_status, reason = plan_validator.validate_plan(p, price)

        if new_status:
            plan_store.update_plan_status(plan_id, new_status, reason, price)
            updated = plan_store.get_plan(plan_id)
            send_plan_alert(updated, new_status.lower())
            return {"plan_id": plan_id, "status": new_status, "reason": reason, "price": price}
        else:
            plan_store.touch_plan(plan_id)
            return {"plan_id": plan_id, "status": p["status"], "message": "Still valid", "price": price}
    except Exception as e:
        logger.exception("[Plans] manual check failed plan %d", plan_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/plans/{plan_id}/invalidate")
def manual_invalidate_plan(plan_id: int, reason: str = Query("MANUAL_INVALIDATE")):
    """Force-invalidate a plan."""
    p = plan_store.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan_store.update_plan_status(plan_id, "INVALIDATED", reason)
    updated = plan_store.get_plan(plan_id)
    send_plan_alert(updated, "invalidated")
    return {"plan_id": plan_id, "status": "INVALIDATED", "reason": reason}


@app.get("/plans/{plan_id}/replay")
def replay_plan(plan_id: int):
    """
    Backtest replay: fetch 1-min bars from plan creation forward,
    simulate fills/exits using stored plan levels.
    Returns simulated outcome JSON for UI replay visualizer.
    """
    p = plan_store.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan not found")

    ticker     = p["ticker"]
    entry_low  = p.get("entry_low")
    entry_high = p.get("entry_high")
    stop_loss  = p.get("stop_loss")
    target_1   = p.get("target_1")
    target_2   = p.get("target_2")
    direction  = str(p.get("direction", "")).upper()
    created_at = p.get("created_at", "")

    try:
        from data.collector import _get_intraday
        import pandas as pd

        df = _get_intraday(ticker)
        if df.empty:
            return {"plan_id": plan_id, "error": "No intraday data available"}

        # Convert to ET, filter from plan creation time
        if df["datetime"].dt.tz is None:
            df["datetime"] = df["datetime"].dt.tz_localize("UTC")
        df["datetime"] = df["datetime"].dt.tz_convert("America/New_York")

        try:
            created_dt = pd.Timestamp(created_at).tz_convert("America/New_York")
        except Exception:
            created_dt = df["datetime"].iloc[0]

        replay_df = df[df["datetime"] >= created_dt].copy()
        if replay_df.empty:
            return {"plan_id": plan_id, "error": "No bars after plan creation time"}

        # Simulate fill/exit bar by bar
        filled      = False
        fill_price  = None
        fill_time   = None
        exit_price  = None
        exit_time   = None
        exit_reason = None
        t1_hit      = False
        pnl_pct     = None
        bars_out    = []

        for _, row in replay_df.iterrows():
            bar = {
                "datetime": row["datetime"].isoformat(),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low":  round(float(row["low"]),  4),
                "close": round(float(row["close"]), 4),
                "volume": int(row.get("volume", 0)),
                "filled": False,
                "exit": False,
                "exit_reason": None,
            }

            if not filled:
                # Check for fill in this bar
                if entry_low and entry_high:
                    if direction == "LONG" and row["low"] <= entry_high:
                        filled     = True
                        fill_price = max(entry_low, float(row["open"]))
                        fill_time  = row["datetime"].isoformat()
                        bar["filled"] = True
                    elif direction == "SHORT" and row["high"] >= entry_low:
                        filled     = True
                        fill_price = min(entry_high, float(row["open"]))
                        fill_time  = row["datetime"].isoformat()
                        bar["filled"] = True
            else:
                # Check stop/target
                if direction == "LONG":
                    if stop_loss and row["low"] <= stop_loss:
                        exit_price  = stop_loss
                        exit_time   = row["datetime"].isoformat()
                        exit_reason = "STOP"
                        bar["exit"] = True
                        bar["exit_reason"] = "STOP"
                    elif not t1_hit and target_1 and row["high"] >= target_1:
                        if not target_2:
                            exit_price  = target_1
                            exit_time   = row["datetime"].isoformat()
                            exit_reason = "TARGET_1"
                            bar["exit"] = True
                            bar["exit_reason"] = "TARGET_1"
                        else:
                            t1_hit = True
                            bar["exit_reason"] = "TARGET_1_HIT"
                    elif t1_hit and target_2 and row["high"] >= target_2:
                        exit_price  = target_2
                        exit_time   = row["datetime"].isoformat()
                        exit_reason = "TARGET_2"
                        bar["exit"] = True
                        bar["exit_reason"] = "TARGET_2"
                elif direction == "SHORT":
                    if stop_loss and row["high"] >= stop_loss:
                        exit_price  = stop_loss
                        exit_time   = row["datetime"].isoformat()
                        exit_reason = "STOP"
                        bar["exit"] = True
                        bar["exit_reason"] = "STOP"
                    elif not t1_hit and target_1 and row["low"] <= target_1:
                        if not target_2:
                            exit_price  = target_1
                            exit_time   = row["datetime"].isoformat()
                            exit_reason = "TARGET_1"
                            bar["exit"] = True
                            bar["exit_reason"] = "TARGET_1"
                        else:
                            t1_hit = True
                            bar["exit_reason"] = "TARGET_1_HIT"
                    elif t1_hit and target_2 and row["low"] <= target_2:
                        exit_price  = target_2
                        exit_time   = row["datetime"].isoformat()
                        exit_reason = "TARGET_2"
                        bar["exit"] = True
                        bar["exit_reason"] = "TARGET_2"

            bars_out.append(bar)
            if bar.get("exit"):
                break

        # Compute P&L
        if filled and fill_price and exit_price:
            raw = (exit_price - fill_price) / fill_price * 100
            pnl_pct = round(raw if direction == "LONG" else -raw, 4)
        elif filled and not exit_price:
            exit_reason = "STILL_OPEN"

        return {
            "plan_id":      plan_id,
            "ticker":       ticker,
            "direction":    direction,
            "entry_zone":   {"low": entry_low, "high": entry_high},
            "stop_loss":    stop_loss,
            "target_1":     target_1,
            "target_2":     target_2,
            "created_at":   created_at,
            "filled":       filled,
            "fill_price":   fill_price,
            "fill_time":    fill_time,
            "exit_price":   exit_price,
            "exit_time":    exit_time,
            "exit_reason":  exit_reason,
            "pnl_pct":      pnl_pct,
            "bars":         bars_out,
        }

    except Exception as e:
        logger.exception("[Plans] replay failed plan %d", plan_id)
        raise HTTPException(status_code=500, detail=str(e))


# ── Trade tracker endpoints ───────────────────────────────────────────────────

@app.get("/quote/{ticker}")
def get_quote_endpoint(ticker: str):
    """Returns live price quote for a ticker symbol."""
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    quote = _get_quote(ticker)
    price = get_price(quote)
    if not price:
        raise HTTPException(status_code=503, detail="Price unavailable")
    return {
        "symbol":    ticker,
        "price":     price,
        "bid":       quote.get("bid"),
        "ask":       quote.get("ask"),
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/historical/{symbol}")
async def get_historical(
    symbol: str,
    timeframe: str = "1d",
    days: int = 30,
):
    """Return cached historical bars for symbol from local store."""
    from data.historical_store import get_bars
    from datetime import datetime, timedelta
    import time
    from_ts = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
    bars = get_bars(symbol.upper(), timeframe, from_ts=from_ts)
    return {
        "symbol":    symbol.upper(),
        "timeframe": timeframe,
        "bars":      bars,
        "count":     len(bars),
    }


@app.get("/backfill/status")
async def backfill_status():
    """Return historical backfill status."""
    from data.historical_store import get_backfill_status, bar_count
    status = get_backfill_status()
    counts = {}
    for sym in ["SPY", "QQQ", "IWM"]:
        counts[sym] = {"1d": bar_count(sym, "1d"), "1m": bar_count(sym, "1m")}
    return {"backfill_log": status, "bar_counts": counts}


@app.post("/trades")
def create_trade(body: TradeCreate):
    """Manually enter a trade for live tracking."""
    trend_ctx = None
    try:
        from trend_analysis import get_trend
        trend_ctx = get_trend(body.symbol)
    except Exception:
        pass
    tid = trade_store.insert_trade(
        symbol=body.symbol,
        direction=body.direction,
        entry_price=body.entry_price,
        stop=body.stop,
        target=body.target,
        target_2=body.target_2,
        trade_type=body.trade_type,
        notes=body.notes or "",
        trend_context=trend_ctx,
    )
    # Link trade back to originating plan if provided
    if body.source_plan_id:
        try:
            plan_store.link_trade(body.source_plan_id, tid)
            logger.info("[Trades] plan %d linked to trade %d", body.source_plan_id, tid)
        except Exception:
            logger.warning("[Trades] plan link failed: plan=%s trade=%d",
                           body.source_plan_id, tid)
    return {"trade_id": tid, "status": "OPEN"}


@app.get("/trades")
def list_trades(
    status: Optional[str] = Query(None),
    limit:  int           = Query(100, le=500),
):
    trades = trade_store.get_all_trades(limit=limit)
    if status:
        trades = [t for t in trades if t.get("status", "").upper() == status.upper()]
    return trades


@app.get("/trades/{trade_id}")
def get_trade(trade_id: int):
    t = trade_store.get_trade(trade_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    return t


@app.patch("/trades/{trade_id}/close")
def close_trade(trade_id: int, body: TradeClose):
    t = trade_store.get_trade(trade_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade_store.close_trade(trade_id, body.exit_price, body.exit_reason)
    return {"trade_id": trade_id, "status": "closed"}


@app.patch("/trades/{trade_id}/status")
def set_trade_status(trade_id: int, status: str = Query(...)):
    t = trade_store.get_trade(trade_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade_store.update_status(trade_id, status.upper())
    return {"trade_id": trade_id, "status": status.upper()}


# ── Discord / clipboard export ────────────────────────────────────────────────

@app.get("/trades/{trade_id}/discord")
def trade_discord(trade_id: int):
    """Returns formatted Discord-ready trade summary string."""
    t = trade_store.get_trade(trade_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trade not found")
    text = discord_export.format_trade(t)
    return {"trade_id": trade_id, "formatted": text}


# ── Settings endpoints ────────────────────────────────────────────────────────

@app.get("/settings")
def get_settings():
    return _settings.load()


@app.put("/settings")
def put_settings(body: SettingsUpdate):
    current = _settings.load()
    if body.moving_averages is not None:
        current["moving_averages"] = body.moving_averages
    if body.gap_detection is not None:
        current["gap_detection"] = body.gap_detection
    if body.risk is not None:
        current["risk"] = body.risk
    if body.scan is not None:
        current.setdefault("scan", {}).update(body.scan)
    _settings.save(current)
    return {"status": "saved", "settings": current}


# ── Settings UI ───────────────────────────────────────────────────────────────

@app.get("/settings-ui", response_class=FileResponse)
def settings_ui():
    import pathlib
    p = pathlib.Path(__file__).parent / "settings.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="settings.html not found")
    return FileResponse(str(p))


@app.get("/sr-cache/{ticker}")
def get_sr_cache(ticker: str):
    from sr_levels import get_levels
    from trend_analysis import get_trend
    ticker = ticker.upper()
    sr     = get_levels(ticker)
    trend  = get_trend(ticker)
    return {**sr, "trend": trend}


@app.post("/sr-cache/refresh/{ticker}")
def refresh_sr_cache(ticker: str):
    from sr_levels import refresh_cache
    return refresh_cache(ticker.upper())


# ── Watchlist endpoints ───────────────────────────────────────────────────────

WATCHLIST_PATH = Path("data/watchlists.json")

@app.get("/watchlist")
def get_watchlist():
    if WATCHLIST_PATH.exists():
        return _json.loads(WATCHLIST_PATH.read_text())
    return {"default": []}

@app.put("/watchlist")
def put_watchlist(body: dict):
    for name, tickers in body.items():
        if not isinstance(tickers, list) or len(tickers) > 50:
            raise HTTPException(status_code=400,
                detail=f"List '{name}' must be array of max 50 tickers")
    WATCHLIST_PATH.parent.mkdir(exist_ok=True)
    WATCHLIST_PATH.write_text(_json.dumps(body, indent=2))
    return body


# ── Scanner endpoints ─────────────────────────────────────────────────────────

_scan_bar_cache: dict = {}
_auto_scan_task = None
_last_scan_results: dict = {}


async def _fetch_bars_for_scan(ticker: str, trade_type: str) -> list:
    """Fetch OHLCV bars from Schwab for screener. Caches result."""
    from data.collector import _get_daily, _get_daily_extended, _get_weekly
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    _ex = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_event_loop()

    try:
        is_swing = trade_type in ("swing_short", "swing_medium", "swing_long")
        if is_swing:
            period_years = 1 if trade_type == "swing_short" else 2
        else:
            period_years = 1  # day/scalp also needs 1 year for screener MIN_BARS=45
        df = await loop.run_in_executor(_ex, _get_daily_extended, ticker, period_years)

        if df.empty:
            return []
        cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        bars = df[cols].round(4).to_dict("records")
        _scan_bar_cache[ticker] = bars
        return bars
    except Exception:
        logger.exception("[Scanner] %s bar fetch error", ticker)
        return []


class ScanRequest(BaseModel):
    trade_type: str = "day"
    list_name:  str = "default"

class ScanConfirmRequest(BaseModel):
    trade_type: str = "day"
    list_name:  str = "default"
    confirmed:  bool = True


async def _run_scan(trade_type: str, list_name: str,
                    skip_ai_warning: bool = False) -> dict:
    """Core scan logic — Stage 1 algo only, Stage 2 technical agent on survivors."""
    from datetime import datetime as _dt
    import asyncio

    wl = get_watchlist()
    tickers = wl.get(list_name)
    if tickers is None:
        raise HTTPException(status_code=400, detail=f"Watchlist '{list_name}' not found")

    s          = _settings.load()
    threshold  = s.get("scan", {}).get("score_threshold", 60)
    concurrency = s.get("scan", {}).get("concurrency_limit", 5)

    _scan_bar_cache.clear()
    sem = asyncio.Semaphore(concurrency)

    # Stage 1 — algo screening (zero AI)
    async def _score_one(ticker):
        async with sem:
            bars = await _fetch_bars_for_scan(ticker, trade_type)
            result = score_ticker(bars, trade_type, threshold)
            return {"ticker": ticker, **result}

    stage1 = await asyncio.gather(*[_score_one(t) for t in tickers])
    survivors = [r for r in stage1 if r.get("passed")]
    survivors.sort(key=lambda x: x.get("score", 0), reverse=True)

    # AI cost warning
    if len(survivors) > 15 and not skip_ai_warning:
        return {
            "requires_confirmation": True,
            "survivor_count":        len(survivors),
            "message": (
                f"{len(survivors)} tickers passed screening. "
                f"This will use {len(survivors)} AI calls. "
                f"POST /scan/confirm with the same body to proceed."
            ),
            "algo_results": survivors,
        }

    # Stage 2 — technical agent on survivors (1 AI call each)
    from data.collector import collect_all as _collect_all
    from agents.technical_agent import TechnicalAgent
    _tech = TechnicalAgent()

    async def _analyze_one(s1_result):
        ticker = s1_result["ticker"]
        async with sem:
            try:
                market_data = await _collect_all(
                    ticker, 25000, 2.0, trade_type
                )
                import preprocessor as _pre
                market_data["pre"]        = _pre.run(market_data)
                market_data["trade_type"] = trade_type
                import settings as _sm
                market_data["tomorrow_setup"] = False
                market_data["gap_detection"]  = _sm.load().get("gap_detection", {})
                from sr_levels import get_levels
                from trend_analysis import get_trend
                market_data["sr_cache"] = get_levels(ticker)
                market_data["trend"]    = get_trend(ticker)
                tech = _tech.analyze(market_data)
                return {**s1_result, "technical": tech}
            except Exception as e:
                return {**s1_result, "technical": {"error": str(e)}}

    results = await asyncio.gather(*[_analyze_one(s) for s in survivors])

    now = _dt.now().isoformat()
    s2  = _settings.load()
    if "scan" not in s2:
        s2["scan"] = {}
    s2["scan"]["last_run"] = now
    _settings.save(s2)

    return {
        "scan_time":     now,
        "trade_type":    trade_type,
        "total_scanned": len(tickers),
        "survivors":     len(survivors),
        "results":       results,
    }


@app.post("/scan")
async def run_scan(body: ScanRequest):
    return await _run_scan(body.trade_type, body.list_name, skip_ai_warning=False)

@app.post("/scan/confirm")
async def run_scan_confirm(body: ScanConfirmRequest):
    return await _run_scan(body.trade_type, body.list_name, skip_ai_warning=True)

@app.get("/scan/status")
def scan_status():
    s = _settings.load().get("scan", {})
    return {
        "auto_enabled":       s.get("auto_enabled", False),
        "interval_minutes":   s.get("interval_minutes", 5),
        "score_threshold":    s.get("score_threshold", 60),
        "concurrency_limit":  s.get("concurrency_limit", 5),
        "default_trade_type": s.get("default_trade_type", "day"),
        "last_run":           s.get("last_run"),
    }

@app.post("/scan/auto/start")
async def scan_auto_start(interval_minutes: int = None):
    global _auto_scan_task
    s = _settings.load()
    if "scan" not in s:
        s["scan"] = {}
    s["scan"]["auto_enabled"] = True
    if interval_minutes:
        s["scan"]["interval_minutes"] = interval_minutes
    _settings.save(s)
    if _auto_scan_task is None or _auto_scan_task.done():
        _auto_scan_task = asyncio.create_task(_auto_scan_loop())
    return scan_status()

@app.post("/scan/auto/stop")
async def scan_auto_stop():
    global _auto_scan_task
    s = _settings.load()
    if "scan" not in s:
        s["scan"] = {}
    s["scan"]["auto_enabled"] = False
    _settings.save(s)
    if _auto_scan_task and not _auto_scan_task.done():
        _auto_scan_task.cancel()
        _auto_scan_task = None
    return scan_status()


async def _auto_scan_loop():
    """Background auto-scan — Stage 1 only (zero AI cost)."""
    from datetime import datetime as _dt
    while True:
        try:
            s          = _settings.load().get("scan", {})
            if not s.get("auto_enabled", False):
                break
            trade_type = s.get("default_trade_type", "day")
            interval   = s.get("interval_minutes", 5)
            threshold  = s.get("score_threshold", 60)

            from utils import is_market_hours
            if trade_type == "day" and not is_market_hours():
                await asyncio.sleep(interval * 60)
                continue

            wl      = get_watchlist()
            tickers = wl.get("default", [])
            _scan_bar_cache.clear()

            results = []
            for ticker in tickers:
                try:
                    bars   = await _fetch_bars_for_scan(ticker, trade_type)
                    result = score_ticker(bars, trade_type, threshold)
                    results.append({"ticker": ticker, **result})
                except Exception:
                    logger.exception("[AutoScan] %s", ticker)

            survivors = sorted(
                [r for r in results if r.get("passed")],
                key=lambda x: x.get("score", 0), reverse=True
            )
            now = _dt.now().isoformat()
            _last_scan_results["results"]   = survivors
            _last_scan_results["scan_time"] = now
            _last_scan_results["total"]     = len(tickers)

            s2 = _settings.load()
            if "scan" not in s2:
                s2["scan"] = {}
            s2["scan"]["last_run"] = now
            _settings.save(s2)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("[AutoScan] error")

        await asyncio.sleep(interval * 60)


@app.get("/scan/last")
def scan_last():
    """Return last auto-scan Stage 1 results."""
    return _last_scan_results or {"results": [], "message": "No scan run yet"}


@app.get("/chart-data/{ticker}")
def get_chart_data(ticker: str, timeframe: str = "daily"):
    """
    Returns combined OHLCV bars + S/R levels for charting.
    timeframe: "daily" | "weekly"
    """
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    from sr_levels import get_levels
    from data.collector import _get_daily, _get_weekly

    try:
        if timeframe == "weekly":
            df = _get_weekly(ticker)
        else:
            df = _get_daily(ticker)

        bars = []
        if not df.empty:
            cols = [c for c in ["datetime", "open", "high", "low", "close", "volume"]
                    if c in df.columns]
            bars = df[cols].round(4).to_dict("records")
            # Convert datetime to ISO string for JSON
            for b in bars:
                if hasattr(b.get("datetime"), "isoformat"):
                    b["datetime"] = b["datetime"].isoformat()

        sr_cache = get_levels(ticker)

        return {
            "ticker":    ticker,
            "timeframe": timeframe,
            "bars":      bars,
            "sr_cache":  sr_cache,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chart-data/{ticker}/intraday")
def get_chart_data_intraday(ticker: str, limit: int = 780):
    """
    Returns 1-minute intraday OHLCV bars + VWAP + intraday S/R + yearly sr_cache.
    Timestamps emitted in ET (America/New_York) as ISO strings with offset.

    VWAP is computed per ET session (resets at 00:00 ET each day).
    intraday_levels provides today H/L, opening range (first 30 min),
    and prior day H/L/close — all in ET.

    limit: max bars to return, tail of series (default 780 ≈ 2 RTH days).
    """
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    from sr_levels import get_levels
    from data.collector import _get_intraday

    try:
        raw = _get_intraday(ticker)

        bars = []
        intraday_levels = {}

        if not raw.empty:
            df = raw.copy()

            # Convert naive UTC → ET for display and session grouping
            if df["datetime"].dt.tz is None:
                df["datetime"] = df["datetime"].dt.tz_localize("UTC")
            df["datetime"] = df["datetime"].dt.tz_convert("America/New_York")

            # Per-session VWAP (resets each ET calendar day)
            df["_session"] = df["datetime"].dt.date
            typical   = (df["high"] + df["low"] + df["close"]) / 3
            pv        = typical * df["volume"]
            cum_pv    = pv.groupby(df["_session"]).cumsum()
            cum_vol   = df["volume"].groupby(df["_session"]).cumsum()
            df["vwap"] = cum_pv / cum_vol.replace(0, float("nan"))

            # Intraday levels from most recent 2 sessions
            session_dates = sorted(df["_session"].unique())
            if session_dates:
                today_key = session_dates[-1]
                today_df  = df[df["_session"] == today_key]
                if not today_df.empty:
                    intraday_levels["today_high"] = round(float(today_df["high"].max()), 4)
                    intraday_levels["today_low"]  = round(float(today_df["low"].min()),  4)
                    # Opening range: first 30 one-minute bars of session (9:30-10:00 ET on RTH)
                    opening = today_df.head(30)
                    if not opening.empty:
                        intraday_levels["opening_range_high"] = round(float(opening["high"].max()), 4)
                        intraday_levels["opening_range_low"]  = round(float(opening["low"].min()),  4)

                if len(session_dates) >= 2:
                    prev_key = session_dates[-2]
                    prev_df  = df[df["_session"] == prev_key]
                    if not prev_df.empty:
                        intraday_levels["prev_day_high"]  = round(float(prev_df["high"].max()), 4)
                        intraday_levels["prev_day_low"]   = round(float(prev_df["low"].min()),  4)
                        intraday_levels["prev_day_close"] = round(float(prev_df["close"].iloc[-1]), 4)

            cols = [c for c in ["datetime", "open", "high", "low", "close", "volume", "vwap"]
                    if c in df.columns]
            tail_df = df[cols].tail(max(1, limit)).copy()
            for c in ["open", "high", "low", "close", "vwap"]:
                if c in tail_df.columns:
                    tail_df[c] = tail_df[c].astype(float).round(4)
            bars = tail_df.to_dict("records")
            for b in bars:
                if hasattr(b.get("datetime"), "isoformat"):
                    b["datetime"] = b["datetime"].isoformat()
                # NaN -> None so JSON serializer accepts it
                for k, v in list(b.items()):
                    if isinstance(v, float) and v != v:
                        b[k] = None

        sr_cache = get_levels(ticker)

        return {
            "ticker":          ticker,
            "timeframe":       "intraday",
            "bars":            bars,
            "intraday_levels": intraday_levels,
            "sr_cache":        sr_cache,
        }
    except Exception as e:
        logger.exception("[chart-data intraday] %s", ticker)
        raise HTTPException(status_code=500, detail=str(e))
