"""
data/plan_store.py
------------------
DuckDB-backed pending plan tracker. Mirrors trade_store_duck.py patterns.
Plans are auto-created on TRADE/TRADE_WAIT verdicts and tracked by
plan_validator until TRIGGERED, INVALIDATED, EXPIRED, or ABANDONED.
"""

import json
from datetime import datetime, timezone
from db.duckdb_manager import get_conn, fetch_one, fetch_all


def insert_plan(analyze_response: dict, analysis_log_id: int = None) -> int:
    """
    Auto-create a pending plan from a /analyze response dict.
    Returns plan_id. Called immediately after checker.run().
    """
    plan       = analyze_response.get("trade_plan", {})
    verdict    = plan.get("verdict", "")
    if verdict not in ("TRADE", "TRADE_WAIT"):
        return None

    ticker     = analyze_response.get("ticker", "").upper()
    trade_type = analyze_response.get("style", "day")
    direction  = plan.get("direction") or ""
    confidence = plan.get("confidence")

    ez         = plan.get("entry_zone") or {}
    entry_low  = ez.get("low")
    entry_high = ez.get("high")
    stop_loss  = plan.get("stop_loss")

    t1         = plan.get("target_1") or {}
    t2         = plan.get("target_2") or {}
    target_1   = t1.get("price") if isinstance(t1, dict) else t1
    target_2   = t2.get("price") if isinstance(t2, dict) else t2
    time_stop  = plan.get("time_stop")

    # Capture VWAP + nearest S/R for validity rules
    sr_cache   = analyze_response.get("sr_cache") or {}
    trend      = analyze_response.get("trend") or {}
    intra      = sr_cache.get("intraday_levels") or {}
    vwap_at_creation    = intra.get("vwap")
    nearest_support     = trend.get("daily", {}).get("trendline_support")
    nearest_resistance  = trend.get("daily", {}).get("trendline_resistance")

    initial_status = "PENDING" if verdict == "TRADE" else "WAITING"
    wait_reason    = plan.get("wait_reason") if verdict == "TRADE_WAIT" else None

    now = datetime.now(timezone.utc).isoformat()

    conn   = get_conn()
    result = conn.execute("""
        INSERT INTO pending_plans (
            plan_id, ticker, trade_type, direction, confidence,
            entry_low, entry_high, stop_loss, target_1, target_2,
            time_stop, vwap_at_creation, nearest_support, nearest_resistance,
            status, initial_status, wait_reason,
            analysis_log_id, created_at,
            is_option, option_type, option_strike, option_expiration,
            option_entry_debit, option_delta, option_iv, underlying_price,
            analysis_snapshot
        ) VALUES (
            nextval('plan_id_seq'), ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            FALSE, NULL, NULL, NULL,
            NULL, NULL, NULL, ?,
            ?
        ) RETURNING plan_id
    """, [
        ticker, trade_type, direction.upper(), confidence,
        entry_low, entry_high, stop_loss, target_1, target_2,
        time_stop, vwap_at_creation, nearest_support, nearest_resistance,
        initial_status, initial_status, wait_reason,
        analysis_log_id, now,
        analyze_response.get("price"),
        json.dumps({
            "reasoning":      plan.get("reasoning", []),
            "wild_card_flags": plan.get("wild_card_flags", []),
            "risk_reward":    plan.get("risk_reward"),
            "agent_verdicts": {
                k: v.get("confidence") for k, v in
                (analyze_response.get("agent_verdicts") or {}).items()
            },
        }),
    ]).fetchone()

    return result[0]


def get_plan(plan_id: int) -> dict | None:
    return fetch_one("SELECT * FROM pending_plans WHERE plan_id = ?", [plan_id])


def get_active_plans() -> list[dict]:
    """PENDING + WAITING plans — eligible for validity checks."""
    return fetch_all(
        "SELECT * FROM pending_plans "
        "WHERE status IN ('PENDING', 'WAITING', 'TRIGGERED') "
        "ORDER BY created_at"
    )


def get_all_plans(limit: int = 200, status: str = None) -> list[dict]:
    if status:
        return fetch_all(
            "SELECT * FROM pending_plans WHERE status = ? "
            "ORDER BY created_at DESC LIMIT ?",
            [status.upper(), limit]
        )
    return fetch_all(
        "SELECT * FROM pending_plans ORDER BY created_at DESC LIMIT ?",
        [limit]
    )


def update_plan_status(
    plan_id: int,
    status: str,
    reason: str = None,
    price: float = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = get_conn()
    if status == "INVALIDATED":
        conn.execute("""
            UPDATE pending_plans SET
                status = ?, invalidated_at = ?, invalidation_reason = ?,
                invalidation_price = ?, last_checked_at = ?,
                check_count = check_count + 1
            WHERE plan_id = ?
        """, [status, now, reason, price, now, plan_id])
    elif status == "TRIGGERED":
        conn.execute("""
            UPDATE pending_plans SET
                status = ?, triggered_at = ?, triggered_price = ?,
                last_checked_at = ?, check_count = check_count + 1
            WHERE plan_id = ?
        """, [status, now, price, now, plan_id])
    elif status == "ABANDONED":
        conn.execute("""
            UPDATE pending_plans SET
                status = ?, invalidated_at = ?, invalidation_reason = ?,
                last_checked_at = ?, check_count = check_count + 1
            WHERE plan_id = ?
        """, [status, now, reason or "WAITING_CONDITION_NOT_MET", now, plan_id])
    else:
        conn.execute("""
            UPDATE pending_plans SET
                status = ?, last_checked_at = ?,
                check_count = check_count + 1
            WHERE plan_id = ?
        """, [status, now, plan_id])


def touch_plan(plan_id: int) -> None:
    """Record a check without changing status."""
    now = datetime.now(timezone.utc).isoformat()
    get_conn().execute(
        "UPDATE pending_plans SET last_checked_at = ?, "
        "check_count = check_count + 1 WHERE plan_id = ?",
        [now, plan_id]
    )


def link_trade(plan_id: int, trade_id: int) -> None:
    """Stamp a DuckDB trade_id on the plan when user clicks TAKE TRADE."""
    get_conn().execute(
        "UPDATE pending_plans SET triggered_trade_id = ? WHERE plan_id = ?",
        [trade_id, plan_id]
    )


def get_plan_summary() -> dict:
    conn = get_conn()
    rows = conn.execute("""
        SELECT status, COUNT(*) AS cnt
        FROM pending_plans
        GROUP BY status
    """).fetchall()
    counts = {r[0]: r[1] for r in rows}
    return {
        "pending":     counts.get("PENDING", 0),
        "waiting":     counts.get("WAITING", 0),
        "triggered":   counts.get("TRIGGERED", 0),
        "invalidated": counts.get("INVALIDATED", 0),
        "expired":     counts.get("EXPIRED", 0),
        "abandoned":   counts.get("ABANDONED", 0),
        "total":       sum(counts.values()),
    }
