"""Google Messages Web tools: list chats, read chat, send message."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.types import Tool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GM_URL = "https://messages.google.com/web/conversations"
_GM_HOST = "messages.google.com"
_GM_COMPOSE_SEL = (
    '[contenteditable="true"][aria-label*="message" i], '
    "[data-e2e-message-input-field], "
    "mws-autosize-textarea textarea"
)
_GM_SEND_SEL = (
    "[data-e2e-send-button], "
    'button[aria-label*="Send" i], '
    '[aria-label="Send SMS message" i]'
)

_JS_GM_LIST_CHATS = """
(function(limit) {
    let items = document.querySelectorAll('mws-conversation-list-item');
    if (!items.length) items = document.querySelectorAll('a[href*="conversations/"]');
    return Array.from(items).slice(0, limit).map((el, idx) => {
        const name = (el.querySelector('.name, [data-e2e-conversation-name], h3') || {innerText: ''}).innerText.trim();
        const snippet = (el.querySelector('.snippet-text, [data-e2e-conversation-snippet], .latest-message') || {innerText: ''}).innerText.trim();
        const timestamp = (el.querySelector('mws-relative-timestamp, .timestamp') || {innerText: ''}).innerText.trim();
        const unread = el.classList.contains('unread')
            || !!el.querySelector('.unread-count, .unread')
            || (el.getAttribute('aria-label') || '').toLowerCase().includes('unread');
        const href = el.getAttribute('href') || (el.querySelector('a') || {getAttribute: () => ''}).getAttribute('href') || '';
        const convId = (href.match(/conversations\/([^/?]+)/) || [])[1] || '';
        return {index: idx, convId, name, snippet, timestamp, unread: !!unread};
    });
})(%d)
"""

_JS_GM_GET_MESSAGES = """
(function(limit) {
    // Read all items including tombstone date separators
    const items = document.querySelectorAll('mws-tombstone-message-wrapper, mws-message-wrapper');
    const result = [];
    let currentDate = '';

    for (const item of items) {
        if (item.nodeName === 'MWS-TOMBSTONE-MESSAGE-WRAPPER') {
            // Tombstone = date separator. Format: "Monday \u00b7 2:35 AM" or "2:35 AM"
            const raw = (item.textContent || '').replace(/\\u00A0/g, ' ').trim();
            if (raw) {
                const parts = raw.split('\\u00B7').map(s => s.trim());
                const dayPart = parts[0] || '';
                if (dayPart && !dayPart.match(/^\\d{1,2}:\\d{2}/)) {
                    // Has a day name like "Saturday"
                    currentDate = dayPart;
                } else {
                    // Time-only tombstone = today
                    currentDate = 'today';
                }
            }
            continue;
        }

        const textEl = item.querySelector('.text-msg-content, [data-e2e-message-text-content]');
        const text = textEl ? textEl.innerText.trim() : '';
        if (!text) continue;

        // Prefer absolute timestamp, fall back to relative
        const absTs = item.querySelector('mws-absolute-timestamp');
        const relTs = item.querySelector('mws-relative-timestamp, .timestamp');
        const time = absTs ? absTs.textContent.trim() : (relTs ? relTs.innerText.trim() : '');

        const isOutgoing = item.classList.contains('outgoing')
            || !!item.closest('.outgoing')
            || item.getAttribute('data-e2e-is-outgoing') === 'true';
        const senderEl = item.querySelector('.sender-name, [data-e2e-sender-name]');
        const sender = senderEl ? senderEl.innerText.trim() : (isOutgoing ? 'Me' : '');

        result.push({text, time, date: currentDate, is_outgoing: isOutgoing, sender});
    }

    return result.filter(m => !m.is_outgoing).slice(-limit);
})(%d)
"""

# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="google_messages_list_chats",
        description=(
            "List recent SMS conversations from Google Messages Web (messages.google.com). "
            "Returns contact name, snippet, timestamp, and unread status. "
            "Google Messages must be paired and open in the VNC browser."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max conversations to return",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="google_messages_read_chat",
        description=(
            "Open an SMS conversation in Google Messages Web and return recent messages. "
            "Accepts a contact name (partial match) or a conversation index from google_messages_list_chats. "
            "Each message includes: text, time (absolute if available, e.g. '2:35 AM'), "
            "date (day name from tombstone separator, e.g. 'Saturday', 'Monday'), "
            "is_outgoing, and sender."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chat": {
                    "type": "string",
                    "description": "Contact name (partial match) or conversation index",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent messages to return",
                    "default": 20,
                },
            },
            "required": ["chat"],
        },
    ),
    Tool(
        name="google_messages_send_message",
        description=(
            "Send an SMS via Google Messages Web. "
            "For existing conversations provide the contact name. "
            "For new conversations provide a phone number — the Start Chat flow will be used."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Contact name (existing) or phone number (new)",
                },
                "message": {"type": "string", "description": "SMS text to send"},
            },
            "required": ["to", "message"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _google_messages_ensure_open() -> dict[str, Any]:
    from cdp import evaluate_in_tab, navigate_in_tab

    url_result = await evaluate_in_tab("window.location.href", _GM_HOST)
    current = str(url_result.get("result", ""))
    if "messages.google.com" not in current:
        await navigate_in_tab(_GM_URL, _GM_HOST)
        await asyncio.sleep(5)
    check = await evaluate_in_tab(
        "!!document.querySelector(\"mws-conversations-list, mws-conversation-list-item, a[href*='conversations/']\")",
        _GM_HOST,
    )
    if not check.get("result"):
        return {
            "error": "Google Messages not paired. Open VNC (port 6080) and scan the QR code."
        }
    return {"status": "ok"}


async def _google_messages_open_chat(chat: str) -> dict[str, Any]:
    from cdp import _dispatch_click, _open_session, evaluate_in_tab

    login = await _google_messages_ensure_open()
    if "error" in login:
        return login

    if chat.isdigit():
        coords_js = f"""
        (() => {{
            let items = document.querySelectorAll('mws-conversation-list-item');
            if (!items.length) items = document.querySelectorAll('a[href*="conversations/"]');
            const el = items[{int(chat)}];
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
        }})()
        """
    else:
        safe = json.dumps(chat.lower())
        coords_js = f"""
        (() => {{
            let items = document.querySelectorAll('mws-conversation-list-item');
            if (!items.length) items = document.querySelectorAll('a[href*="conversations/"]');
            const lower = {safe};
            for (const el of items) {{
                const nameEl = el.querySelector('.name, [data-e2e-conversation-name], h3') || {{innerText: ''}};
                if (nameEl.innerText.trim().toLowerCase().includes(lower)) {{
                    const rect = el.getBoundingClientRect();
                    return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
                }}
            }}
            return null;
        }})()
        """

    coords = await evaluate_in_tab(coords_js, _GM_HOST)
    pos = coords.get("result")
    if not pos:
        return {"error": f"Conversation '{chat}' not found in Google Messages."}
    http, cdp = await _open_session(url_contains=_GM_HOST)
    try:
        await _dispatch_click(cdp, pos["x"], pos["y"])
    finally:
        await cdp.close()
        await http.close()
    await asyncio.sleep(2)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


async def _google_messages_list_chats(limit: int = 20) -> dict[str, Any]:
    from cdp import evaluate_in_tab

    login = await _google_messages_ensure_open()
    if "error" in login:
        return login
    await asyncio.sleep(1)
    result = await evaluate_in_tab(_JS_GM_LIST_CHATS % limit, _GM_HOST)
    chats = result.get("result") or []
    return {"chats": chats, "count": len(chats)}


async def _google_messages_read_chat(chat: str, limit: int = 20) -> dict[str, Any]:
    from cdp import evaluate_in_tab

    opened = await _google_messages_open_chat(chat)
    if "error" in opened:
        return opened
    await asyncio.sleep(2)

    # Scroll up to load older messages (Google Messages uses virtual scrolling)
    if limit > 25:
        _JS_SCROLL = """(() => {
            const container = document.querySelector('mws-bottom-anchored.container');
            if (container) container.scrollTop = 0;
            return document.querySelectorAll('mws-message-wrapper').length;
        })()"""
        prev_count = 0
        for _ in range(10):
            scroll_result = await evaluate_in_tab(_JS_SCROLL, _GM_HOST)
            current_count = scroll_result.get("result", 0) or 0
            if current_count >= limit or current_count == prev_count:
                break
            prev_count = current_count
            await asyncio.sleep(2)

    result = await evaluate_in_tab(_JS_GM_GET_MESSAGES % limit, _GM_HOST)
    messages = result.get("result") or []
    return {"chat": chat, "messages": messages, "count": len(messages)}


async def _google_messages_send_message(to: str, message: str) -> dict[str, Any]:
    from cdp import evaluate_in_tab, type_text_in_tab

    login = await _google_messages_ensure_open()
    if "error" in login:
        return login

    is_phone = (
        to.lstrip("+").replace(" ", "").replace("-", "").isdigit()
        and len(to.lstrip("+").replace(" ", "").replace("-", "")) >= 7
    )

    if is_phone:
        fab_result = await evaluate_in_tab(
            """
        (() => {
            const fab = document.querySelector('[data-e2e-start-chat-fab], [aria-label="Start chat" i], a[href*="new"]');
            if (!fab) return 'NOT_FOUND';
            fab.click(); return 'CLICKED';
        })()
        """,
            _GM_HOST,
        )
        if fab_result.get("result") == "NOT_FOUND":
            return {"error": "Could not find 'Start chat' button in Google Messages."}
        await asyncio.sleep(1)
        input_selectors = [
            "[data-e2e-contact-input]",
            'input[placeholder*="name" i]',
            'input[placeholder*="number" i]',
            'input[aria-label*="recipient" i]',
            'input[aria-label*="To" i]',
        ]
        typed = False
        for sel in input_selectors:
            res = await evaluate_in_tab(f'!!document.querySelector("{sel}")', _GM_HOST)
            if res.get("result"):
                await type_text_in_tab(sel, to, _GM_HOST)
                typed = True
                break
        if not typed:
            return {"error": "Could not find recipient input in Google Messages."}
        await asyncio.sleep(1.5)
        await evaluate_in_tab(
            """
        (() => {
            const el = document.activeElement || document.body;
            el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', keyCode:13, bubbles:true}));
        })()
        """,
            _GM_HOST,
        )
        await asyncio.sleep(1.5)
    else:
        opened = await _google_messages_open_chat(to)
        if "error" in opened:
            return opened

    compose_found = False
    for sel in _GM_COMPOSE_SEL.split(", "):
        res = await evaluate_in_tab(f'!!document.querySelector("{sel}")', _GM_HOST)
        if res.get("result"):
            await type_text_in_tab(sel, message, _GM_HOST)
            compose_found = True
            break
    if not compose_found:
        return {"error": "Could not find message compose field."}

    await asyncio.sleep(0.5)

    send_clicked = False
    for sel in _GM_SEND_SEL.split(", "):
        res = await evaluate_in_tab(f'!!document.querySelector("{sel}")', _GM_HOST)
        if res.get("result"):
            await evaluate_in_tab(f'document.querySelector("{sel}").click()', _GM_HOST)
            send_clicked = True
            break
    if not send_clicked:
        await evaluate_in_tab(
            """
        (() => {
            const el = document.activeElement || document.body;
            el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', keyCode:13, bubbles:true}));
        })()
        """,
            _GM_HOST,
        )

    await asyncio.sleep(1)
    return {"status": "sent", "to": to, "message": message}


# ---------------------------------------------------------------------------
# Handler wrappers
# ---------------------------------------------------------------------------


async def _h_google_messages_list_chats(a: dict) -> dict:
    return await _google_messages_list_chats(limit=a.get("limit", 20))


async def _h_google_messages_read_chat(a: dict) -> dict:
    return await _google_messages_read_chat(chat=a["chat"], limit=a.get("limit", 20))


async def _h_google_messages_send_message(a: dict) -> dict:
    return await _google_messages_send_message(to=a["to"], message=a["message"])


HANDLERS: dict = {
    "google_messages_list_chats": _h_google_messages_list_chats,
    "google_messages_read_chat": _h_google_messages_read_chat,
    "google_messages_send_message": _h_google_messages_send_message,
}
