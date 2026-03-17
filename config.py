import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Schwab
SCHWAB_APP_KEY      = os.getenv("SCHWAB_APP_KEY", "")
SCHWAB_APP_SECRET   = os.getenv("SCHWAB_APP_SECRET", "")
SCHWAB_ACCESS_TOKEN  = os.getenv("SCHWAB_ACCESS_TOKEN", "")
SCHWAB_REFRESH_TOKEN = os.getenv("SCHWAB_REFRESH_TOKEN", "")

SCHWAB_BASE_URL  = "https://api.schwabapi.com/marketdata/v1"
SCHWAB_TRADER_URL = "https://api.schwabapi.com/trader/v1"
SCHWAB_TOKEN_URL  = "https://api.schwabapi.com/v1/oauth/token"

# Day Trading Config
DAY_TRADE_CONFIG = {
    "timeframe":     "1min",
    "lookback_days": 5,
    "bars_to_ai":    240,
    "rsi_window":    14,
    "emas":          [9, 20],
    "smas":          [20, 50, 100, 200],
    "macd":          True,
}
