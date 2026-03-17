"""
settings.py — Load/save persistent settings from data/settings.json.
All modules that use MAs should call settings.get_ma_config() instead
of reading hard-coded values from config.py.
"""
import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "data" / "settings.json"

DEFAULT_SETTINGS: dict = {
    "moving_averages": {
        "ma1": {"period": 20,  "type": "SMA"},
        "ma2": {"period": 50,  "type": "SMA"},
        "ma3": {"period": 200, "type": "SMA"},
    },
    # ── Placeholder sections — add config groups here as needed ─────────────
    "_sections": ["moving_averages"],
    "_future": {
        "risk":     "max_risk_per_trade, max_daily_loss, position_size_pct",
        "display":  "theme, chart_type, refresh_interval_ms",
        "alerts":   "discord_webhook, email_alerts, sms_alerts",
    },
}


def load() -> dict:
    """Return current settings. Falls back to defaults on any error."""
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text())
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save(settings: dict) -> None:
    """Persist settings to disk. Merges with defaults to fill gaps."""
    merged = DEFAULT_SETTINGS.copy()
    merged.update(settings)
    SETTINGS_PATH.parent.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2))


def get_ma_config() -> dict:
    """
    Returns {"emas": [...], "smas": [...]} derived from settings.json.
    Falls back to config.py DAY_TRADE_CONFIG defaults if settings are missing.
    """
    try:
        s   = load()
        mas = s.get("moving_averages", {})
        emas, smas = [], []
        for key in sorted(k for k in mas if not k.startswith("_")):
            ma  = mas[key]
            p   = int(ma.get("period") or 0)
            typ = str(ma.get("type", "SMA")).upper()
            if p > 0:
                (emas if typ == "EMA" else smas).append(p)
        if emas or smas:
            return {"emas": emas, "smas": smas}
    except Exception:
        pass
    # Fallback to hard-coded defaults
    from config import DAY_TRADE_CONFIG
    return {"emas": DAY_TRADE_CONFIG["emas"], "smas": DAY_TRADE_CONFIG["smas"]}
