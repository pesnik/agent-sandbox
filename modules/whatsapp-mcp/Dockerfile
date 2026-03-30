# =============================================================================
# WhatsApp MCP — Go bridge (whatsmeow) + Python FastMCP SSE server
#
# Stage 1: Build the Go bridge from pesnik/whatsapp-mcp
# Stage 2: Python runtime with FastMCP SSE server
# =============================================================================

# --- Stage 1: Go bridge binary ---
FROM golang:1.23-alpine AS go-builder
RUN apk add --no-cache git gcc musl-dev sqlite-dev

WORKDIR /src
# Clone whatsapp-mcp (your fork); the Go bridge lives in whatsapp-bridge/
RUN git clone --depth 1 https://github.com/pesnik/whatsapp-mcp .

WORKDIR /src/whatsapp-bridge
# CGO required for go-sqlite3 (whatsmeow's SQLite store)
RUN CGO_ENABLED=1 GOOS=linux go build -o /whatsapp-bridge .

# --- Stage 2: Python runtime ---
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl libsqlite3-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Go bridge binary
COPY --from=go-builder /whatsapp-bridge /usr/local/bin/whatsapp-bridge

# Python MCP server
WORKDIR /app
COPY requirements.txt mcp_server.py ./
RUN pip install --no-cache-dir -r requirements.txt

# Data directory — mounted as a named volume at runtime
RUN mkdir -p /data

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 8080: Go bridge REST API (internal only)
# 8081: FastMCP SSE endpoint (exposed to host / nginx)
EXPOSE 8080 8081

ENTRYPOINT ["/entrypoint.sh"]
