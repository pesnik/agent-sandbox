# =============================================================================
# Google Messages MCP — OpenMessage (libgm / mautrix-gmessages)
#
# OpenMessage is a single Go binary that:
#   - Pairs with your Android's Google Messages app via QR code
#   - Serves a web UI at :7007/ for pairing and status
#   - Exposes MCP SSE at :7007/mcp/sse
#
# Source: https://github.com/MaxGhenis/openmessage
#
# NOTE: Google is migrating Messages for Web from QR pairing to Google Account
# sign-in. If this breaks, check upstream for protocol updates.
# =============================================================================

FROM golang:1.23-alpine AS builder
RUN apk add --no-cache git ca-certificates

WORKDIR /src
RUN git clone --depth 1 https://github.com/MaxGhenis/openmessage .

# Try root package first; if main is in cmd/, adjust accordingly
RUN go build -o /openmessage . 2>/dev/null || \
    go build -o /openmessage ./cmd/openmessage/ 2>/dev/null || \
    go build -o /openmessage ./cmd/

# --- Runtime ---
FROM alpine:3.19
RUN apk add --no-cache ca-certificates curl

COPY --from=builder /openmessage /usr/local/bin/openmessage

# Data directory for session token and message cache
RUN mkdir -p /data

# OpenMessage uses $HOME to resolve ~/.local/share/openmessage/
# Override HOME so data lands in the mounted volume
ENV HOME=/data
ENV PORT=7007

EXPOSE 7007

# The binary serves on PORT when not invoked over stdio
CMD ["/usr/local/bin/openmessage"]
