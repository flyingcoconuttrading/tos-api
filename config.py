import os
from dotenv import load_dotenv

load_dotenv()

# ── Anthropic ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-20250514"

# ── Schwab API ─────────────────────────────────────────────────────────────
SCHWAB_APP_KEY      = os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET   = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_CALLBACK_URL = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
SCHWAB_TOKENS_DB = os.getenv("SCHWAB_TOKENS_DB", "C:/Users/randy/.schwabdev/tokens.db")

# ── PostgreSQL ─────────────────────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_PORT     = os.getenv("DB_PORT",     "5432")
DB_NAME     = os.getenv("DB_NAME",     "stock_checker")
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_URL      = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ── Feature Flags ──────────────────────────────────────────────────────────
ENABLE_OPTIONS  = os.getenv("ENABLE_OPTIONS",  "false").lower() == "true"
ENABLE_RTD      = os.getenv("ENABLE_RTD",      "false").lower() == "true"
ENABLE_NEWS     = os.getenv("ENABLE_NEWS",     "false").lower() == "true"
ENABLE_ECON_CAL = os.getenv("ENABLE_ECON_CAL", "false").lower() == "true"

# ── Cache TTLs (seconds) ───────────────────────────────────────────────────
CACHE_TTL_INTRADAY = 60
CACHE_TTL_DAILY    = 6 * 3600
CACHE_TTL_OPTIONS  = 5 * 60
CACHE_TTL_QUOTE    = 15

# ── Default Account Settings ───────────────────────────────────────────────
DEFAULT_ACCOUNT_SIZE = 25000
DEFAULT_RISK_PERCENT = 2.0

# ── Day Trading Config ─────────────────────────────────────────────────────
DAY_TRADE_CONFIG = {
    "timeframe":      "1min",
    "lookback_days":  5,
    "bars_to_ai":     240,
    "rsi_window":     14,
    "emas":           [9, 20],
    "smas":           [20, 50, 100, 200],
    "macd":           True,
    "vwap":           True,
    "daily_lookback": 30,
}

# ── Polygon.io — historical data + EOD quotes ─────────────────────────────
# Free tier: 5 calls/min, 2 years history, EOD only
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")

# ── Checker Methodology Rules ──────────────────────────────────────────────
CHECKER_RULES = """
CHECKER METHODOLOGY RULES (follow strictly):
1. Buy at SUPPORT, not at breakout — enter on pullbacks that are likely to hold
2. Short at RESISTANCE — wait for rejection confirmation, not anticipation
3. Define Risk/Reward BEFORE entry — minimum 1:1.5, prefer 1:2+
4. Time stops are mandatory — day trades must close by 4:00 PM ET
5. Reduce size when Wild Card risk is HIGH or DO_NOT_TRADE
6. Never average into a losing position
7. Wait for S/R levels to be tested and confirmed — patience over FOMO
"""
