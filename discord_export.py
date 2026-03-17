"""
discord_export.py — Format trades for Discord / clipboard copy.

Usage:
    from discord_export import format_trade, copy_to_clipboard
    text = copy_to_clipboard(trade_dict)
"""
import subprocess
import sys


def format_trade(trade: dict) -> str:
    """
    Returns a Discord-ready trade summary string.

    Expected keys: symbol, direction, entry_price, stop, target,
                   status, out_Xm_pnl or out_Xd_pnl, notes.
    """
    direction = str(trade.get("direction", "")).upper()
    emoji     = "🟢" if direction == "LONG" else "🔴"
    symbol    = str(trade.get("symbol", "???")).upper()

    entry  = trade.get("entry_price")
    stop   = trade.get("stop")
    target = trade.get("target")
    status = str(trade.get("status", "OPEN")).upper()
    notes  = trade.get("notes") or ""

    # Risk/reward ratio
    rr = "N/A"
    if entry and stop and target and abs(entry - stop) > 0:
        risk   = abs(entry - stop)
        reward = abs(target - entry)
        rr     = f"1:{reward / risk:.1f}"

    # Best available P&L — prefer latest interval
    pnl     = None
    pnl_lbl = ""
    for col, lbl in [
        ("out_30d_pnl", "30d"), ("out_14d_pnl", "14d"),
        ("out_7d_pnl",  "7d"),  ("out_3d_pnl",  "3d"),
        ("out_1d_pnl",  "1d"),  ("out_30m_pnl", "30m"),
        ("out_15m_pnl", "15m"), ("out_10m_pnl", "10m"),
        ("out_5m_pnl",  "5m"),
    ]:
        if trade.get(col) is not None:
            pnl     = trade[col]
            pnl_lbl = lbl
            break

    if pnl is not None:
        sign    = "+" if pnl >= 0 else ""
        pnl_str = f"{sign}{pnl:.2f}% ({pnl_lbl})"
    else:
        pnl_str = "N/A"

    lines = [
        f"{emoji} {symbol} | {direction} | Entry: ${entry:.2f}" if entry else f"{emoji} {symbol} | {direction}",
        f"Stop: ${stop:.2f} | Target: ${target:.2f} | R:R {rr}" if (stop and target) else "Stop/Target: pending",
        f"Status: {status} | P&L: {pnl_str}",
    ]
    if notes:
        lines.append(f"Notes: {notes}")

    return "\n".join(lines)


def copy_to_clipboard(trade: dict) -> str:
    """
    Format trade and copy to clipboard. Returns the formatted string.
    Falls back to printing if clipboard copy fails.
    """
    text = format_trade(trade)
    try:
        if sys.platform == "win32":
            subprocess.run("clip", input=text.encode("utf-8"), check=True, shell=True)
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"],
                           input=text.encode("utf-8"), check=True)
    except Exception:
        # Clipboard unavailable — caller can display the text instead
        pass
    return text
