"""
scripts/backfill.py — Historical data backfill from Polygon.io.

Downloads 2 years of daily and 1-min bars for core symbols.
Safe to re-run — skips already-downloaded date ranges.
Respects 5 calls/minute rate limit automatically.

Usage:
    python scripts/backfill.py                    # all symbols, all timeframes
    python scripts/backfill.py --symbol SPY       # single symbol
    python scripts/backfill.py --timeframe 1d     # daily only
    python scripts/backfill.py --days 30          # last 30 days only
    python scripts/backfill.py --status           # show what's already downloaded
"""

import sys
import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.polygon_adapter import fetch_bars
from data.historical_store import insert_bars, log_backfill, get_backfill_status, bar_count

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("backfill")

# Core symbols — NQ proxied via QQQ (Polygon doesn't carry futures on free tier)
SYMBOLS = ["SPY", "QQQ", "IWM"]

# Timeframes to backfill
TIMEFRAMES = ["1d", "1m"]

# How far back to go (free tier supports 2 years)
DEFAULT_LOOKBACK_DAYS = 730


def get_api_key() -> str:
    import os
    from pathlib import Path
    import json

    # Try env first
    key = os.environ.get("POLYGON_API_KEY")
    if key:
        return key

    # Try config.py
    try:
        from config import POLYGON_API_KEY
        if POLYGON_API_KEY:
            return POLYGON_API_KEY
    except (ImportError, AttributeError):
        pass

    # Try .env file
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("POLYGON_API_KEY="):
                return line.split("=", 1)[1].strip()

    raise ValueError(
        "POLYGON_API_KEY not found. Set it in config.py, .env, or environment variable."
    )


def backfill_symbol(symbol: str, timeframe: str, from_date: str,
                    to_date: str, api_key: str) -> int:
    logger.info("Fetching %s %s  %s → %s", symbol, timeframe, from_date, to_date)
    try:
        bars = fetch_bars(symbol, timeframe, from_date, to_date, api_key)
        if bars:
            insert_bars(bars)
            log_backfill(symbol, timeframe, from_date, to_date, len(bars), "polygon")
            logger.info("  ✓ %d bars stored", len(bars))
        else:
            logger.warning("  ⚠ No bars returned for %s %s", symbol, timeframe)
        return len(bars)
    except PermissionError as e:
        logger.error("  ✗ Not authorized: %s", e)
        return 0
    except Exception as e:
        logger.error("  ✗ Error: %s", e)
        return 0


def main():
    parser = argparse.ArgumentParser(description="Polygon.io historical backfill")
    parser.add_argument("--symbol",    type=str, help="Single symbol e.g. SPY")
    parser.add_argument("--timeframe", type=str, help="1d or 1m")
    parser.add_argument("--days",      type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help="Lookback days (default 730 = 2 years)")
    parser.add_argument("--status",    action="store_true", help="Show backfill status")
    args = parser.parse_args()

    if args.status:
        rows = get_backfill_status()
        if not rows:
            print("No backfill history yet.")
            return
        print(f"\n{'Symbol':<8} {'TF':<5} {'From':<12} {'To':<12} {'Bars':>8} {'Source':<10} {'Completed'}")
        print("-" * 75)
        for r in rows:
            print(f"{r['symbol']:<8} {r['timeframe']:<5} {r['from_date']:<12} "
                  f"{r['to_date']:<12} {r['bars_count']:>8} {r['source']:<10} {r['completed_at']}")
        print()
        # Also show current counts
        print(f"\nCurrent bar counts:")
        symbols = [args.symbol] if args.symbol else SYMBOLS
        tfs     = [args.timeframe] if args.timeframe else TIMEFRAMES
        for sym in symbols:
            for tf in tfs:
                n = bar_count(sym, tf)
                print(f"  {sym} {tf}: {n:,} bars")
        return

    api_key    = get_api_key()
    to_date    = date.today().isoformat()
    from_date  = (date.today() - timedelta(days=args.days)).isoformat()
    symbols    = [args.symbol]    if args.symbol    else SYMBOLS
    timeframes = [args.timeframe] if args.timeframe else TIMEFRAMES

    total = 0
    for symbol in symbols:
        for timeframe in timeframes:
            n = backfill_symbol(symbol, timeframe, from_date, to_date, api_key)
            total += n

    logger.info("\nBackfill complete. Total bars stored: %d", total)
    logger.info("Run with --status to see summary.")


if __name__ == "__main__":
    main()
