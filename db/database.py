"""
db/database.py
--------------
PostgreSQL connection and schema setup.
Run init_db() once at startup to create tables.
"""

import json
import psycopg2
import psycopg2.extras
from datetime import datetime
from config import DB_URL

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS trade_logs (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    ticker          VARCHAR(10)  NOT NULL,
    style           VARCHAR(20)  NOT NULL DEFAULT 'day_trading',
    price           NUMERIC(12,4),
    account_size    NUMERIC(12,2),
    risk_percent    NUMERIC(5,2),

    -- Verdict
    verdict         VARCHAR(20),
    direction       VARCHAR(10),
    confidence      INTEGER,
    entry_low       NUMERIC(12,4),
    entry_high      NUMERIC(12,4),
    stop_loss       NUMERIC(12,4),
    target_1        NUMERIC(12,4),
    target_2        NUMERIC(12,4),
    risk_reward     VARCHAR(20),

    -- Agent verdicts (full JSON)
    technical_verdict   JSONB,
    macro_verdict       JSONB,
    wildcard_verdict    JSONB,
    supervisor_verdict  JSONB,

    -- Market context
    spy_change      NUMERIC(8,4),
    qqq_change      NUMERIC(8,4),
    vix             NUMERIC(8,4),

    -- S/R levels
    support_levels  JSONB,
    resistance_levels JSONB,
    key_levels      JSONB,

    -- Outcome tracking (updated later)
    outcome         VARCHAR(20) DEFAULT 'PENDING',
    outcome_price   NUMERIC(12,4),
    outcome_notes   TEXT,
    outcome_at      TIMESTAMPTZ,

    -- Full raw request/response
    raw_request     JSONB,
    raw_response    JSONB
);

CREATE INDEX IF NOT EXISTS idx_trade_logs_ticker     ON trade_logs (ticker);
CREATE INDEX IF NOT EXISTS idx_trade_logs_created_at ON trade_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_logs_outcome    ON trade_logs (outcome);
CREATE INDEX IF NOT EXISTS idx_trade_logs_verdict    ON trade_logs (verdict);
"""


def get_conn():
    return psycopg2.connect(DB_URL)


def init_db():
    """Create tables if they don't exist. Called at startup."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLES)
        conn.commit()
        print("[DB] Tables initialized.")
    finally:
        conn.close()


def log_trade(request: dict, response: dict) -> int:
    """Insert a trade log entry. Returns the new row id."""
    plan = response.get("trade_plan", {})
    ctx  = response.get("market_context", {})
    verdicts = response.get("agent_verdicts", {})
    tech = verdicts.get("technical", {})
    sr   = tech.get("key_levels", {})

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO trade_logs (
                    ticker, style, price, account_size, risk_percent,
                    verdict, direction, confidence,
                    entry_low, entry_high, stop_loss, target_1, target_2, risk_reward,
                    technical_verdict, macro_verdict, wildcard_verdict, supervisor_verdict,
                    spy_change, qqq_change, vix,
                    support_levels, resistance_levels, key_levels,
                    raw_request, raw_response
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                ) RETURNING id
            """, (
                response.get("ticker"),
                response.get("style", "day_trading"),
                response.get("price"),
                request.get("account_size", 25000),
                request.get("risk_percent", 2.0),

                plan.get("verdict"),
                plan.get("direction"),
                plan.get("confidence"),
                plan.get("entry_zone", {}).get("low")  if plan.get("entry_zone") else None,
                plan.get("entry_zone", {}).get("high") if plan.get("entry_zone") else None,
                plan.get("stop_loss"),
                plan.get("target_1", {}).get("price")  if plan.get("target_1") else None,
                plan.get("target_2", {}).get("price")  if plan.get("target_2") else None,
                plan.get("risk_reward"),

                json.dumps(verdicts.get("technical", {})),
                json.dumps(verdicts.get("macro", {})),
                json.dumps(verdicts.get("wildcard", {})),
                json.dumps(plan),

                ctx.get("spy_change"),
                ctx.get("qqq_change"),
                ctx.get("vix"),

                json.dumps(tech.get("support_levels", {})),
                json.dumps(tech.get("resistance_levels", {})),
                json.dumps(sr),

                json.dumps(request),
                json.dumps(response),
            ))
            row_id = cur.fetchone()[0]
        conn.commit()
        return row_id
    finally:
        conn.close()


def get_logs(ticker: str = None, outcome: str = None, limit: int = 50) -> list:
    """Query trade logs with optional filters."""
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where, params = [], []
            if ticker:
                where.append("ticker = %s")
                params.append(ticker.upper())
            if outcome:
                where.append("outcome = %s")
                params.append(outcome.upper())
            where_sql = f"WHERE {' AND '.join(where)}" if where else ""
            params.append(limit)
            cur.execute(f"""
                SELECT id, created_at, ticker, style, price, verdict, direction,
                       confidence, entry_low, entry_high, stop_loss, target_1,
                       target_2, risk_reward, spy_change, qqq_change, vix,
                       outcome, outcome_price, outcome_notes, outcome_at,
                       account_size, risk_percent
                FROM trade_logs
                {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
            """, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def update_outcome(log_id: int, outcome: str, price: float = None, notes: str = None):
    """Update the outcome of a trade log entry."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE trade_logs
                SET outcome = %s, outcome_price = %s, outcome_notes = %s,
                    outcome_at = NOW()
                WHERE id = %s
            """, (outcome.upper(), price, notes, log_id))
        conn.commit()
    finally:
        conn.close()
