"""
db/duckdb_manager.py
DuckDB connection manager for tos-api.
Single file: data/tos_api.duckdb
Single connection — API is the only writer.
External tools must connect with: duckdb.connect("tos_api.duckdb", read_only=True)
"""

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "tos_api.duckdb"

_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return singleton DuckDB connection (read-write, API process only)."""
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(exist_ok=True)
        _conn = duckdb.connect(str(DB_PATH))
    return _conn


def execute(sql: str, params: list = None):
    """Execute SQL and return list of tuples."""
    conn = get_conn()
    if params:
        return conn.execute(sql, params).fetchall()
    return conn.execute(sql).fetchall()


def execute_df(sql: str, params: list = None):
    """Execute SQL and return pandas DataFrame."""
    conn = get_conn()
    if params:
        return conn.execute(sql, params).df()
    return conn.execute(sql).df()


def fetch_one(sql: str, params: list = None) -> dict | None:
    """Execute SQL and return single row as dict."""
    conn = get_conn()
    cur  = conn.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def fetch_all(sql: str, params: list = None) -> list[dict]:
    """Execute SQL and return all rows as list of dicts."""
    conn = get_conn()
    cur  = conn.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def init_schema():
    """Create all tables and sequences. Safe to call on every startup."""
    conn = get_conn()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        trade_id             INTEGER PRIMARY KEY,
        symbol               TEXT NOT NULL,
        direction            TEXT NOT NULL,
        trade_type           TEXT NOT NULL,

        entry_price          DOUBLE,
        stop                 DOUBLE,
        target               DOUBLE,
        target_2             DOUBLE,
        entry_time           TIMESTAMP,
        status               TEXT DEFAULT 'OPEN',

        entry_daily_trend    TEXT,
        entry_weekly_trend   TEXT,
        entry_adx            DOUBLE,
        entry_mtf_alignment  TEXT,
        entry_trade_bias     TEXT,
        last_trend_update    TIMESTAMP,

        out_5m_price         DOUBLE, out_5m_pnl    DOUBLE,
        out_10m_price        DOUBLE, out_10m_pnl   DOUBLE,
        out_15m_price        DOUBLE, out_15m_pnl   DOUBLE,
        out_30m_price        DOUBLE, out_30m_pnl   DOUBLE,

        out_1d_price         DOUBLE, out_1d_pnl    DOUBLE,
        out_3d_price         DOUBLE, out_3d_pnl    DOUBLE,
        out_7d_price         DOUBLE, out_7d_pnl    DOUBLE,
        out_14d_price        DOUBLE, out_14d_pnl   DOUBLE,
        out_30d_price        DOUBLE, out_30d_pnl   DOUBLE,
        out_60d_price        DOUBLE, out_60d_pnl   DOUBLE,
        out_90d_price        DOUBLE, out_90d_pnl   DOUBLE,
        out_180d_price       DOUBLE, out_180d_pnl  DOUBLE,

        out_t1_price         DOUBLE, out_t1_pnl    DOUBLE,

        session_log          JSON    DEFAULT '[]',

        closed_at            TIMESTAMP,
        exit_price           DOUBLE,
        exit_reason          TEXT,
        notes                TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS sr_levels (
        ticker          TEXT PRIMARY KEY,
        calculated_at   TIMESTAMP NOT NULL,
        data            JSON NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS trend_data (
        ticker          TEXT PRIMARY KEY,
        calculated_at   TIMESTAMP NOT NULL,
        data            JSON NOT NULL
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        ticker   TEXT    NOT NULL,
        date     DATE    NOT NULL,
        open     DOUBLE,
        high     DOUBLE,
        low      DOUBLE,
        close    DOUBLE,
        volume   BIGINT,
        source   TEXT DEFAULT 'schwab',
        PRIMARY KEY (ticker, date)
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS scan_results (
        id              INTEGER PRIMARY KEY,
        scan_time       TIMESTAMP NOT NULL,
        trade_type      TEXT NOT NULL,
        ticker          TEXT NOT NULL,
        score           DOUBLE,
        direction       TEXT,
        passed          BOOLEAN,
        algo_data       JSON,
        technical_data  JSON
    )
    """)

    conn.execute("CREATE SEQUENCE IF NOT EXISTS trade_id_seq START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS scan_id_seq  START 1")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS plan_id_seq  START 1")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending_plans (
        plan_id              INTEGER PRIMARY KEY,
        ticker               TEXT NOT NULL,
        trade_type           TEXT NOT NULL,
        direction            TEXT NOT NULL,
        confidence           INTEGER,

        entry_low            DOUBLE,
        entry_high           DOUBLE,
        stop_loss            DOUBLE,
        target_1             DOUBLE,
        target_2             DOUBLE,
        time_stop            TEXT,

        vwap_at_creation     DOUBLE,
        nearest_support      DOUBLE,
        nearest_resistance   DOUBLE,

        status               TEXT NOT NULL DEFAULT 'PENDING',
        initial_status       TEXT NOT NULL DEFAULT 'PENDING',
        wait_reason          TEXT,

        triggered_at         TEXT,
        triggered_price      DOUBLE,
        triggered_trade_id   INTEGER,

        invalidated_at       TEXT,
        invalidation_reason  TEXT,
        invalidation_price   DOUBLE,

        analysis_log_id      INTEGER,
        created_at           TEXT NOT NULL,
        last_checked_at      TEXT,
        check_count          INTEGER DEFAULT 0,

        -- Options placeholder (populated when options trading added)
        is_option            BOOLEAN DEFAULT FALSE,
        option_type          TEXT,
        option_strike        DOUBLE,
        option_expiration    TEXT,
        option_entry_debit   DOUBLE,
        option_delta         DOUBLE,
        option_iv            DOUBLE,
        underlying_price     DOUBLE,

        -- Full analysis snapshot for backtest replay
        analysis_snapshot    JSON
    )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol   ON trades (symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_status   ON trades (status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_history   ON price_history (ticker, date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_time       ON scan_results (scan_time, ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_ticker    ON pending_plans (ticker)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_status    ON pending_plans (status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_created   ON pending_plans (created_at)")

    print(f"[DuckDB] Schema ready: {DB_PATH}")
