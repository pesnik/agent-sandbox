"""WhatsApp Web tools: list chats, read chat, send message."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.types import Tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WA_INPUT_SEL = 'footer div[contenteditable="true"]'
_WA_URL = "web.whatsapp.com"

_JS_WA_LIST_CHATS = """
(function(limit) {
    const rows = document.querySelectorAll('#pane-side span[title]');
    const seen = new Set();
    const chats = [];
    for (const el of rows) {
        const name = el.getAttribute('title') || '';
        if (!name || seen.has(name)) continue;
        seen.add(name);
        const row = el.closest('[role="listitem"]') || el.parentElement;
        let time = '', preview = '';
        if (row) {
            const texts = Array.from(row.querySelectorAll('span'))
                .map(s => s.children.length === 0 ? (s.innerText || '').trim() : '')
                .filter(t => t && t !== name);
            time = texts.find(t => /^\d{1,2}:\d{2}/.test(t) || t === 'Yesterday' || /^\d{1,2}\//.test(t)) || '';
            preview = texts.filter(t => t !== time).join(' ').slice(0, 80);
        }
        chats.push({name, time, preview});
        if (chats.length >= limit) break;
    }
    return chats;
})(%d)
"""

_JS_WA_READ_MESSAGES = """
(function(limit) {
    const withMeta = document.querySelectorAll('[data-pre-plain-text]');
    if (withMeta.length > 0) {
        return Array.from(withMeta).slice(-limit).map(el => {
            const meta = el.getAttribute('data-pre-plain-text') || '';
            const match = meta.match(/\[([^\]]+)\]\s*([^:]+):\s*/);
            const time   = match ? match[1].trim() : '';
            const sender = match ? match[2].trim() : '';
            const textEl = el.querySelector('.copyable-text');
            const text   = textEl ? textEl.innerText.trim() : el.innerText.trim();
            return {time, sender, text};
        }).filter(m => m.text);
    }
    const bubbles = document.querySelectorAll('.message-in .copyable-text, .message-out .copyable-text');
    return Array.from(bubbles).slice(-limit).map(el => {
        const row = el.closest('.message-in, .message-out');
        const direction = row && row.classList.contains('message-out') ? 'You' : 'Them';
        const tsEl = row && row.querySelector('span[class*="time"], span._ahhn');
        const time = (tsEl && tsEl.innerText.trim()) || '';
        return {time, sender: direction, text: el.innerText.trim()};
    }).filter(m => m.text);
})(%d)
"""

# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="whatsapp_list_chats",
        description=(
            "List recent WhatsApp chats visible in the sidebar. "
            "Returns name, last message preview, and timestamp for each. "
            "WhatsApp Web must be open and logged in via VNC."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max chats to return", "default": 20},
            },
        },
    ),
    Tool(
        name="whatsapp_read_chat",
        description=(
            "Open a WhatsApp chat and return the last N messages with sender and timestamp. "
            "Accepts a contact/group name (e.g. 'EDE Internal') or a phone number."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chat":  {"type": "string", "description": "Contact/group name or phone number"},
                "limit": {"type": "integer", "description": "Number of recent messages to return", "default": 20},
            },
            "required": ["chat"],
        },
    ),
    Tool(
        name="whatsapp_send_message",
        description=(
            "Send a WhatsApp message to a contact, group, or phone number. "
            "WhatsApp Web must be open and logged in via VNC."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Contact/group name or phone number"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["to", "message"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_phone(value: str) -> bool:
    stripped = value.lstrip("+").replace(" ", "").replace("-", "")
    return stripped.isdigit() and len(stripped) >= 7


async def _whatsapp_ensure_open() -> dict[str, Any]:
    from cdp import evaluate_in_tab, navigate_in_tab
    url_result = await evaluate_in_tab("window.location.href", _WA_URL)
    current = str(url_result.get("result", ""))
    if "web.whatsapp.com" not in current:
        await navigate_in_tab("https://web.whatsapp.com", _WA_URL)
        await asyncio.sleep(6)
    check = await evaluate_in_tab('!!document.querySelector("#pane-side")', _WA_URL)
    if not check.get("result"):
        return {"error": "WhatsApp not logged in. Open VNC (port 6080) and scan the QR code."}
    return {"status": "ok"}


async def _whatsapp_open_chat(chat: str) -> dict[str, Any]:
    from cdp import _dispatch_click, _open_session, evaluate_in_tab, navigate_in_tab
    if _is_phone(chat):
        phone = chat.lstrip("+").replace(" ", "").replace("-", "")
        login = await _whatsapp_ensure_open()
        if "error" in login:
            return login
        await navigate_in_tab(f"https://web.whatsapp.com/send?phone={phone}", _WA_URL)
        await asyncio.sleep(6)
        check = await evaluate_in_tab(f'!!document.querySelector("{_WA_INPUT_SEL}")', _WA_URL)
        if not check.get("result"):
            return {"error": f"Failed to open chat for {chat}. Phone number may be invalid."}
        return {"status": "ok"}

    # Name-based: real click via CDP to fire React events
    login = await _whatsapp_ensure_open()
    if "error" in login:
        return login
    safe = json.dumps(chat.lower())
    coords_js = f"""
    (() => {{
        const rows = Array.from(document.querySelectorAll('#pane-side span[title]'));
        const target = rows.find(el => el.getAttribute('title').toLowerCase().includes({safe}));
        if (!target) return null;
        const item = target.closest('[role="listitem"]') || target.parentElement;
        if (!item) return null;
        const rect = item.getBoundingClientRect();
        return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
    }})()
    """
    coords = await evaluate_in_tab(coords_js, _WA_URL)
    pos = coords.get("result")
    if not pos:
        return {"error": f"Chat '{chat}' not found in WhatsApp sidebar."}
    http, cdp = await _open_session(url_contains=_WA_URL)
    try:
        await _dispatch_click(cdp, pos["x"], pos["y"])
    finally:
        await cdp.close()
        await http.close()
    await asyncio.sleep(3)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


async def _whatsapp_list_chats(limit: int = 20) -> dict[str, Any]:
    from cdp import evaluate_in_tab
    login = await _whatsapp_ensure_open()
    if "error" in login:
        return login
    result = await evaluate_in_tab(_JS_WA_LIST_CHATS % limit, _WA_URL)
    chats = result.get("result") or []
    return {"chats": chats, "count": len(chats)}


async def _whatsapp_read_chat(chat: str, limit: int = 20) -> dict[str, Any]:
    from cdp import evaluate_in_tab
    opened = await _whatsapp_open_chat(chat)
    if "error" in opened:
        return opened
    await asyncio.sleep(1)
    result = await evaluate_in_tab(_JS_WA_READ_MESSAGES % limit, _WA_URL)
    messages = result.get("result") or []
    return {"chat": chat, "messages": messages, "count": len(messages)}


async def _whatsapp_send_message(to: str, message: str) -> dict[str, Any]:
    from cdp import evaluate_in_tab, type_text_in_tab
    opened = await _whatsapp_open_chat(to)
    if "error" in opened:
        return opened
    await asyncio.sleep(1)
    await type_text_in_tab(_WA_INPUT_SEL, message, _WA_URL)
    await asyncio.sleep(0.5)
    await evaluate_in_tab(f"""
    (() => {{
        const inp = document.querySelector('{_WA_INPUT_SEL}');
        if (inp) {{
            inp.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', code:'Enter', keyCode:13, bubbles:true}}));
            inp.dispatchEvent(new KeyboardEvent('keyup',  {{key:'Enter', code:'Enter', keyCode:13, bubbles:true}}));
        }}
    }})()
    """, _WA_URL)
    await asyncio.sleep(1)
    return {"status": "sent", "to": to, "message": message}


# ---------------------------------------------------------------------------
# Handler wrappers
# ---------------------------------------------------------------------------


async def _h_whatsapp_list_chats(a: dict) -> dict:
    return await _whatsapp_list_chats(limit=a.get("limit", 20))


async def _h_whatsapp_read_chat(a: dict) -> dict:
    return await _whatsapp_read_chat(chat=a["chat"], limit=a.get("limit", 20))


async def _h_whatsapp_send_message(a: dict) -> dict:
    return await _whatsapp_send_message(to=a["to"], message=a["message"])


HANDLERS: dict = {
    "whatsapp_list_chats":   _h_whatsapp_list_chats,
    "whatsapp_read_chat":    _h_whatsapp_read_chat,
    "whatsapp_send_message": _h_whatsapp_send_message,
}
