"""
WhatsApp MCP — FastMCP SSE server wrapping the whatsmeow Go bridge.

Architecture:
  Go bridge  (port 8080, internal) — manages WhatsApp session via whatsmeow,
                                     writes SQLite DBs, exposes REST for sends.
  This server (port 8081, external) — reads SQLite for listing/search,
                                      calls Go bridge REST for sends.

Schema (messages.db written by the Go bridge, from pesnik/whatsapp-mcp):
  messages(id, chat_jid, flow, timestamp, push_name, text, media_type, has_media)
  flow: "inbound" | "outbound"

REST API (Go bridge at WHATSAPP_BRIDGE_URL):
  POST /send  {"to": "JID_OR_PHONE", "text": "..."}  → {"status": "sent"}

If the schema or REST path differs in your fork, adjust the queries/endpoints below.
"""
import os
import sqlite3
import json
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP

os.environ["STARLETTE_TRUSTED_HOSTS"] = "*"

BRIDGE_URL = os.environ.get("WHATSAPP_BRIDGE_URL", "http://localhost:8080")
DB_PATH    = os.environ.get("WHATSAPP_DB_PATH", "/data/messages.db")
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
                chat_jid,
                push_name  AS name,
                MAX(timestamp) AS last_timestamp,
                text       AS last_text
            FROM messages
            GROUP BY chat_jid
            ORDER BY last_timestamp DESC
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
            "SELECT flow, timestamp, push_name, text FROM messages "
            "WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?",
            (jid, limit),
        ).fetchall()

        # 2. Fall back: name/push_name partial match → resolve to JID
        if not rows:
            hit = conn.execute(
                "SELECT chat_jid FROM messages WHERE push_name LIKE ? LIMIT 1",
                (f"%{chat}%",),
            ).fetchone()
            if hit:
                rows = conn.execute(
                    "SELECT flow, timestamp, push_name, text FROM messages "
                    "WHERE chat_jid = ? ORDER BY timestamp DESC LIMIT ?",
                    (hit["chat_jid"], limit),
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
            SELECT DISTINCT chat_jid, push_name AS name
            FROM messages
            WHERE push_name LIKE ? OR chat_jid LIKE ?
            ORDER BY push_name
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
    import sys
    import os
    
    os.environ.setdefault("STARLETTE_TRUSTED_HOSTS", "*")
    
    print(f"Starting MCP server on port {PORT}", file=sys.stderr)
    sys.stderr.flush()
    
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    
    mcp_app = mcp.sse_app()
    
    async def root(request):
        return JSONResponse({"status": "ok", "mcp": "whatsapp-mcp"})
    
    app = Starlette(
        routes=[
            Route("/", root),
            Route("/sse", mcp_app),
            Route("/sse/", mcp_app),
        ]
    )
    
    print(f"MCP app created, starting uvicorn on 0.0.0.0:{PORT}", file=sys.stderr)
    sys.stderr.flush()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
