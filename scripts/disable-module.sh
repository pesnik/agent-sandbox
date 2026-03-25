#!/bin/bash
# ---------------------------------------------------------------------------
# disable-module.sh — Remove module supervisord configs from modules/enabled/
#
# Usage:
#   ./scripts/disable-module.sh <module> [module2 ...]
#
# Example:
#   ./scripts/disable-module.sh vscode sms
#
# Restart the sandbox container after disabling modules.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
ENABLED_DIR="${REPO_ROOT}/modules/enabled"

if [ $# -eq 0 ]; then
    echo "Usage: $(basename "$0") <module> [module2 ...]"
    echo ""
    echo "Currently enabled modules:"
    if ls "${ENABLED_DIR}"/*.conf 2>/dev/null | grep -q .; then
        for f in "${ENABLED_DIR}"/*.conf; do
            echo "  $(basename "$f" .conf)"
        done
    else
        echo "  (none)"
    fi
    exit 1
fi

for module in "$@"; do
    conf="${ENABLED_DIR}/${module}.conf"
    if [ ! -f "$conf" ]; then
        echo "WARNING: Module '${module}' is not currently enabled — skipping." >&2
        continue
    fi
    rm "$conf"
    echo "Disabled: ${module}"
done

echo ""
echo "Restart the sandbox container to apply changes:"
echo "  docker compose restart sandbox"
