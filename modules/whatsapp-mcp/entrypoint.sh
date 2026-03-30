#!/bin/bash
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data}"
BRIDGE_PORT="${BRIDGE_PORT:-8080}"
MCP_PORT="${MCP_PORT:-8081}"

# ---------------------------------------------------------------------------
# Start Go bridge (whatsmeow)
# On first run it prints a QR code — view with: docker logs -f agent-whatsapp-mcp
# On subsequent runs it reconnects from the saved SQLite session automatically.
# ---------------------------------------------------------------------------
echo "[whatsapp-mcp] Starting Go bridge on :${BRIDGE_PORT} (data: ${DATA_DIR})..."
cd "$DATA_DIR"
/usr/local/bin/whatsapp-bridge &
BRIDGE_PID=$!

# ---------------------------------------------------------------------------
# Wait for bridge to accept connections (up to 60 s)
# ---------------------------------------------------------------------------
echo "[whatsapp-mcp] Waiting for bridge (scan QR if first run)..."
READY=0
for i in $(seq 1 60); do
    if curl -sf "http://localhost:${BRIDGE_PORT}/" >/dev/null 2>&1 || \
       curl -sf "http://localhost:${BRIDGE_PORT}/health" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 1
done

if [[ $READY -eq 0 ]]; then
    echo "[whatsapp-mcp] WARNING: bridge did not respond after 60 s — starting MCP anyway."
    echo "[whatsapp-mcp] Check 'docker logs -f agent-whatsapp-mcp' for QR code or errors."
fi

# ---------------------------------------------------------------------------
# Start FastMCP SSE server
# ---------------------------------------------------------------------------
echo "[whatsapp-mcp] Starting FastMCP SSE server on :${MCP_PORT}..."
exec python /app/mcp_server.py
