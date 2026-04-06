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

REST API (this server — for polling agents like TigerClaw):
  GET /api/chats?limit=N
      → [{jid, name, last_message_time}]
  GET /api/chats/{chat}/messages?limit=N&since_ms=EPOCH_MS
      chat: JID, phone number, or partial name
      since_ms: only return messages with timestamp > this epoch-ms value (optional)
      → [{id, jid, name, sender, text, timestamp, ts_ms}] oldest-first
"""
import os
import sqlite3
import json
from datetime import datetime, timezone
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

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
# REST API — for polling agents (TigerClaw etc.) that can't use MCP SSE
# ---------------------------------------------------------------------------

def _ts_to_ms(ts: str) -> int:
    """Convert ISO-8601 timestamp string to Unix milliseconds."""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


async def rest_list_chats(request: Request) -> JSONResponse:
    """GET /api/chats?limit=N → [{jid, name, last_message_time}]"""
    limit = int(request.query_params.get("limit", 200))
    with _db() as conn:
        rows = conn.execute(
            "SELECT jid, name, last_message_time FROM chats "
            "ORDER BY last_message_time DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return JSONResponse(_rows_to_list(rows))


async def rest_chat_messages(request: Request) -> JSONResponse:
    """
    GET /api/chats/{chat}/messages?limit=N&since_ms=EPOCH_MS
    Returns inbound messages (is_from_me=0) oldest-first.
    """
    chat = request.path_params["chat"]
    limit = int(request.query_params.get("limit", 50))
    since_ms = int(request.query_params.get("since_ms", 0))

    with _db() as conn:
        # Resolve chat → JID: try exact JID, then name partial match
        jid = _jid(chat)
        if not conn.execute("SELECT 1 FROM chats WHERE jid = ?", (jid,)).fetchone():
            hit = conn.execute(
                "SELECT jid FROM chats WHERE name LIKE ? LIMIT 1",
                (f"%{chat}%",),
            ).fetchone()
            if hit:
                jid = hit["jid"]

        # Fetch name for this chat
        _name_row = conn.execute("SELECT name FROM chats WHERE jid = ?", (jid,)).fetchone()
        chat_name = _name_row["name"] if _name_row else chat

        if since_ms > 0:
            since_iso = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat()
            rows = conn.execute(
                "SELECT id, sender, content AS text, timestamp FROM messages "
                "WHERE chat_jid = ? AND is_from_me = 0 AND timestamp > ? "
                "ORDER BY timestamp ASC LIMIT ?",
                (jid, since_iso, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, sender, content AS text, timestamp FROM messages "
                "WHERE chat_jid = ? AND is_from_me = 0 "
                "ORDER BY timestamp DESC LIMIT ?",
                (jid, limit),
            ).fetchall()

    messages = []
    for r in rows:
        d = dict(r)
        d["jid"] = jid
        d["name"] = chat_name
        d["ts_ms"] = _ts_to_ms(d.get("timestamp", ""))
        messages.append(d)

    # Always return oldest-first
    messages.sort(key=lambda m: m["ts_ms"])
    return JSONResponse(messages)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Compose: REST routes first, then FastMCP SSE app as fallback
    app = Starlette(routes=[
        Route("/api/chats", rest_list_chats),
        Route("/api/chats/{chat:path}/messages", rest_chat_messages),
        Mount("/", app=mcp.sse_app()),
    ])
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
