#!/usr/bin/env bash
# run-local.sh — Run agent-sandbox natively on macOS (no Docker)
#
# Starts: Chrome headless (CDP :9222), REST API (:8091), MCP server (:8079)
# Skips:  VNC, noVNC, nginx, code-server
#
# Usage:
#   ./scripts/run-local.sh           # start all services
#   CDP_PORT=9333 ./scripts/run-local.sh  # override ports via env

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/.venv-local"
CHROME_DATA_DIR="${HOME}/.config/agent-sandbox-local"
CDP_PORT="${CDP_PORT:-9222}"
API_PORT="${API_PORT:-8091}"
MCP_PORT="${MCP_PORT:-8079}"
STEALTH_EXT="$REPO_ROOT/core/stealth-extension"

# ---------------------------------------------------------------------------
# Chrome detection
# ---------------------------------------------------------------------------
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [[ ! -x "$CHROME_BIN" ]]; then
    echo "ERROR: Google Chrome not found at: $CHROME_BIN"
    echo "Install from https://www.google.com/chrome/ and retry."
    exit 1
fi

# ---------------------------------------------------------------------------
# Python virtualenv + deps
# ---------------------------------------------------------------------------
if [[ ! -d "$VENV" ]]; then
    echo "Creating virtualenv at $VENV ..."
    python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip install -q \
    -r "$REPO_ROOT/core/api/requirements.txt" \
    -r "$REPO_ROOT/core/mcp_server/requirements.txt"

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
PIDS=()
cleanup() {
    echo ""
    echo "Shutting down ..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    # Chrome may have spawned child processes — kill by user-data-dir marker
    pkill -f "agent-sandbox-local" 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Chrome (headless, CDP on $CDP_PORT)
# ---------------------------------------------------------------------------
echo "Starting Chrome on port $CDP_PORT ..."
mkdir -p "$CHROME_DATA_DIR"
rm -f "$CHROME_DATA_DIR/Singleton"*

"$CHROME_BIN" \
    --headless=new \
    --no-sandbox \
    --disable-dev-shm-usage \
    --remote-debugging-port="$CDP_PORT" \
    --remote-debugging-address=0.0.0.0 \
    --remote-allow-origins="*" \
    --user-data-dir="$CHROME_DATA_DIR" \
    --window-size=1280,800 \
    --no-first-run \
    --no-default-browser-check \
    --disable-background-networking \
    --disable-default-apps \
    --disable-extensions-except="$STEALTH_EXT" \
    --load-extension="$STEALTH_EXT" \
    --disable-sync \
    --disable-blink-features=AutomationControlled \
    about:blank >/tmp/agent-sandbox-chrome.log 2>&1 &
CHROME_PID=$!
PIDS+=("$CHROME_PID")
echo "  Chrome PID $CHROME_PID, log: /tmp/agent-sandbox-chrome.log"

# Give Chrome time to open its debug socket
sleep 2

# ---------------------------------------------------------------------------
# REST API (uvicorn, port $API_PORT)
# ---------------------------------------------------------------------------
echo "Starting REST API on port $API_PORT ..."
CDP_URL="http://localhost:$CDP_PORT" \
    uvicorn main:app \
        --host 0.0.0.0 \
        --port "$API_PORT" \
        --app-dir "$REPO_ROOT/core/api" \
        --log-level info >/tmp/agent-sandbox-api.log 2>&1 &
API_PID=$!
PIDS+=("$API_PID")
echo "  API PID $API_PID, log: /tmp/agent-sandbox-api.log"

# ---------------------------------------------------------------------------
# MCP server (uvicorn, port $MCP_PORT)
# PYTHONPATH overrides the hardcoded /opt/sandbox/api path in server.py
# ---------------------------------------------------------------------------
echo "Starting MCP server on port $MCP_PORT ..."
PYTHONPATH="$REPO_ROOT/core/api${PYTHONPATH:+:$PYTHONPATH}" \
CDP_URL="http://localhost:$CDP_PORT" \
    uvicorn server:create_app \
        --factory \
        --host 0.0.0.0 \
        --port "$MCP_PORT" \
        --app-dir "$REPO_ROOT/core/mcp_server" \
        --log-level info >/tmp/agent-sandbox-mcp.log 2>&1 &
MCP_PID=$!
PIDS+=("$MCP_PID")
echo "  MCP PID $MCP_PID, log: /tmp/agent-sandbox-mcp.log"

# ---------------------------------------------------------------------------
echo ""
echo "All services up:"
echo "  REST API : http://localhost:$API_PORT/v1/docs"
echo "  MCP SSE  : http://localhost:$MCP_PORT/mcp/sse"
echo "  CDP      : http://localhost:$CDP_PORT"
echo ""
echo "Logs: /tmp/agent-sandbox-{chrome,api,mcp}.log"
echo "Press Ctrl+C to stop all services."
echo ""

wait
