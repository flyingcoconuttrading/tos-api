"""
notifications.py — Discord webhook push notifications for tos-api.

Separate from discord_export.py (clipboard formatter for completed trades).
This file handles server-side push to Discord channels.

Env vars (in .env):
    DISCORD_WEBHOOK_URL          — default webhook (required for any push)
    DISCORD_WEBHOOK_PLAN_ALERTS  — optional separate channel for plan alerts
    DISCORD_NOTIFICATIONS_ENABLED — "true" / "false" (default true)

Usage:
    from notifications import send_plan_alert
    send_plan_alert(plan, "created")
"""

import json
import logging
import os
from datetime import datetime, timezone

import requests as _requests

logger = logging.getLogger("tos_api.notifications")

_PLAN_EVENTS = ("created", "triggered", "invalidated", "expired", "abandoned")
_RATE_LIMIT_CACHE: dict = {}   # plan_id:event → last_sent ISO string


def _get_webhook_url(channel: str = "default") -> str | None:
    if os.getenv("DISCORD_NOTIFICATIONS_ENABLED", "true").lower() == "false":
        return None
    if channel == "plan_alerts":
        return (os.getenv("DISCORD_WEBHOOK_PLAN_ALERTS")
                or os.getenv("DISCORD_WEBHOOK_URL"))
    return os.getenv("DISCORD_WEBHOOK_URL")


def _rate_limited(plan_id: int, event: str) -> bool:
    """One alert per plan per event type. Returns True if already sent."""
    key = f"{plan_id}:{event}"
    if key in _RATE_LIMIT_CACHE:
        return True
    _RATE_LIMIT_CACHE[key] = datetime.now(timezone.utc).isoformat()
    return False


def send_discord(message: str, channel: str = "default") -> bool:
    """
    Push a plain-text message to Discord webhook.
    Returns True on success, False on failure (never raises).
    """
    url = _get_webhook_url(channel)
    if not url:
        return False
    try:
        resp = _requests.post(
            url,
            json={"content": message[:2000]},  # Discord 2000 char limit
            timeout=5,
        )
        if resp.status_code not in (200, 204):
            logger.warning("Discord push failed: %d %s", resp.status_code, resp.text[:100])
            return False
        return True
    except Exception:
        logger.exception("Discord push error")
        return False


def send_plan_alert(plan: dict, event: str) -> bool:
    """
    Push a formatted plan alert to Discord.
    event: "created" | "triggered" | "invalidated" | "expired" | "abandoned"
    Rate-limited: one message per plan per event.
    """
    if event not in _PLAN_EVENTS:
        return False

    plan_id = plan.get("plan_id", "?")
    if _rate_limited(plan_id, event):
        return False

    ticker     = plan.get("ticker", "?")
    direction  = plan.get("direction", "?")
    trade_type = plan.get("trade_type", "?")
    confidence = plan.get("confidence", "?")
    entry_low  = plan.get("entry_low")
    entry_high = plan.get("entry_high")
    stop_loss  = plan.get("stop_loss")
    target_1   = plan.get("target_1")
    status     = plan.get("status", "?")

    dir_emoji = "🟢" if direction == "LONG" else "🔴" if direction == "SHORT" else "⚪"

    entry_str = (f"${entry_low:.2f}–${entry_high:.2f}"
                 if entry_low and entry_high else "N/A")

    if event == "created":
        icon = "📋"
        headline = f"**NEW PLAN** | {ticker} {direction} {trade_type.upper()}"
        body = (f"Entry: {entry_str} | Stop: ${stop_loss:.2f} | "
                f"T1: ${target_1:.2f}" if stop_loss and target_1 else "")
        detail = f"Confidence: {confidence}% | Status: {status}"

    elif event == "triggered":
        icon = "✅"
        price = plan.get("triggered_price", "?")
        headline = f"**TRIGGERED** | {ticker} {direction} — entry zone touched"
        body = f"Fill price: ${price}" if isinstance(price, (int, float)) else ""
        detail = f"Plan #{plan_id} | {trade_type.upper()}"

    elif event == "invalidated":
        icon = "❌"
        reason = plan.get("invalidation_reason", "?").replace("_", " ").title()
        price  = plan.get("invalidation_price")
        headline = f"**INVALIDATED** | {ticker} — {reason}"
        body = f"At price: ${price:.2f}" if price else ""
        detail = f"Plan #{plan_id} | {trade_type.upper()} {direction}"

    elif event == "expired":
        icon = "⏰"
        headline = f"**EXPIRED** | {ticker} {direction} — time stop reached"
        body = f"Time stop: {plan.get('time_stop', 'N/A')}"
        detail = f"Plan #{plan_id}"

    elif event == "abandoned":
        icon = "🚫"
        reason = (plan.get("invalidation_reason") or "WAITING_NOT_MET").replace("_", " ").title()
        headline = f"**ABANDONED** | {ticker} — {reason}"
        body = "Wait condition cleared but entry zone no longer valid"
        detail = f"Plan #{plan_id} | was WAITING"

    parts = [f"{icon} {dir_emoji} {headline}"]
    if body:
        parts.append(body)
    parts.append(detail)

    message = "\n".join(parts)
    return send_discord(message, channel="plan_alerts")
