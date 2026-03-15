"""
Schwab API Connectivity Test
============================
Tests OAuth2 auth, REST endpoints, and WebSocket streaming.

Setup:
    pip install schwabdev colorama
    Set your credentials in .env or pass via environment variables.

Usage:
    python test_connectivity.py
"""

import os
import sys
import json
import asyncio
import time
from datetime import datetime

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
except ImportError:
    # Fallback if colorama not installed
    class Fore:
        GREEN = RED = YELLOW = CYAN = WHITE = MAGENTA = ""
    class Style:
        BRIGHT = RESET_ALL = ""

# ── Load .env if present ──────────────────────────────────────────────────────
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

load_env()

APP_KEY    = os.environ.get("SCHWAB_APP_KEY", "")
APP_SECRET = os.environ.get("SCHWAB_APP_SECRET", "")
CALLBACK   = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
TOKEN_PATH = os.environ.get("SCHWAB_TOKEN_PATH", "tokens.json")

# ── Helpers ───────────────────────────────────────────────────────────────────
PASS = f"{Fore.GREEN}✓ PASS{Style.RESET_ALL}"
FAIL = f"{Fore.RED}✗ FAIL{Style.RESET_ALL}"
SKIP = f"{Fore.YELLOW}⚠ SKIP{Style.RESET_ALL}"
INFO = f"{Fore.CYAN}ℹ INFO{Style.RESET_ALL}"

def header(title):
    print(f"\n{Style.BRIGHT}{Fore.WHITE}{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}{Style.RESET_ALL}")

def result(label, ok, detail=""):
    icon = PASS if ok else FAIL
    suffix = f"  {Fore.WHITE}{detail}{Style.RESET_ALL}" if detail else ""
    print(f"  {icon}  {label}{suffix}")

def info(msg):
    print(f"  {INFO}  {msg}")


# ── TEST 1: Credentials present ───────────────────────────────────────────────
def test_credentials():
    header("TEST 1 — Credentials Check")
    ok_key    = bool(APP_KEY    and APP_KEY    != "YOUR_APP_KEY")
    ok_secret = bool(APP_SECRET and APP_SECRET != "YOUR_APP_SECRET")

    result("SCHWAB_APP_KEY set",    ok_key,    APP_KEY[:8] + "..." if ok_key else "NOT SET")
    result("SCHWAB_APP_SECRET set", ok_secret, APP_SECRET[:4] + "..." if ok_secret else "NOT SET")
    result("Callback URL",          True,      CALLBACK)
    result("Token file path",       True,      TOKEN_PATH)

    if not (ok_key and ok_secret):
        print(f"\n  {Fore.RED}ACTION REQUIRED:{Style.RESET_ALL}")
        print("  Create a .env file next to this script with:")
        print("    SCHWAB_APP_KEY=your_key_here")
        print("    SCHWAB_APP_SECRET=your_secret_here")
        print("    SCHWAB_CALLBACK_URL=https://127.0.0.1")
        return False
    return True


# ── TEST 2: schwabdev import ──────────────────────────────────────────────────
def test_import():
    header("TEST 2 — Package Import")
    try:
        import schwabdev
        result("import schwabdev", True, f"version {schwabdev.__version__}" if hasattr(schwabdev, '__version__') else "ok")
        return True
    except ImportError as e:
        result("import schwabdev", False, str(e))
        print(f"\n  {Fore.YELLOW}FIX:{Style.RESET_ALL}  pip install schwabdev")
        return False


# ── TEST 3: OAuth2 / Token ─────────────────────────────────────────────────────
def test_auth():
    header("TEST 3 — OAuth2 Authentication")
    import schwabdev

    token_exists = os.path.exists(TOKEN_PATH)
    result("Token file exists", token_exists, TOKEN_PATH if token_exists else "will be created on first login")

    info("Creating Schwab client (browser may open for first-time auth)...")
    try:
        client = schwabdev.Client(APP_KEY, APP_SECRET, TOKEN_PATH)
        result("Client created", True)

        # Check token is valid by reading it
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH) as f:
                tok = json.load(f)
            expires_at = tok.get("access_token_issued_at", 0)
            result("Token file written", True, TOKEN_PATH)
        else:
            result("Token file written", False, "file not found after client init")

        return client
    except Exception as e:
        result("Client creation", False, str(e))
        return None


# ── TEST 4: REST — Quote ──────────────────────────────────────────────────────
def test_rest_quote(client):
    header("TEST 4 — REST API: Quote")
    try:
        resp = client.quote("SPY")
        ok = resp.ok
        result(f"GET /quotes/SPY  [{resp.status_code}]", ok)

        if ok:
            data = resp.json()
            spy = data.get("SPY", {}).get("quote", {})
            last  = spy.get("lastPrice",  spy.get("last", "N/A"))
            bid   = spy.get("bidPrice",   spy.get("bid",  "N/A"))
            ask   = spy.get("askPrice",   spy.get("ask",  "N/A"))
            info(f"SPY  last={last}  bid={bid}  ask={ask}")
        else:
            info(f"Response: {resp.text[:200]}")
        return ok
    except Exception as e:
        result("Quote request", False, str(e))
        return False


# ── TEST 5: REST — Option Chain ────────────────────────────────────────────────
def test_rest_option_chain(client):
    header("TEST 5 — REST API: Option Chain")
    try:
        resp = client.option_chains("SPY", strike_count=4)
        ok = resp.ok
        result(f"GET /chains?symbol=SPY  [{resp.status_code}]", ok)

        if ok:
            data = resp.json()
            calls = data.get("callExpDateMap", {})
            puts  = data.get("putExpDateMap",  {})
            underlying = data.get("underlyingPrice", "N/A")
            expiry_count = len(calls)
            info(f"Underlying price: {underlying}")
            info(f"Expiration dates returned: {expiry_count}")
            # Show first available expiry + strike
            if calls:
                first_exp = next(iter(calls))
                first_strike = next(iter(calls[first_exp]))
                c = calls[first_exp][first_strike][0]
                info(f"Sample call — {first_exp} strike {first_strike}:  "
                     f"bid={c.get('bid','N/A')}  ask={c.get('ask','N/A')}  "
                     f"delta={c.get('delta','N/A')}  gamma={c.get('gamma','N/A')}")
        else:
            info(f"Response: {resp.text[:200]}")
        return ok
    except Exception as e:
        result("Option chain request", False, str(e))
        return False


# ── TEST 6: Streaming — Level 1 Options ───────────────────────────────────────
async def _stream_test(client):
    """Subscribe to LEVELONE_OPTIONS for SPY, collect 3 messages, then stop."""
    import schwabdev
    messages = []
    stop = asyncio.Event()

    def handler(msg):
        messages.append(msg)
        if len(messages) >= 3:
            stop.set()

    streamer = client.stream
    await streamer.start_auto()

    # Subscribe to SPY level 1 quote
    streamer.send(streamer.level_one_equities("SPY", "0,1,2,3,8"))

    try:
        await asyncio.wait_for(stop.wait(), timeout=15)
    except asyncio.TimeoutError:
        pass

    await streamer.stop()
    return messages


def test_streaming(client):
    header("TEST 6 — WebSocket Streaming")
    info("Subscribing to SPY Level 1 for 15s (needs market hours or delayed data)...")
    try:
        messages = asyncio.run(_stream_test(client))
        if messages:
            result("WebSocket connected",    True)
            result(f"Messages received ({len(messages)})", True)
            info(f"Sample: {str(messages[0])[:120]}...")
            return True
        else:
            result("WebSocket connected", True)
            result("Messages received",   False, "0 messages — market may be closed or data delayed")
            return False
    except Exception as e:
        result("WebSocket streaming", False, str(e))
        return False


# ── SUMMARY ───────────────────────────────────────────────────────────────────
def summary(results: dict):
    header("SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    color  = Fore.GREEN if passed == total else (Fore.YELLOW if passed > 0 else Fore.RED)

    for name, ok in results.items():
        icon = PASS if ok else (SKIP if ok is None else FAIL)
        print(f"  {icon}  {name}")

    print(f"\n  {color}{Style.BRIGHT}{passed}/{total} tests passed{Style.RESET_ALL}")
    if passed == total:
        print(f"  {Fore.GREEN}🎉 All systems go — Schwab API is ready to use!{Style.RESET_ALL}")
    elif passed >= 4:
        print(f"  {Fore.YELLOW}Core REST API working. Streaming may need market hours.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}Check credentials and network, then re-run.{Style.RESET_ALL}")
    print()


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}{'='*60}")
    print(f"  Schwab API Connectivity Test")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}{Style.RESET_ALL}")

    results = {}

    # 1. Credentials
    creds_ok = test_credentials()
    results["Credentials"] = creds_ok
    if not creds_ok:
        summary(results)
        sys.exit(1)

    # 2. Import
    import_ok = test_import()
    results["Package import"] = import_ok
    if not import_ok:
        summary(results)
        sys.exit(1)

    # 3. Auth
    client = test_auth()
    results["OAuth2 auth"] = client is not None
    if not client:
        summary(results)
        sys.exit(1)

    # 4. Quote
    results["REST quote"] = test_rest_quote(client)

    # 5. Option chain
    results["REST option chain"] = test_rest_option_chain(client)

    # 6. Streaming
    results["WebSocket stream"] = test_streaming(client)

    summary(results)


if __name__ == "__main__":
    main()
