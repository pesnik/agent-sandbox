#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Set up VNC password
# ---------------------------------------------------------------------------
mkdir -p ~/.vnc
echo "${VNC_PASSWORD:-sandbox}" | vncpasswd -f > ~/.vnc/passwd
chmod 600 ~/.vnc/passwd

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
# Ensure nginx log directory exists
# ---------------------------------------------------------------------------
mkdir -p /var/log/nginx /var/run

# ---------------------------------------------------------------------------
# Start supervisord (foreground — this is PID 1)
# ---------------------------------------------------------------------------
echo "[entrypoint] Starting supervisord..."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
