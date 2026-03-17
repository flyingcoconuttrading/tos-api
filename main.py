"""
main.py — Stock Pick Checker API
Run: uvicorn main:app --reload --port 8002
"""

import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import checker
import settings as _settings
import discord_export
import swing_tracker
from data import trade_store
from data.collector import _get_quote           # re-used by price watcher
from db.database import init_db, get_logs, update_outcome
from config import DEFAULT_ACCOUNT_SIZE, DEFAULT_RISK_PERCENT
from utils import get_price

app = FastAPI(
    title="Stock Pick Checker",
    description="AI-powered day trading analysis via multi-agent system",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()               # PostgreSQL — analysis logs
    trade_store.init_db()   # SQLite   — live trade tracking
    asyncio.create_task(_price_watcher())
    asyncio.create_task(_session_checker())


# ── Background tasks ─────────────────────────────────────────────────────────

async def _price_watcher():
    """Every 30 s: check all open trades against live Schwab price.
    Auto-closes if stop or target is hit."""
    while True:
        try:
            _check_open_trades()
        except Exception as e:
            print(f"[PriceWatcher] {e}")
        await asyncio.sleep(30)


def _check_open_trades():
    for trade in trade_store.get_open_trades():
        try:
            quote  = _get_quote(trade["symbol"])
            price  = get_price(quote)
            if not price:
                continue
            reason = trade_store.check_price_trigger(trade, price)
            if reason:
                trade_store.close_trade(trade["trade_id"], price, reason)
                print(f"[PriceWatcher] {trade['symbol']} auto-closed: {reason} @ {price}")
        except Exception as e:
            print(f"[PriceWatcher] {trade.get('symbol')}: {e}")


async def _session_checker():
    """Every 60 s: log session boundary prices for open swing trades
    and check multi-day outcome milestones."""
    while True:
        try:
            swing_tracker.log_session_price(_get_quote)
            swing_tracker.check_multi_day_outcomes(_get_quote)
        except Exception as e:
            print(f"[SessionChecker] {e}")
        await asyncio.sleep(60)


# ── Models ───────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    ticker:       str
    account_size: float = DEFAULT_ACCOUNT_SIZE
    risk_percent: float = DEFAULT_RISK_PERCENT

class OutcomeUpdate(BaseModel):
    outcome:       str
    outcome_price: Optional[float] = None
    notes:         Optional[str]   = None

class TradeCreate(BaseModel):
    symbol:      str
    direction:   str              # LONG / SHORT
    entry_price: float
    stop:        float
    target:      float
    trade_type:  str  = "scalp"   # scalp / swing
    notes:       Optional[str] = ""

class TradeClose(BaseModel):
    exit_price:  float
    exit_reason: str = "MANUAL"   # STOP / TARGET / MANUAL / EXPIRED

class SettingsUpdate(BaseModel):
    moving_averages: Optional[dict] = None


# ── Analysis endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.1.0"}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    if not req.ticker or len(req.ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    try:
        result = await checker.run(
            req.ticker,
            account_size=req.account_size,
            risk_percent=req.risk_percent,
        )
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


# ── Trade tracker endpoints (SQLite) ─────────────────────────────────────────

@app.post("/trades")
def create_trade(body: TradeCreate):
    """Manually enter a trade for live tracking."""
    tid = trade_store.insert_trade(
        symbol=body.symbol,
        direction=body.direction,
        entry_price=body.entry_price,
        stop=body.stop,
        target=body.target,
        trade_type=body.trade_type,
        notes=body.notes or "",
    )
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
