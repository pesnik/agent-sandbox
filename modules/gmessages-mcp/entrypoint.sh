#!/bin/sh
set -e

SESSION_FILE="/data/.local/share/openmessage/session.json"
mkdir -p "$(dirname "$SESSION_FILE")"

# Create a stub iMessage DB with the expected schema so openmessage doesn't warn
IMESSAGE_DB="/data/Library/Messages/chat.db"
if [ ! -f "$IMESSAGE_DB" ]; then
    mkdir -p "$(dirname "$IMESSAGE_DB")"
    sqlite3 "$IMESSAGE_DB" "
CREATE TABLE IF NOT EXISTS chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL,
    style INTEGER, state INTEGER, account_id TEXT, properties BLOB,
    chat_identifier TEXT, service_name TEXT, room_name TEXT,
    account_login TEXT, is_archived INTEGER DEFAULT 0,
    last_addressed_handle TEXT, display_name TEXT, group_id TEXT,
    is_filtered INTEGER DEFAULT 0, successful_query INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT UNIQUE NOT NULL, text TEXT, handle_id INTEGER DEFAULT 0,
    service TEXT, account_guid TEXT, date INTEGER DEFAULT 0,
    date_read INTEGER DEFAULT 0, date_delivered INTEGER DEFAULT 0,
    is_from_me INTEGER DEFAULT 0, is_read INTEGER DEFAULT 0,
    is_sent INTEGER DEFAULT 0, is_delivered INTEGER DEFAULT 0,
    cache_has_attachments INTEGER DEFAULT 0, subject TEXT,
    country TEXT, type INTEGER DEFAULT 0, service_center TEXT,
    is_service_message INTEGER DEFAULT 0, is_forward INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL, country TEXT, service TEXT NOT NULL,
    uncanonicalized_id TEXT, person_centric_id TEXT
);
CREATE TABLE IF NOT EXISTS chat_message_join (
    chat_id INTEGER REFERENCES chat (ROWID) ON DELETE CASCADE,
    message_id INTEGER REFERENCES message (ROWID) ON DELETE CASCADE,
    message_date INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS chat_handle_join (
    chat_id INTEGER REFERENCES chat (ROWID) ON DELETE CASCADE,
    handle_id INTEGER REFERENCES handle (ROWID) ON DELETE CASCADE,
    PRIMARY KEY (chat_id, handle_id)
);
" > /dev/null 2>&1
fi

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
