#!/bin/sh
set -e

SESSION_FILE="/data/.local/share/openmessage/session.json"
mkdir -p "$(dirname "$SESSION_FILE")"

if [ ! -f "$SESSION_FILE" ]; then
    echo "[gmessages-mcp] No session found — starting QR pairing."
    echo "[gmessages-mcp] Scan the QR code with Google Messages on your phone:"
    echo "[gmessages-mcp]   Messages → profile icon → Device pairing → Pair new device"
    echo ""
    /usr/local/bin/openmessage pair
    echo ""
    echo "[gmessages-mcp] Paired successfully. Starting serve..."
fi

exec /usr/local/bin/openmessage serve
