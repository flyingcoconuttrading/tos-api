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
    target_2     REAL,
    entry_time   TEXT,                     -- ISO datetime ET
    status       TEXT    DEFAULT 'OPEN',  -- OPEN/CONFIRMED/STOPPED/TARGET_HIT/TARGET_1_HIT/EXPIRED/CLOSED
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

    -- Target 1 partial hit (TARGET_1_HIT status — still watching for T2)
    out_t1_price REAL, out_t1_pnl REAL,

    -- Swing session boundary log (JSON list of {time, price, label})
    session_log  TEXT   DEFAULT '[]',

    closed_at    TEXT,
    exit_price   REAL,
    exit_reason  TEXT,   -- STOP / TARGET / TARGET_2 / MANUAL / EXPIRED
    notes        TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
"""

# Migrations for existing DBs — safe to re-run (OperationalError ignored)
_MIGRATIONS = [
    "ALTER TABLE trades ADD COLUMN target_2    REAL",
    "ALTER TABLE trades ADD COLUMN out_t1_price REAL",
    "ALTER TABLE trades ADD COLUMN out_t1_pnl   REAL",
]

# All columns in order — used for CSV header
_COLS = [
    "trade_id", "symbol", "direction", "entry_price", "stop", "target", "target_2",
    "entry_time", "status", "trade_type",
    "out_5m_price", "out_5m_pnl", "out_10m_price", "out_10m_pnl",
    "out_15m_price", "out_15m_pnl", "out_30m_price", "out_30m_pnl",
    "out_1d_price", "out_1d_pnl", "out_3d_price", "out_3d_pnl",
    "out_7d_price", "out_7d_pnl", "out_14d_price", "out_14d_pnl",
    "out_30d_price", "out_30d_pnl",
    "out_t1_price", "out_t1_pnl",
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
    _migrate()
    print(f"[TradeStore] DB ready: {DB_PATH}")


def _migrate() -> None:
    """Apply schema migrations for existing DBs. Silently skips already-added columns."""
    with _conn() as c:
        for sql in _MIGRATIONS:
            try:
                c.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists


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
    target_2:    float | None = None,
    trade_type:  str          = "scalp",
    notes:       str          = "",
) -> int:
    """Insert a new trade. Returns trade_id."""
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO trades
               (symbol, direction, entry_price, stop, target, target_2,
                entry_time, status, trade_type, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (symbol.upper(), direction.upper(), entry_price, stop, target, target_2,
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
            "SELECT * FROM trades WHERE status IN ('OPEN','CONFIRMED','TARGET_1_HIT') ORDER BY entry_time"
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
    status_map = {
        "STOP":     "STOPPED",
        "TARGET":   "TARGET_HIT",
        "TARGET_2": "TARGET_HIT",
        "MANUAL":   "CLOSED",
        "EXPIRED":  "EXPIRED",
    }
    status = status_map.get(exit_reason.upper(), "CLOSED")
    with _conn() as c:
        c.execute(
            """UPDATE trades SET status=?, exit_price=?, exit_reason=?, closed_at=?
               WHERE trade_id=?""",
            (status, exit_price, exit_reason.upper(), now, trade_id),
        )
    _export_csv()


def record_target1_hit(trade_id: int, price: float) -> None:
    """Partial close at target 1 — set status TARGET_1_HIT, keep watching for target 2."""
    trade = get_trade(trade_id)
    if not trade:
        return
    pnl = _pnl(trade.get("direction", "LONG"), trade.get("entry_price"), price)
    with _conn() as c:
        c.execute(
            "UPDATE trades SET status='TARGET_1_HIT', out_t1_price=?, out_t1_pnl=? WHERE trade_id=?",
            (price, pnl, trade_id),
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


# ── Scalp interval outcome snapshots ────────────────────────────────────────

# Minutes after entry at which to snapshot scalp trade price
SCALP_INTERVALS = [(5, "5m"), (10, "10m"), (15, "15m"), (30, "30m")]


def check_scalp_intervals(trade: dict, current_price: float) -> None:
    """
    For open scalp trades, record current price at each elapsed interval
    (5m, 10m, 15m, 30m) if not yet recorded.
    Called by the price watcher on every poll cycle.
    """
    if trade.get("trade_type") != "scalp":
        return
    entry_time_str = trade.get("entry_time")
    if not entry_time_str or not current_price:
        return
    try:
        entry_dt = datetime.fromisoformat(entry_time_str)
    except ValueError:
        return

    elapsed_min = (datetime.now() - entry_dt).total_seconds() / 60
    tid = trade["trade_id"]

    for minutes, label in SCALP_INTERVALS:
        col = f"out_{label}_price"
        if elapsed_min >= minutes and trade.get(col) is None:
            update_outcome_interval(tid, label, current_price)


# ── Price-triggered stop/target check ────────────────────────────────────────

def check_price_trigger(trade: dict, current_price: float) -> str | None:
    """
    Returns 'STOP', 'TARGET_1', 'TARGET_2', or 'TARGET' (no target_2 set).
    When target_2 is set:
      - normal status: returns TARGET_1 when target hit
      - TARGET_1_HIT status: returns TARGET_2 when target_2 hit (stop still watched)
    """
    if not current_price:
        return None
    direction = str(trade.get("direction", "")).upper()
    stop      = trade.get("stop")
    target    = trade.get("target")
    target_2  = trade.get("target_2")
    status    = str(trade.get("status", "")).upper()

    if direction == "LONG":
        if stop and current_price <= stop:
            return "STOP"
        if status == "TARGET_1_HIT":
            if target_2 and current_price >= target_2:
                return "TARGET_2"
        else:
            if target_2:
                if target and current_price >= target:
                    return "TARGET_1"
            else:
                if target and current_price >= target:
                    return "TARGET"
    elif direction == "SHORT":
        if stop and current_price >= stop:
            return "STOP"
        if status == "TARGET_1_HIT":
            if target_2 and current_price <= target_2:
                return "TARGET_2"
        else:
            if target_2:
                if target and current_price <= target:
                    return "TARGET_1"
            else:
                if target and current_price <= target:
                    return "TARGET"
    return None


# ── CSV export ───────────────────────────────────────────────────────────────

def _export_csv() -> None:
    trades = get_all_trades(limit=10_000)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
