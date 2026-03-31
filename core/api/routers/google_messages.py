"""Google Messages router."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cdp import (
    _dispatch_click,
    _open_session,
    evaluate as cdp_evaluate,
    click_at as cdp_click_at,
    navigate as cdp_navigate,
)

router = APIRouter()

_GM_HOST = "messages.google.com"

_JS_GM_GET_MESSAGES = """
(function(limit) {
    const items = document.querySelectorAll('mws-tombstone-message-wrapper, mws-message-wrapper');
    const result = [];
    let currentDate = '';

    let currentTombstoneTime = '';

    for (const item of items) {
        if (item.nodeName === 'MWS-TOMBSTONE-MESSAGE-WRAPPER') {
            const raw = (item.textContent || '')
                .replace(/\\u00A0/g, ' ')
                .replace(/\\u202F/g, ' ')
                .trim();
            if (raw) {
                const parts = raw.split('\\u00B7').map(s => s.trim());
                const dayPart = parts[0] || '';
                const timePart = parts[1] || '';
                if (dayPart && !dayPart.match(/^\\d{1,2}:\\d{2}/)) {
                    currentDate = dayPart;
                } else {
                    currentDate = 'today';
                }
                currentTombstoneTime = timePart;
            }
            continue;
        }

        const textEl = item.querySelector('.text-msg-content, [data-e2e-message-text-content]');
        const text = textEl ? textEl.innerText.trim() : '';
        if (!text) continue;

        const absTs = item.querySelector('mws-absolute-timestamp');
        const relTs = item.querySelector('mws-relative-timestamp, .timestamp');
        const rawTime = absTs ? absTs.textContent : (relTs ? relTs.innerText : '');
        const time = rawTime.replace(/\\u202F/g, ' ').trim();

        const isOutgoing = item.getAttribute('is-outgoing') === 'true';
        const senderEl = item.querySelector('.sender-name, [data-e2e-sender-name]');
        const sender = senderEl ? senderEl.innerText.trim() : (isOutgoing ? 'Me' : '');
        const msgId = item.getAttribute('msg-id') || '';

        result.push({
            text, time, date: currentDate,
            tombstone_time: currentTombstoneTime,
            is_outgoing: isOutgoing, sender, msg_id: msgId
        });
    }

    return result.filter(m => !m.is_outgoing).slice(-limit);
})(%d)
"""

_JS_SCROLL_UP = """(() => {
    const container = document.querySelector('mws-bottom-anchored.container');
    if (container) container.scrollTop = 0;
    return document.querySelectorAll('mws-message-wrapper').length;
})()"""

_JS_FIND_CHAT = """
(function(name) {
    // Scroll sidebar to top so recently-used chats are visible
    const nav = document.querySelector('nav.conversation-list');
    if (nav) nav.scrollTop = 0;
    let items = document.querySelectorAll('mws-conversation-list-item');
    if (!items.length) items = document.querySelectorAll('a[href*="conversations/"]');
    const lower = name.toLowerCase();
    for (const el of items) {
        const nameEl = el.querySelector('.name, [data-e2e-conversation-name], h3') || {innerText: ''};
        if (nameEl.innerText.trim().toLowerCase().includes(lower)) {
            el.scrollIntoView({block: 'center'});
            const rect = el.getBoundingClientRect();
            return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
        }
    }
    return null;
})(%s)
"""


class GoogleMessagesReadRequest(BaseModel):
    chat: str
    limit: int = 20


@router.post("/v1/google-messages/read")
async def google_messages_read(req: GoogleMessagesReadRequest) -> dict[str, Any]:
    """Read messages from a Google Messages conversation.

    Handles scrolling to load older messages when limit > 25.
    Returns messages with date (tombstone day name) and time (absolute timestamp).
    """
    try:
        url_result = await cdp_evaluate("window.location.href")
        current = str(url_result.get("result", ""))
        gm_base = f"https://{_GM_HOST}/web/conversations"
        if _GM_HOST not in current or current.rstrip("/") != gm_base.rstrip("/"):
            await cdp_navigate(gm_base)

        # Poll for conversation list instead of blind sleep
        safe_name = json.dumps(req.chat.lower())
        pos = None
        for _ in range(15):
            await asyncio.sleep(1)
            coords = await cdp_evaluate(_JS_FIND_CHAT % safe_name)
            pos = coords.get("result")
            if pos:
                break
        if not pos:
            raise HTTPException(
                status_code=404, detail=f"Conversation '{req.chat}' not found"
            )

        await cdp_click_at(pos["x"], pos["y"])
        # Poll for messages to appear instead of blind sleep
        for _ in range(10):
            await asyncio.sleep(1)
            check = await cdp_evaluate("document.querySelectorAll('mws-message-wrapper').length")
            if (check.get("result") or 0) > 0:
                break

        if req.limit > 25:
            max_scrolls = max(10, req.limit // 25)
            prev_count = 0
            for _ in range(max_scrolls):
                await cdp_evaluate(_JS_SCROLL_UP)
                # Poll for new messages to load after scroll (up to 5s)
                current_count = prev_count
                for _ in range(5):
                    await asyncio.sleep(1)
                    scroll_result = await cdp_evaluate(_JS_SCROLL_UP)
                    current_count = scroll_result.get("result", 0) or 0
                    if current_count != prev_count:
                        break
                if current_count >= req.limit or current_count == prev_count:
                    break
                prev_count = current_count

        result = await cdp_evaluate(_JS_GM_GET_MESSAGES % req.limit)
        messages = result.get("result") or []

        return {"chat": req.chat, "messages": messages, "count": len(messages)}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
