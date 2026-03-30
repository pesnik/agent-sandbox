"""WhatsApp Web router."""

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
    evaluate_in_tab as cdp_evaluate_in_tab,
)

router = APIRouter()

_WA_HOST = "web.whatsapp.com"

_JS_WA_FIND_CHAT = """
(function(name) {
    const rows = Array.from(document.querySelectorAll('#pane-side span[title]'));
    const target = rows.find(el => el.getAttribute('title').toLowerCase().includes(name));
    if (!target) return null;
    const item = target.closest('[role="listitem"]') || target.parentElement;
    if (!item) return null;
    item.scrollIntoView({block: 'center'});
    const rect = item.getBoundingClientRect();
    return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
})(%s)
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


class WhatsAppReadRequest(BaseModel):
    chat: str
    limit: int = 20


@router.post("/v1/whatsapp/read")
async def whatsapp_read(req: WhatsAppReadRequest) -> dict[str, Any]:
    """Open a WhatsApp chat by name and return the last N messages.

    Targets the WhatsApp Web tab (web.whatsapp.com) without disrupting it.
    Returns messages with time, sender, and text fields.
    """
    try:
        url_result = await cdp_evaluate_in_tab("window.location.href", _WA_HOST)
        if "error" in url_result:
            raise HTTPException(
                status_code=503,
                detail="WhatsApp Web tab not found. Open WhatsApp Web and log in.",
            )

        check = await cdp_evaluate_in_tab('!!document.querySelector("#pane-side")', _WA_HOST)
        if not check.get("result"):
            raise HTTPException(
                status_code=503,
                detail="WhatsApp not logged in. Scan QR code via VNC (port 6080).",
            )

        safe_name = json.dumps(req.chat.lower())
        coords = await cdp_evaluate_in_tab(_JS_WA_FIND_CHAT % safe_name, _WA_HOST)
        pos = coords.get("result")
        if not pos:
            raise HTTPException(
                status_code=404,
                detail=f"Chat '{req.chat}' not found in WhatsApp sidebar.",
            )

        http, cdp = await _open_session(url_contains=_WA_HOST)
        try:
            await _dispatch_click(cdp, pos["x"], pos["y"])
        finally:
            await cdp.close()
            await http.close()

        await asyncio.sleep(2)

        result = await cdp_evaluate_in_tab(_JS_WA_READ_MESSAGES % req.limit, _WA_HOST)
        messages = result.get("result") or []

        return {"chat": req.chat, "messages": messages, "count": len(messages)}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
