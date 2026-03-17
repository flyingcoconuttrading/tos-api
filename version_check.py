"""
version_check.py
----------------
Compares current local files against a stored baseline of hashes.
Run once to generate the baseline, then run again anytime to detect changes.

Usage:
    python version_check.py baseline   # Save current state as baseline
    python version_check.py check      # Compare current files to baseline
    python version_check.py update     # Update baseline for specific files
"""

import sys
import os
import hashlib
import json
from datetime import datetime
from pathlib import Path

BASELINE_FILE = ".file_baseline.json"

# Files to track — add new files here as the project grows
TRACKED_FILES = [
    "main.py",
    "checker.py",
    "config.py",
    "data/collector.py",
    "agents/base_agent.py",
    "agents/technical_agent.py",
    "agents/macro_agent.py",
    "agents/wildcard_agent.py",
    "agents/supervisor_agent.py",
    "cache/store.py",
    "db/database.py",
    "requirements.txt",
]

# ANSI colors for Git Bash
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def hash_file(path: str) -> str:
    """SHA256 hash of a file's contents."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()
    except FileNotFoundError:
        return "MISSING"


def get_current_hashes() -> dict:
    return {f: hash_file(f) for f in TRACKED_FILES}


def load_baseline() -> dict:
    if not os.path.exists(BASELINE_FILE):
        return {}
    with open(BASELINE_FILE) as f:
        return json.load(f)


def save_baseline(hashes: dict, label: str = "") -> None:
    baseline = {
        "created_at": datetime.now().isoformat(),
        "label":      label or f"baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "files":      hashes,
    }
    with open(BASELINE_FILE, "w") as f:
        json.dump(baseline, f, indent=2)


def cmd_baseline():
    """Save current state as baseline."""
    hashes = get_current_hashes()
    label  = input("Label for this baseline (press Enter to skip): ").strip()
    save_baseline(hashes, label)

    print(f"\n{GREEN}{BOLD}Baseline saved:{RESET}")
    for f, h in hashes.items():
        status = f"{GREEN}OK{RESET}" if h != "MISSING" else f"{RED}MISSING{RESET}"
        print(f"  {status}  {f}")
    print(f"\n{CYAN}Saved to {BASELINE_FILE}{RESET}")


def cmd_check():
    """Compare current files to baseline."""
    baseline = load_baseline()
    if not baseline:
        print(f"{RED}No baseline found. Run: python version_check.py baseline{RESET}")
        sys.exit(1)

    current = get_current_hashes()
    saved   = baseline.get("files", {})

    changed  = []
    added    = []
    missing  = []
    ok       = []

    for f in TRACKED_FILES:
        curr_hash = current.get(f, "MISSING")
        base_hash = saved.get(f)

        if curr_hash == "MISSING":
            missing.append(f)
        elif base_hash is None:
            added.append(f)
        elif curr_hash != base_hash:
            changed.append(f)
        else:
            ok.append(f)

    # ── Print report ───────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*56}")
    print(f"  Stock Pick Checker — File Version Report")
    print(f"  Baseline: {baseline.get('label', 'unknown')} ({baseline.get('created_at', '')[:19]})")
    print(f"{'='*56}{RESET}\n")

    if changed:
        print(f"{YELLOW}{BOLD}  MODIFIED ({len(changed)} files){RESET}")
        for f in changed:
            print(f"  {YELLOW}~ {f}{RESET}")
        print()

    if missing:
        print(f"{RED}{BOLD}  MISSING ({len(missing)} files){RESET}")
        for f in missing:
            print(f"  {RED}✗ {f}{RESET}")
        print()

    if added:
        print(f"{CYAN}{BOLD}  NEW — not in baseline ({len(added)} files){RESET}")
        for f in added:
            print(f"  {CYAN}+ {f}{RESET}")
        print()

    if ok:
        print(f"{GREEN}{BOLD}  UNCHANGED ({len(ok)} files){RESET}")
        for f in ok:
            print(f"  {GREEN}✓ {f}{RESET}")
        print()

    # ── Summary ────────────────────────────────────────────────────────────
    total = len(TRACKED_FILES)
    print(f"{BOLD}{'─'*56}")
    if not changed and not missing:
        print(f"  {GREEN}All {total} tracked files match baseline.{RESET}")
    else:
        issues = len(changed) + len(missing)
        print(f"  {YELLOW}{issues} file(s) differ from baseline.{RESET}")
        print(f"  Run 'python version_check.py baseline' to update baseline.")
    print(f"{'─'*56}{RESET}\n")

    return len(changed) + len(missing)


def cmd_update():
    """Interactively update baseline for specific changed files."""
    baseline = load_baseline()
    if not baseline:
        print(f"{RED}No baseline found. Run baseline first.{RESET}")
        sys.exit(1)

    current = get_current_hashes()
    saved   = baseline.get("files", {})
    changed = [f for f in TRACKED_FILES
               if current.get(f, "MISSING") != saved.get(f)
               and current.get(f) != "MISSING"]

    if not changed:
        print(f"{GREEN}No changed files — nothing to update.{RESET}")
        return

    print(f"\n{YELLOW}Modified files:{RESET}")
    for i, f in enumerate(changed):
        print(f"  [{i+1}] {f}")

    print(f"\nEnter numbers to update (e.g. 1 3), or 'all', or 'cancel':")
    choice = input("> ").strip().lower()

    if choice == "cancel":
        return
    elif choice == "all":
        selected = changed
    else:
        try:
            indices  = [int(x) - 1 for x in choice.split()]
            selected = [changed[i] for i in indices if 0 <= i < len(changed)]
        except (ValueError, IndexError):
            print(f"{RED}Invalid selection.{RESET}")
            return

    for f in selected:
        baseline["files"][f] = current[f]
        print(f"  {GREEN}Updated: {f}{RESET}")

    baseline["updated_at"] = datetime.now().isoformat()
    with open(BASELINE_FILE, "w") as fp:
        json.dump(baseline, fp, indent=2)

    print(f"\n{GREEN}Baseline updated for {len(selected)} file(s).{RESET}")


# ── Main ───────────────────────────────────────────────────────────────────

COMMANDS = {
    "baseline": cmd_baseline,
    "check":    cmd_check,
    "update":   cmd_update,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in COMMANDS:
        print(f"Usage: python version_check.py [baseline|check|update]")
        sys.exit(1)
    COMMANDS[cmd]()
