"""
WhatsApp MCP — FastMCP SSE server wrapping the whatsmeow Go bridge.

Architecture:
  Go bridge  (port 8080, internal) — manages WhatsApp session via whatsmeow,
                                     writes SQLite DBs, exposes REST for sends.
  This server (port 8081, external) — reads SQLite for listing/search,
                                      calls Go bridge REST for sends.

Schema (written by the Go bridge to /data/store/messages.db):
  chats(jid, name, last_message_time)
  messages(id, chat_jid, sender, content, timestamp, is_from_me,
           media_type, filename, url, media_key, file_sha256,
           file_enc_sha256, file_length)
  timestamp: ISO-8601 string (e.g. "2026-04-05 05:28:16+00:00")
  is_from_me: 0 | 1

NOTE: /data/messages.db is a separate empty file created at startup.
The actual message store is always at /data/store/messages.db.

REST API (Go bridge at WHATSAPP_BRIDGE_URL):
  POST /send  {"to": "JID_OR_PHONE", "text": "..."}  → {"status": "sent"}
"""
import os
import sqlite3
import json
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP

BRIDGE_URL = os.environ.get("WHATSAPP_BRIDGE_URL", "http://localhost:8080")
DB_PATH    = os.environ.get("WHATSAPP_DB_PATH", "/data/store/messages.db")
PORT       = int(os.environ.get("MCP_PORT", "8081"))

mcp = FastMCP("whatsapp-mcp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    """Open messages.db read-only, return Row-factory connection."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _jid(phone_or_jid: str) -> str:
    """Normalise a phone number or partial JID to a full WhatsApp JID."""
    s = phone_or_jid.strip()
    if "@" in s:
        return s
    # Strip common prefixes that users might include
    s = s.lstrip("+").replace(" ", "").replace("-", "")
    return f"{s}@s.whatsapp.net"


def _rows_to_list(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def whatsapp_list_chats(limit: int = 20) -> list[dict]:
    """
    List WhatsApp chats sorted by most recent message.
    Returns: [{chat_jid, name, last_timestamp, last_text}]
    """
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT
                c.jid       AS chat_jid,
                c.name      AS name,
                c.last_message_time AS last_timestamp,
                m.content   AS last_text
            FROM chats c
            LEFT JOIN messages m ON m.id = (
                SELECT id FROM messages
                WHERE chat_jid = c.jid
                ORDER BY timestamp DESC LIMIT 1
            )
            ORDER BY c.last_message_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return _rows_to_list(rows)


@mcp.tool()
def whatsapp_read_chat(chat: str, limit: int = 20) -> list[dict]:
    """
    Read messages from a WhatsApp chat.

    chat: phone number (with country code), contact name (partial match), or full JID.
    Returns messages ordered newest-first: [{flow, timestamp, push_name, text}]
    """
    with _db() as conn:
        # 1. Try exact JID match
        jid = _jid(chat)
        rows = conn.execute(
            "SELECT is_from_me AS flow, timestamp, sender, content AS text "
            "FROM messages WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?",
            (jid, limit),
        ).fetchall()

        # 2. Fall back: chat name partial match → resolve to JID
        if not rows:
            hit = conn.execute(
                "SELECT jid FROM chats WHERE name LIKE ? LIMIT 1",
                (f"%{chat}%",),
            ).fetchone()
            if hit:
                rows = conn.execute(
                    "SELECT is_from_me AS flow, timestamp, sender, content AS text "
                    "FROM messages WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?",
                    (hit["jid"], limit),
                ).fetchall()

    return _rows_to_list(rows)


@mcp.tool()
def whatsapp_search_contacts(query: str) -> list[dict]:
    """
    Search contacts by name or phone number.
    Returns [{chat_jid, name}] from known chat participants.
    """
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT jid AS chat_jid, name
            FROM chats
            WHERE name LIKE ? OR jid LIKE ?
            ORDER BY name
            LIMIT 20
            """,
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
    return _rows_to_list(rows)


@mcp.tool()
async def whatsapp_send_message(to: str, message: str) -> dict:
    """
    Send a WhatsApp message.

    to: phone number with country code (e.g. "8801XXXXXXXXX") or full JID.
    Returns the bridge response ({"status": "sent"} on success).
    """
    jid = _jid(to)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{BRIDGE_URL}/send",
            json={"to": jid, "text": message},
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # FastMCP >= 1.0 exposes sse_app() → Starlette app with /sse + /messages
    uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=PORT, log_level="info")
