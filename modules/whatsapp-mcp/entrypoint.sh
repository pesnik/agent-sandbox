#!/bin/bash
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data}"
BRIDGE_PORT="${BRIDGE_PORT:-8080}"
MCP_PORT="${MCP_PORT:-8081}"

echo "[whatsapp-mcp] Starting Go bridge on :${BRIDGE_PORT} (data: ${DATA_DIR})..."
cd "$DATA_DIR"

/usr/local/bin/whatsapp-bridge > /tmp/bridge.log 2>&1 &
BRIDGE_PID=$!
echo "[whatsapp-mcp] Bridge PID: $BRIDGE_PID"

echo "[whatsapp-mcp] Waiting for bridge (scan QR if first run)..."
for i in $(seq 1 60); do
    if curl -sf "http://localhost:${BRIDGE_PORT}/" >/dev/null 2>&1 || \
       curl -sf "http://localhost:${BRIDGE_PORT}/health" >/dev/null 2>&1; then
        echo "[whatsapp-mcp] Bridge is ready after $i seconds"
        break
    fi
    echo "[whatsapp-mcp] Waiting... $i/60"
    sleep 1
done

echo "[whatsapp-mcp] Starting FastMCP SSE server on :${MCP_PORT}..."
echo "[whatsapp-mcp] Running: python /app/mcp_server.py"
python /app/mcp_server.py
