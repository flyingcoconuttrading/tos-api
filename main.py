"""
main.py
-------
FastAPI server — exposes the Stock Pick Checker engine via REST API.

Run with:
    uvicorn main:app --reload --port 8002
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import checker

app = FastAPI(
    title="Stock Pick Checker",
    description="AI-powered day trading analysis via multi-agent system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    ticker: str

class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """
    Main endpoint. Submit a ticker, get back a full day trade plan.

    Example:
        POST /analyze
        { "ticker": "AAPL" }
    """
    if not req.ticker or len(req.ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    try:
        result = await checker.run(req.ticker)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
