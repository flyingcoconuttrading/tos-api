"""
data/trade_store_duck.py
DuckDB-backed trade tracker. Replaces trade_store.py for new trades.
trades_legacy.db (renamed from trades.db) is read-only archive.
Exports to data/trades.csv on every write.
Version: v2.2.0
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from db.duckdb_manager import get_conn, fetch_one, fetch_all

CSV_PATH = Path(__file__).parent / "trades.csv"

SCALP_INTERVALS = [(5, "5m"), (10, "10m"), (15, "15m"), (30, "30m")]

SWING_INTERVALS = {
    "swing_short":  [(1, "1d"), (3, "3d"), (7, "7d"),
                     (14, "14d"), (30, "30d")],
    "swing_medium": [(1, "1d"), (7, "7d"), (14, "14d"),
                     (30, "30d"), (60, "60d")],
    "swing_long":   [(7, "7d"), (14, "14d"), (30, "30d"),
                     (60, "60d"), (90, "90d"), (180, "180d")],
    "day":          [(1, "1d")],
}


def _pnl(direction: str, entry: float, price: float) -> float | None:
    if not entry or not price or entry == 0:
        return None
    pct = (price - entry) / entry * 100
    return round(pct if direction.upper() == "LONG" else -pct, 4)


def insert_trade(
    symbol:        str,
    direction:     str,
    entry_price:   float,
    stop:          float,
    target:        float,
    target_2:      float | None = None,
    trade_type:    str          = "scalp",
    notes:         str          = "",
    trend_context: dict         = None,
) -> int:
    now    = datetime.now()
    tc     = trend_context or {}
    daily  = tc.get("daily",  {})
    weekly = tc.get("weekly", {})

    conn   = get_conn()
    result = conn.execute("""
        INSERT INTO trades (
            trade_id, symbol, direction, trade_type,
            entry_price, stop, target, target_2,
            entry_time, status, notes,
            entry_daily_trend, entry_weekly_trend,
            entry_adx, entry_mtf_alignment, entry_trade_bias,
            last_trend_update
        ) VALUES (
            nextval('trade_id_seq'), ?, ?, ?,
            ?, ?, ?, ?,
            ?, 'OPEN', ?,
            ?, ?,
            ?, ?, ?,
            ?
        ) RETURNING trade_id
    """, [
        symbol.upper(), direction.upper(), trade_type.lower(),
        entry_price, stop, target, target_2,
        now, notes,
        daily.get("direction"),
        weekly.get("direction"),
        daily.get("adx"),
        tc.get("mtf_alignment"),
        tc.get("trade_bias"),
        now,
    ]).fetchone()

    trade_id = result[0]
    _export_csv()
    return trade_id


def get_trade(trade_id: int) -> dict | None:
    return fetch_one(
        "SELECT * FROM trades WHERE trade_id = ?", [trade_id]
    )


def get_open_trades() -> list[dict]:
    return fetch_all(
        "SELECT * FROM trades "
        "WHERE status IN ('OPEN','CONFIRMED','TARGET_1_HIT') "
        "ORDER BY entry_time"
    )


def get_all_trades(limit: int = 200) -> list[dict]:
    return fetch_all(
        "SELECT * FROM trades ORDER BY trade_id DESC LIMIT ?", [limit]
    )


def update_status(trade_id: int, status: str) -> None:
    get_conn().execute(
        "UPDATE trades SET status = ? WHERE trade_id = ?",
        [status, trade_id]
    )
    _export_csv()


def update_trend_snapshot(trade_id: int, trend: dict) -> None:
    daily  = trend.get("daily",  {})
    weekly = trend.get("weekly", {})
    get_conn().execute("""
        UPDATE trades SET
            entry_daily_trend   = ?,
            entry_weekly_trend  = ?,
            entry_adx           = ?,
            entry_mtf_alignment = ?,
            entry_trade_bias    = ?,
            last_trend_update   = ?
        WHERE trade_id = ?
          AND status IN ('OPEN','CONFIRMED','TARGET_1_HIT')
    """, [
        daily.get("direction"),
        weekly.get("direction"),
        daily.get("adx"),
        trend.get("mtf_alignment"),
        trend.get("trade_bias"),
        datetime.now(),
        trade_id,
    ])
    _export_csv()


def close_trade(trade_id: int, exit_price: float, exit_reason: str) -> None:
    status_map = {
        "STOP":     "STOPPED",
        "TARGET":   "TARGET_HIT",
        "TARGET_2": "TARGET_HIT",
        "MANUAL":   "CLOSED",
        "EXPIRED":  "EXPIRED",
    }
    status = status_map.get(exit_reason.upper(), "CLOSED")
    get_conn().execute("""
        UPDATE trades SET
            status = ?, exit_price = ?, exit_reason = ?, closed_at = ?
        WHERE trade_id = ?
    """, [status, exit_price, exit_reason.upper(), datetime.now(), trade_id])
    _export_csv()


def record_target1_hit(trade_id: int, price: float) -> None:
    trade = get_trade(trade_id)
    if not trade:
        return
    pnl = _pnl(trade.get("direction", "LONG"), trade.get("entry_price"), price)
    get_conn().execute(
        "UPDATE trades SET status='TARGET_1_HIT', "
        "out_t1_price=?, out_t1_pnl=? WHERE trade_id=?",
        [price, pnl, trade_id]
    )
    _export_csv()


def update_outcome_interval(trade_id: int, interval: str,
                             price: float) -> None:
    trade = get_trade(trade_id)
    if not trade:
        return
    pnl       = _pnl(trade.get("direction", "LONG"),
                     trade.get("entry_price"), price)
    col_price = f"out_{interval}_price"
    col_pnl   = f"out_{interval}_pnl"
    get_conn().execute(
        f"UPDATE trades SET {col_price} = ?, {col_pnl} = ? WHERE trade_id = ?",
        [price, pnl, trade_id]
    )
    _export_csv()


def append_session_log(trade_id: int, label: str, price: float) -> None:
    trade = get_trade(trade_id)
    if not trade:
        return
    log = json.loads(trade.get("session_log") or "[]")
    log.append({
        "time":  datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "price": price,
    })
    get_conn().execute(
        "UPDATE trades SET session_log = ? WHERE trade_id = ?",
        [json.dumps(log), trade_id]
    )
    _export_csv()


def check_price_trigger(trade: dict, current_price: float) -> str | None:
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


def check_scalp_intervals(trade: dict, current_price: float) -> None:
    if trade.get("trade_type") != "scalp":
        return
    entry_time_str = trade.get("entry_time")
    if not entry_time_str or not current_price:
        return
    try:
        entry_dt = (datetime.fromisoformat(entry_time_str)
                    if isinstance(entry_time_str, str) else entry_time_str)
    except ValueError:
        return
    elapsed_min = (datetime.now() - entry_dt).total_seconds() / 60
    tid = trade["trade_id"]
    for minutes, label in SCALP_INTERVALS:
        col = f"out_{label}_price"
        if elapsed_min >= minutes and trade.get(col) is None:
            update_outcome_interval(tid, label, current_price)


def check_swing_intervals(trade: dict, current_price: float) -> None:
    trade_type = trade.get("trade_type", "")
    if trade_type not in SWING_INTERVALS:
        return
    entry_time_str = trade.get("entry_time")
    if not entry_time_str or not current_price:
        return
    try:
        entry_dt = (datetime.fromisoformat(entry_time_str)
                    if isinstance(entry_time_str, str) else entry_time_str)
    except ValueError:
        return
    elapsed_days = (datetime.now() - entry_dt).total_seconds() / 86400
    tid = trade["trade_id"]
    for days, label in SWING_INTERVALS[trade_type]:
        col = f"out_{label}_price"
        if elapsed_days >= days and trade.get(col) is None:
            update_outcome_interval(tid, label, current_price)


def _export_csv() -> None:
    trades = get_all_trades(limit=10_000)
    if not trades:
        return
    fieldnames = list(trades[0].keys())
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(trades)
