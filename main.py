"""
main.py — Stock Pick Checker API
Run: uvicorn main:app --reload --port 8002
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import checker
from db.database import init_db, get_logs, update_outcome
from config import DEFAULT_ACCOUNT_SIZE, DEFAULT_RISK_PERCENT

app = FastAPI(
    title="Stock Pick Checker",
    description="AI-powered day trading analysis via multi-agent system",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


# ── Models ─────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    ticker:       str
    account_size: float = DEFAULT_ACCOUNT_SIZE
    risk_percent: float = DEFAULT_RISK_PERCENT

class OutcomeUpdate(BaseModel):
    outcome:      str
    outcome_price: Optional[float] = None
    notes:        Optional[str]    = None


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


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
