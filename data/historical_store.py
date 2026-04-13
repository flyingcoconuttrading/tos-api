"""
historical_store.py — Local SQLite cache for historical bar data.

Stores normalized bars from any adapter (Polygon, Schwab, yfinance).
Prevents re-fetching data already downloaded.
Schema is adapter-agnostic — normalized bar format only.
"""

import sqlite3
import json
import logging
from pathlib import Path
from typing import Optional

logger  = logging.getLogger("tos_api.historical_store")
DB_PATH = Path(__file__).parent / "historical.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def ensure_schema():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS bars (
                symbol    TEXT    NOT NULL,
                timeframe TEXT    NOT NULL,
                timestamp INTEGER NOT NULL,
                open      REAL    NOT NULL,
                high      REAL    NOT NULL,
                low       REAL    NOT NULL,
                close     REAL    NOT NULL,
                volume    REAL,
                vwap      REAL,
                trades    INTEGER,
                source    TEXT,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bars_symbol_tf ON bars(symbol, timeframe)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS backfill_log (
                symbol      TEXT    NOT NULL,
                timeframe   TEXT    NOT NULL,
                from_date   TEXT    NOT NULL,
                to_date     TEXT    NOT NULL,
                bars_count  INTEGER,
                source      TEXT,
                completed_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (symbol, timeframe, from_date, to_date)
            )
        """)
        c.commit()


def insert_bars(bars: list[dict]):
    """Upsert normalized bar dicts. Ignores duplicates."""
    if not bars:
        return
    with _conn() as c:
        c.executemany("""
            INSERT OR IGNORE INTO bars
                (symbol, timeframe, timestamp, open, high, low, close,
                 volume, vwap, trades, source)
            VALUES
                (:symbol, :timeframe, :timestamp, :open, :high, :low, :close,
                 :volume, :vwap, :trades, :source)
        """, bars)
        c.commit()
    logger.debug("Inserted %d bars", len(bars))


def get_bars(symbol: str, timeframe: str,
             from_ts: int = 0, to_ts: int = None) -> list[dict]:
    """Return bars as list of dicts sorted by timestamp asc."""
    query  = "SELECT * FROM bars WHERE symbol=? AND timeframe=?"
    params = [symbol, timeframe]
    if from_ts:
        query += " AND timestamp >= ?"
        params.append(from_ts)
    if to_ts:
        query += " AND timestamp <= ?"
        params.append(to_ts)
    query += " ORDER BY timestamp ASC"
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_latest_timestamp(symbol: str, timeframe: str) -> Optional[int]:
    """Return the most recent timestamp stored for symbol+timeframe, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT MAX(timestamp) AS ts FROM bars WHERE symbol=? AND timeframe=?",
            (symbol, timeframe)
        ).fetchone()
    return row["ts"] if row and row["ts"] else None


def get_earliest_timestamp(symbol: str, timeframe: str) -> Optional[int]:
    with _conn() as c:
        row = c.execute(
            "SELECT MIN(timestamp) AS ts FROM bars WHERE symbol=? AND timeframe=?",
            (symbol, timeframe)
        ).fetchone()
    return row["ts"] if row and row["ts"] else None


def log_backfill(symbol: str, timeframe: str, from_date: str,
                 to_date: str, bars_count: int, source: str):
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO backfill_log
                (symbol, timeframe, from_date, to_date, bars_count, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (symbol, timeframe, from_date, to_date, bars_count, source))
        c.commit()


def get_backfill_status() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM backfill_log ORDER BY completed_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def bar_count(symbol: str, timeframe: str) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM bars WHERE symbol=? AND timeframe=?",
            (symbol, timeframe)
        ).fetchone()
    return row["n"] if row else 0


# Run schema on import
ensure_schema()
