#!/bin/bash
# ---------------------------------------------------------------------------
# enable-module.sh — Copy module supervisord configs into modules/enabled/
#
# Usage:
#   ./scripts/enable-module.sh <module> [module2 ...]
#
# Example:
#   ./scripts/enable-module.sh browser vscode sms
#
# The core container mounts ./modules as /sandbox/modules:ro and the
# entrypoint copies /sandbox/modules/enabled/*.conf into /etc/supervisor/conf.d/
# on startup. Restart the container after enabling modules.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENABLED_DIR="${REPO_ROOT}/modules/enabled"

if [ $# -eq 0 ]; then
    echo "Usage: $(basename "$0") <module> [module2 ...]"
    echo ""
    echo "Available modules:"
    for dir in "${REPO_ROOT}/modules"/*/; do
        name="$(basename "$dir")"
        if [ -f "${dir}supervisord.conf" ]; then
            echo "  $name"
        fi
    done
    exit 1
fi

mkdir -p "$ENABLED_DIR"

for module in "$@"; do
    conf="${REPO_ROOT}/modules/${module}/supervisord.conf"
    if [ ! -f "$conf" ]; then
        echo "WARNING: No supervisord.conf found for module '${module}' — skipping." >&2
        continue
    fi
    dest="${ENABLED_DIR}/${module}.conf"
    cp "$conf" "$dest"
    echo "Enabled: ${module}  →  ${dest}"
done

echo ""
echo "Restart the sandbox container to apply changes:"
echo "  docker compose restart sandbox"
