#!/usr/bin/env bash
# login.sh — Open Chrome headed for one-time logins (WhatsApp, Google Messages, Outlook)
#
# Uses the same user-data-dir as run-local.sh so sessions persist into headless mode.
#
# Workflow:
#   1. Run this script  →  Chrome opens visually
#   2. Log into WhatsApp Web, Google Messages, Outlook, etc.
#   3. Close Chrome (Cmd+Q)
#   4. Run ./scripts/run-local.sh  →  sessions are already authenticated
#
# Re-run this script any time a session expires and needs re-login.

set -euo pipefail

CHROME_DATA_DIR="${HOME}/.config/agent-sandbox-local"
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STEALTH_EXT="$REPO_ROOT/core/stealth-extension"

if [[ ! -x "$CHROME_BIN" ]]; then
    echo "ERROR: Google Chrome not found at: $CHROME_BIN"
    exit 1
fi

# Stop any running headless instance using the same data dir — they can't share
if pgrep -f "agent-sandbox-local" >/dev/null 2>&1; then
    echo "WARNING: A headless Chrome is already running with this data dir."
    echo "Stop run-local.sh first, then re-run login.sh."
    exit 1
fi

mkdir -p "$CHROME_DATA_DIR"
rm -f "$CHROME_DATA_DIR/Singleton"*

echo "Opening Chrome for login ..."
echo "  Log into: WhatsApp Web, Google Messages, Outlook — whatever you need."
echo "  When done, close Chrome (Cmd+Q) and run ./scripts/run-local.sh"
echo ""

"$CHROME_BIN" \
    --user-data-dir="$CHROME_DATA_DIR" \
    --no-first-run \
    --no-default-browser-check \
    --disable-default-apps \
    --disable-extensions-except="$STEALTH_EXT" \
    --load-extension="$STEALTH_EXT" \
    --disable-blink-features=AutomationControlled \
    --window-size=1280,800 \
    "https://web.whatsapp.com" \
    "https://messages.google.com/web" \
    "https://outlook.office.com/mail/inbox"

echo "Chrome closed. Sessions saved."
echo "Run ./scripts/run-local.sh to start the sandbox."
