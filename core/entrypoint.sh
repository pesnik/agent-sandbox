#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Remove any stale X lock files from previous runs
# ---------------------------------------------------------------------------
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1

# ---------------------------------------------------------------------------
# Copy any enabled module supervisord confs into the global conf.d
# ---------------------------------------------------------------------------
if ls /sandbox/modules/enabled/*.conf 2>/dev/null | grep -q .; then
    cp -f /sandbox/modules/enabled/*.conf /etc/supervisor/conf.d/
    echo "[entrypoint] Loaded module configs:"
    ls /sandbox/modules/enabled/*.conf
else
    echo "[entrypoint] No module configs found in /sandbox/modules/enabled/"
fi

# ---------------------------------------------------------------------------
# Generate nginx config from template using BASE_PATH env var
# BASE_PATH example: /ede-sandbox  (leave empty for root serving)
# ---------------------------------------------------------------------------
BASE_PATH="${BASE_PATH:-}"
BASE_PATH_TRIM="${BASE_PATH#/}"
if [ -n "$BASE_PATH_TRIM" ]; then
    NOVNC_WEBSOCKIFY_PATH="${BASE_PATH_TRIM}/websockify"
else
    NOVNC_WEBSOCKIFY_PATH="websockify"
fi
export BASE_PATH BASE_PATH_TRIM NOVNC_WEBSOCKIFY_PATH
envsubst '${BASE_PATH}${BASE_PATH_TRIM}${NOVNC_WEBSOCKIFY_PATH}' \
    < /etc/nginx/conf.d/default.conf.tpl \
    > /etc/nginx/conf.d/default.conf
echo "[entrypoint] nginx base path: '${BASE_PATH:-/}'"

# ---------------------------------------------------------------------------
# Ensure nginx log directory exists
# ---------------------------------------------------------------------------
mkdir -p /var/log/nginx /var/run

# ---------------------------------------------------------------------------
# Start supervisord (foreground — this is PID 1)
# ---------------------------------------------------------------------------
echo "[entrypoint] Starting supervisord..."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
