"""
Schwab API Connectivity Test  (schwabdev 3.x compatible)
=========================================================
Setup:
    pip install schwabdev colorama

    Create a .env file in this folder:
        SCHWAB_APP_KEY=your_key
        SCHWAB_APP_SECRET=your_secret
        SCHWAB_CALLBACK_URL=https://127.0.0.1

    The callback URL must EXACTLY match what's in the Schwab Developer Portal.

Usage:
    python test_connectivity.py
"""

import os, sys, asyncio, time
from datetime import datetime

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
except ImportError:
    class Fore:
        GREEN = RED = YELLOW = CYAN = WHITE = MAGENTA = ""
    class Style:
        BRIGHT = RESET_ALL = ""

def load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

load_env()

APP_KEY      = os.environ.get("SCHWAB_APP_KEY", "")
APP_SECRET   = os.environ.get("SCHWAB_APP_SECRET", "")
CALLBACK_URL = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1")
TOKENS_DB    = os.environ.get("SCHWAB_TOKENS_DB", "tokens.db")

PASS = f"{Fore.GREEN}✓ PASS{Style.RESET_ALL}"
FAIL = f"{Fore.RED}✗ FAIL{Style.RESET_ALL}"
INFO = f"{Fore.CYAN}ℹ INFO{Style.RESET_ALL}"

def header(t): print(f"\n{Style.BRIGHT}{'─'*60}\n  {t}\n{'─'*60}{Style.RESET_ALL}")
def result(label, ok, detail=""):
    suffix = f"  {Fore.WHITE}{detail}{Style.RESET_ALL}" if detail else ""
    print(f"  {PASS if ok else FAIL}  {label}{suffix}")
def info(msg): print(f"  {INFO}  {msg}")

# ── TEST 1 ────────────────────────────────────────────────────────────────────
def test_credentials():
    header("TEST 1 — Credentials Check")
    ok_key    = bool(APP_KEY    and "YOUR" not in APP_KEY)
    ok_secret = bool(APP_SECRET and "YOUR" not in APP_SECRET)
    result("SCHWAB_APP_KEY set",    ok_key,    APP_KEY[:8]+"..." if ok_key else "NOT SET")
    result("SCHWAB_APP_SECRET set", ok_secret, APP_SECRET[:4]+"..." if ok_secret else "NOT SET")
    result("Callback URL",          True,      CALLBACK_URL)
    result("Tokens DB path",        True,      TOKENS_DB)
    if not (ok_key and ok_secret):
        print(f"\n  {Fore.RED}ACTION:{Style.RESET_ALL} Fill in your .env file with your App Key and App Secret.")
        return False
    return True

# ── TEST 2 ────────────────────────────────────────────────────────────────────
def test_import():
    header("TEST 2 — Package Import")
    try:
        import schwabdev
        result("import schwabdev", True, f"version {getattr(schwabdev,'__version__','unknown')}")
        return True
    except ImportError as e:
        result("import schwabdev", False, str(e))
        print(f"\n  {Fore.YELLOW}FIX:{Style.RESET_ALL}  pip install schwabdev")
        return False

# ── TEST 3 ────────────────────────────────────────────────────────────────────
def test_auth():
    header("TEST 3 — OAuth2 Authentication")
    import schwabdev
    db_exists = os.path.exists(TOKENS_DB)
    result("Token DB exists", db_exists, TOKENS_DB if db_exists else "will be created on first login")
    info(f"Callback URL being used: {CALLBACK_URL}")
    info("This must EXACTLY match your Schwab Developer Portal app setting.")
    info("If browser opens: log in → authorize → copy the redirect URL → paste here.")
    try:
        client = schwabdev.Client(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            callback_url=CALLBACK_URL,
            tokens_db=TOKENS_DB,
        )
        result("Client created", True)
        result("Token DB written", os.path.exists(TOKENS_DB), TOKENS_DB)
        return client
    except Exception as e:
        result("Client creation", False, str(e))
        err = str(e).lower()
        print()
        if "https" in err:
            print(f"  {Fore.YELLOW}FIX:{Style.RESET_ALL} Callback URL must start with https://")
            print(f"       Your .env has: SCHWAB_CALLBACK_URL={CALLBACK_URL}")
            print(f"       Go to developer.schwab.com → your app → check the exact callback URL registered.")
            print(f"       Set SCHWAB_CALLBACK_URL in .env to match it exactly (no trailing slash).")
        elif "pending" in err or "approved" in err:
            print(f"  {Fore.YELLOW}FIX:{Style.RESET_ALL} App not fully approved. Status must be 'Ready for Use'.")
        else:
            print(f"  {Fore.YELLOW}HINT:{Style.RESET_ALL} Double-check App Key, Secret, and callback URL in .env.")
        return None

# ── TEST 4 ────────────────────────────────────────────────────────────────────
def test_rest_quote(client):
    header("TEST 4 — REST API: Quote")
    try:
        resp = client.quote("SPY")
        result(f"GET /quotes/SPY  [HTTP {resp.status_code}]", resp.ok)
        if resp.ok:
            spy  = resp.json().get("SPY", {}).get("quote", {})
            info(f"SPY  last={spy.get('lastPrice','N/A')}  bid={spy.get('bidPrice','N/A')}  ask={spy.get('askPrice','N/A')}")
        else:
            info(f"Body: {resp.text[:300]}")
        return resp.ok
    except Exception as e:
        result("Quote request", False, str(e))
        return False

# ── TEST 5 ────────────────────────────────────────────────────────────────────
def test_rest_option_chain(client):
    header("TEST 5 — REST API: Option Chain")
    try:
        resp = client.option_chains("SPY", strike_count=4)
        result(f"GET /chains?symbol=SPY  [HTTP {resp.status_code}]", resp.ok)
        if resp.ok:
            data  = resp.json()
            calls = data.get("callExpDateMap", {})
            info(f"Underlying price: {data.get('underlyingPrice','N/A')}")
            info(f"Expiration dates: {len(calls)}")
            if calls:
                exp, strike = next(iter(calls)), next(iter(next(iter(calls.values()))))
                c = calls[exp][strike][0]
                info(f"Sample — {exp} ${strike}: bid={c.get('bid','N/A')} ask={c.get('ask','N/A')} delta={c.get('delta','N/A')}")
        else:
            info(f"Body: {resp.text[:300]}")
        return resp.ok
    except Exception as e:
        result("Option chain", False, str(e))
        return False

# ── TEST 6 ────────────────────────────────────────────────────────────────────
async def _run_stream(client, timeout=15):
    messages = []
    def handler(msg): messages.append(msg)
    streamer = client.stream
    await streamer.start_auto(receiver=handler)
    streamer.send(streamer.level_one_equities("SPY", "0,1,2,3,8"))
    deadline = time.time() + timeout
    while time.time() < deadline and not messages:
        await asyncio.sleep(0.5)
    await streamer.stop()
    return messages

def test_streaming(client):
    header("TEST 6 — WebSocket Streaming")
    info("Subscribing to SPY Level 1 for up to 15s (needs market hours for data)...")
    try:
        messages = asyncio.run(_run_stream(client, timeout=15))
        result("WebSocket connected", True)
        result(f"Messages received ({len(messages)})", len(messages) > 0,
               "run during market hours if 0" if not messages else "")
        if messages:
            info(f"Sample: {str(messages[0])[:120]}")
        return True  # pass if socket connected, even if no data
    except Exception as e:
        result("WebSocket streaming", False, str(e))
        return False

# ── SUMMARY ───────────────────────────────────────────────────────────────────
def summary(results):
    header("SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    color  = Fore.GREEN if passed == total else (Fore.YELLOW if passed > 0 else Fore.RED)
    for name, ok in results.items():
        print(f"  {'✓ PASS' if ok else '✗ FAIL'}  {name}")
    print(f"\n  {color}{Style.BRIGHT}{passed}/{total} tests passed{Style.RESET_ALL}")
    if passed == total:
        print(f"  {Fore.GREEN}🎉 Schwab API is connected and ready!{Style.RESET_ALL}")
    elif passed >= 4:
        print(f"  {Fore.YELLOW}Core REST API working.{Style.RESET_ALL}")
    else:
        print(f"  {Fore.RED}Fix the errors above then re-run.{Style.RESET_ALL}")
    print()

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{Style.BRIGHT}{Fore.MAGENTA}{'='*60}\n  Schwab API Connectivity Test\n  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}{Style.RESET_ALL}")
    results = {}

    if not (results := results | {"Credentials": test_credentials()}):
        pass
    if not results["Credentials"]:
        return summary(results)

    results["Package import"] = test_import()
    if not results["Package import"]:
        return summary(results)

    client = test_auth()
    results["OAuth2 auth"] = client is not None
    if not client:
        return summary(results)

    results["REST quote"]        = test_rest_quote(client)
    results["REST option chain"] = test_rest_option_chain(client)
    results["WebSocket stream"]  = test_streaming(client)
    summary(results)

if __name__ == "__main__":
    main()
