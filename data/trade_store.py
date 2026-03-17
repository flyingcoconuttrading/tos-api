"""
data/trade_store.py
--------------------
SQLite trade tracker at data/trades.db.
Mirrors tos-dash-v2 ideas.db structure.
Supports scalp (5/10/15/30m outcomes) and swing (1d/3d/7d/14d/30d outcomes).
Exports to data/trades.csv on every write.
"""

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from utils import get_price

DB_PATH  = Path(__file__).parent / "trades.db"
CSV_PATH = Path(__file__).parent / "trades.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT    NOT NULL,
    direction    TEXT    NOT NULL,         -- LONG / SHORT
    entry_price  REAL,
    stop         REAL,
    target       REAL,
    entry_time   TEXT,                     -- ISO datetime ET
    status       TEXT    DEFAULT 'OPEN',  -- OPEN/CONFIRMED/STOPPED/TARGET_HIT/EXPIRED/CLOSED
    trade_type   TEXT    DEFAULT 'scalp', -- scalp / swing

    -- Scalp intraday outcomes
    out_5m_price  REAL, out_5m_pnl  REAL,
    out_10m_price REAL, out_10m_pnl REAL,
    out_15m_price REAL, out_15m_pnl REAL,
    out_30m_price REAL, out_30m_pnl REAL,

    -- Multi-day outcomes (swing uses all; scalp uses 1d)
    out_1d_price  REAL, out_1d_pnl  REAL,
    out_3d_price  REAL, out_3d_pnl  REAL,
    out_7d_price  REAL, out_7d_pnl  REAL,
    out_14d_price REAL, out_14d_pnl REAL,
    out_30d_price REAL, out_30d_pnl REAL,

    -- Swing session boundary log (JSON list of {time, price, label})
    session_log  TEXT   DEFAULT '[]',

    closed_at    TEXT,
    exit_price   REAL,
    exit_reason  TEXT,   -- STOP / TARGET / MANUAL / EXPIRED
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
"""

# All columns in order — used for CSV header
_COLS = [
    "trade_id", "symbol", "direction", "entry_price", "stop", "target",
    "entry_time", "status", "trade_type",
    "out_5m_price", "out_5m_pnl", "out_10m_price", "out_10m_pnl",
    "out_15m_price", "out_15m_pnl", "out_30m_price", "out_30m_pnl",
    "out_1d_price", "out_1d_pnl", "out_3d_price", "out_3d_pnl",
    "out_7d_price", "out_7d_pnl", "out_14d_price", "out_14d_pnl",
    "out_30d_price", "out_30d_pnl",
    "session_log", "closed_at", "exit_price", "exit_reason", "notes",
]


# ── Connection ──────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


# ── Init ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)
    print(f"[TradeStore] DB ready: {DB_PATH}")


# ── P&L helper ──────────────────────────────────────────────────────────────

def _pnl(direction: str, entry: float, price: float) -> float | None:
    if not entry or not price or entry == 0:
        return None
    pct = (price - entry) / entry * 100
    return round(pct if direction.upper() == "LONG" else -pct, 4)


# ── Insert ──────────────────────────────────────────────────────────────────

def insert_trade(
    symbol:      str,
    direction:   str,
    entry_price: float,
    stop:        float,
    target:      float,
    trade_type:  str   = "scalp",
    notes:       str   = "",
) -> int:
    """Insert a new trade. Returns trade_id."""
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO trades
               (symbol, direction, entry_price, stop, target,
                entry_time, status, trade_type, notes)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (symbol.upper(), direction.upper(), entry_price, stop, target,
             now, "OPEN", trade_type.lower(), notes),
        )
        trade_id = cur.lastrowid
    _export_csv()
    return trade_id


# ── Read ─────────────────────────────────────────────────────────────────────

def get_trade(trade_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM trades WHERE trade_id=?", (trade_id,)).fetchone()
    return dict(row) if row else None


def get_open_trades() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trades WHERE status IN ('OPEN','CONFIRMED') ORDER BY entry_time"
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_trades(limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trades ORDER BY trade_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Update ───────────────────────────────────────────────────────────────────

def update_status(trade_id: int, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE trades SET status=? WHERE trade_id=?", (status, trade_id))
    _export_csv()


def close_trade(trade_id: int, exit_price: float, exit_reason: str) -> None:
    """Mark trade CLOSED with exit price and reason."""
    now = datetime.now().isoformat(timespec="seconds")
    status_map = {"STOP": "STOPPED", "TARGET": "TARGET_HIT",
                  "MANUAL": "CLOSED",  "EXPIRED": "EXPIRED"}
    status = status_map.get(exit_reason.upper(), "CLOSED")
    with _conn() as c:
        c.execute(
            """UPDATE trades SET status=?, exit_price=?, exit_reason=?, closed_at=?
               WHERE trade_id=?""",
            (status, exit_price, exit_reason.upper(), now, trade_id),
        )
    _export_csv()


def update_outcome_interval(trade_id: int, interval: str, price: float) -> None:
    """
    Update a specific outcome interval. interval is one of:
    5m, 10m, 15m, 30m, 1d, 3d, 7d, 14d, 30d
    """
    trade = get_trade(trade_id)
    if not trade:
        return
    entry     = trade.get("entry_price")
    direction = trade.get("direction", "LONG")
    pnl       = _pnl(direction, entry, price)
    col_price = f"out_{interval}_price"
    col_pnl   = f"out_{interval}_pnl"
    with _conn() as c:
        c.execute(
            f"UPDATE trades SET {col_price}=?, {col_pnl}=? WHERE trade_id=?",
            (price, pnl, trade_id),
        )
    _export_csv()


def append_session_log(trade_id: int, label: str, price: float) -> None:
    """Append a session boundary price snapshot to session_log JSON."""
    trade = get_trade(trade_id)
    if not trade:
        return
    log = json.loads(trade.get("session_log") or "[]")
    log.append({
        "time":  datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "price": price,
    })
    with _conn() as c:
        c.execute(
            "UPDATE trades SET session_log=? WHERE trade_id=?",
            (json.dumps(log), trade_id),
        )
    _export_csv()


# ── Price-triggered stop/target check ────────────────────────────────────────

def check_price_trigger(trade: dict, current_price: float) -> str | None:
    """
    Returns 'STOP' if stop hit, 'TARGET' if target hit, else None.
    Works for both LONG and SHORT.
    """
    if not current_price:
        return None
    direction = str(trade.get("direction", "")).upper()
    stop      = trade.get("stop")
    target    = trade.get("target")

    if direction == "LONG":
        if stop   and current_price <= stop:   return "STOP"
        if target and current_price >= target: return "TARGET"
    elif direction == "SHORT":
        if stop   and current_price >= stop:   return "STOP"
        if target and current_price <= target: return "TARGET"
    return None


# ── CSV export ───────────────────────────────────────────────────────────────

def _export_csv() -> None:
    trades = get_all_trades(limit=10_000)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
