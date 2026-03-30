"""Outlook Web router.

Endpoints:
  POST /v1/outlook/list           — list visible inbox emails
  POST /v1/outlook/read           — open and read one email by index
  POST /v1/outlook/list-folders   — list all folders from the nav pane
  POST /v1/outlook/filter         — apply or clear the Unread filter
  POST /v1/outlook/move           — move an email to a named folder
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cdp import (
    evaluate as cdp_evaluate,
    navigate as cdp_navigate,
    press_key as cdp_press_key,
    type_into_focused as cdp_type_into_focused,
)

router = APIRouter()

_OL_HOST = "outlook"
_OL_INBOX = "https://outlook.cloud.microsoft/mail/inbox"

# ---------------------------------------------------------------------------
# JS snippets
# ---------------------------------------------------------------------------

_JS_LIST_EMAILS = """
(function(limit) {
    const items = document.querySelectorAll('[role="listbox"] [role="option"]');
    return Array.from(items).slice(0, limit).map((el, idx) => {
        const label = el.getAttribute('aria-label') || '';
        const convId = el.getAttribute('data-convid') || '';
        const unread = label.toLowerCase().startsWith('unread');
        const leaves = Array.from(el.querySelectorAll('span, div'))
            .filter(s => s.children.length === 0 && (s.innerText || '').trim())
            .filter(s => !/^\(\d+\)$/.test((s.innerText || '').trim()));
        let sender = '', senderEmail = '', subject = '', time = '', preview = '';
        for (const s of leaves) {
            const text = (s.innerText || '').trim();
            const title = s.getAttribute('title') || '';
            if (!time && /^\d{1,2}:\d{2}/.test(text)) { time = text; }
            else if (!sender) { sender = text; senderEmail = title.includes('@') ? title : ''; }
            else if (!subject) { subject = text; }
            else if (!preview) { preview = text; }
        }
        return {index: idx, convId, unread, sender, senderEmail, subject, time, preview};
    });
})(%d)
"""

_JS_READ_HEADER = """
(function() {
    const h3s = Array.from(document.querySelectorAll('[role="heading"][aria-level="3"]'));
    let subject = '', from_ = '', to_ = '', cc_ = '', date_ = '';
    for (const el of h3s) {
        const text = (el.innerText || '').trim();
        if (!text) continue;
        if (el.tagName === 'DIV' && !subject && !text.startsWith('To:') && !text.startsWith('Cc:')
                && !text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)/))
            subject = text.split('\\n')[0];
        if (el.tagName === 'SPAN' && !from_) from_ = text;
        if (text.startsWith('To:')) to_ = text;
        if (text.startsWith('Cc:')) cc_ = text;
        if (text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s/)) date_ = text;
    }
    return {subject, from_: from_, to_: to_, cc_: cc_, date_: date_};
})()
"""

_JS_READ_BODY = """
(function() {
    const doc = document.querySelector('[role="document"]');
    return {body_text: doc ? (doc.innerText || '') : ''};
})()
"""

_JS_LIST_FOLDERS = """
(function() {
    const tree = document.querySelector('[role="tree"]');
    if (!tree) return [];
    const SKIP = new Set(['selected', 'unread', 'starred', 'flagged']);
    return Array.from(tree.querySelectorAll('[role="treeitem"]')).map(el => {
        const lines = (el.innerText || '').split('\\n')
            .map(s => s.trim())
            .filter(s => s.length > 1 && !/^\\d+$/.test(s) && !SKIP.has(s.toLowerCase()));
        return {
            name: lines[0] || '',
            level: parseInt(el.getAttribute('aria-level') || '1'),
        };
    }).filter(f => f.name && f.name.length < 80);
})()
"""

_JS_APPLY_UNREAD_FILTER = """
(function() {
    const btn = Array.from(document.querySelectorAll('button'))
        .find(b => (b.getAttribute('aria-label') || '').trim() === 'Filter');
    if (btn) { btn.click(); return true; }
    return false;
})()
"""

_JS_CLICK_UNREAD_OPTION = """
(function() {
    const els = document.querySelectorAll('button, [role="menuitem"], [role="option"]');
    for (const el of els) {
        if ((el.innerText || '').trim() === 'Unread') { el.click(); return true; }
    }
    return false;
})()
"""

_JS_CLEAR_UNREAD_FILTER = """
(function() {
    for (const el of document.querySelectorAll('button, [role="menuitem"]')) {
        const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
        if (t === 'All' || t === 'Clear filter' || t === 'Filtered: Unread') {
            el.click(); return 'chip';
        }
    }
    const btn = Array.from(document.querySelectorAll('button'))
        .find(b => (b.getAttribute('aria-label') || '').includes('Filter'));
    if (btn) { btn.click(); return 'menu'; }
    return null;
})()
"""

_JS_CLICK_ALL_OPTION = """
(function() {
    for (const el of document.querySelectorAll('button, [role="menuitem"]')) {
        if ((el.innerText || '').trim() === 'All') { el.click(); return true; }
    }
    return false;
})()
"""

_JS_DISMISS_DIALOG = """
(function() {
    const closeBtn = document.querySelector('[role="dialog"] button[aria-label="Close"]');
    if (closeBtn) { closeBtn.click(); return 'close'; }
    const cancel = Array.from(document.querySelectorAll('[role="dialog"] button'))
        .find(b => (b.innerText || '').trim() === 'Cancel');
    if (cancel) { cancel.click(); return 'cancel'; }
    const backdrop = document.querySelector('.fui-DialogSurface__backdrop');
    if (backdrop) { backdrop.click(); return 'backdrop'; }
    return null;
})()
"""

_JS_TREE_FOLDER_NAMES = """
(function() {
    const dialog = document.querySelector('[role="dialog"]');
    if (!dialog) return null;
    return Array.from(dialog.querySelectorAll('[role="treeitem"]')).map(el => {
        const lines = (el.innerText || '').split('\\n').map(s => s.trim()).filter(s => s.length > 1);
        return lines[0] || '';
    }).filter(n => n);
})()
"""

_JS_MOVE_BTN_ENABLED = """
(function() {
    const dialog = document.querySelector('[role="dialog"]');
    if (!dialog) return false;
    const btn = Array.from(dialog.querySelectorAll('button'))
        .find(b => (b.innerText || '').trim() === 'Move');
    return btn ? !btn.disabled : false;
})()
"""


# ---------------------------------------------------------------------------
# Shared login guard
# ---------------------------------------------------------------------------


async def _ensure_outlook() -> None:
    """Navigate to inbox if needed; raise 503 if not logged in."""
    url_result = await cdp_evaluate("window.location.href")
    current = str(url_result.get("result", "")).lower()
    if _OL_HOST not in current or "mail" not in current:
        await cdp_navigate(_OL_INBOX)
        await asyncio.sleep(4)

    check = await cdp_evaluate('!!document.querySelector("[aria-label=\\"New mail\\"]")')
    if not check.get("result"):
        raise HTTPException(
            status_code=503,
            detail="Outlook not logged in. Open VNC (port 6080) and log in manually.",
        )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class OutlookListRequest(BaseModel):
    limit: int = 20
    unread_only: bool = False


class OutlookReadRequest(BaseModel):
    index: int


class OutlookFilterRequest(BaseModel):
    active: bool  # True = apply Unread filter, False = clear it


class OutlookMoveRequest(BaseModel):
    index: int
    folder: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/v1/outlook/list")
async def outlook_list(req: OutlookListRequest) -> dict[str, Any]:
    """List emails from the Outlook inbox visible in the browser."""
    try:
        await _ensure_outlook()
        await asyncio.sleep(1)
        result = await cdp_evaluate(_JS_LIST_EMAILS % req.limit)
        emails = result.get("result") or []
        if req.unread_only:
            emails = [e for e in emails if e.get("unread")]
        return {"emails": emails, "count": len(emails)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/outlook/read")
async def outlook_read(req: OutlookReadRequest) -> dict[str, Any]:
    """Click an inbox email by index and return its subject, from, date, and body."""
    try:
        await _ensure_outlook()
        click_js = (
            f'document.querySelectorAll(\'[role="listbox"] [role="option"]\')[{req.index}]?.click()'
        )
        await cdp_evaluate(click_js)
        await asyncio.sleep(2)

        check = await cdp_evaluate('!!document.querySelector(\'[role="document"]\')')
        if not check.get("result"):
            raise HTTPException(
                status_code=404,
                detail=f"No email at index {req.index} or reading pane did not open.",
            )

        header = await cdp_evaluate(_JS_READ_HEADER)
        body = await cdp_evaluate(_JS_READ_BODY)
        h = header.get("result") or {}
        b = body.get("result") or {}

        return {
            "index": req.index,
            "subject": h.get("subject", ""),
            "from": h.get("from_", ""),
            "to": h.get("to_", ""),
            "cc": h.get("cc_", ""),
            "date": h.get("date_", ""),
            "body_text": b.get("body_text", ""),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/outlook/list-folders")
async def outlook_list_folders() -> dict[str, Any]:
    """List all folders from the Outlook left navigation pane."""
    try:
        await _ensure_outlook()
        result = await cdp_evaluate(_JS_LIST_FOLDERS)
        folders = result.get("result") or []
        return {"folders": folders, "count": len(folders)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/outlook/filter")
async def outlook_filter(req: OutlookFilterRequest) -> dict[str, Any]:
    """Apply (active=true) or clear (active=false) the Unread email filter."""
    try:
        await _ensure_outlook()
        if req.active:
            await cdp_evaluate(_JS_APPLY_UNREAD_FILTER)
            await asyncio.sleep(0.7)
            await cdp_evaluate(_JS_CLICK_UNREAD_OPTION)
            await asyncio.sleep(1)
        else:
            result = await cdp_evaluate(_JS_CLEAR_UNREAD_FILTER)
            await asyncio.sleep(0.5)
            # If we opened the Filter menu (not a chip), click All
            if result.get("result") == "menu":
                await cdp_evaluate(_JS_CLICK_ALL_OPTION)
                await asyncio.sleep(0.5)
        return {"active": req.active, "status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/outlook/move")
async def outlook_move(req: OutlookMoveRequest) -> dict[str, Any]:
    """Move the email at `index` to the folder whose name matches `folder`.

    Uses keyboard-only navigation inside the Move Items dialog to avoid
    Fluent UI portal overlay blocking (React ignores synthetic mouse events).

    Steps:
    1.  Dismiss any open dialog.
    2.  Click email at index via JS.
    3.  Click "Move to" toolbar button via JS.
    4.  Click "Move to a different folder..." in the dropdown via JS.
    5.  Wait for the Move Items dialog.
    6.  Verify the folder exists in the tree.
    7.  JS-focus the search input, type folder name to filter.
    8.  Tab → root header, ArrowDown → target folder (enables Move button).
    9.  Tab × 2 → Move button, Enter to confirm.
    10. Verify dialog closed.
    """
    try:
        await _ensure_outlook()

        # Step 1: dismiss any leftover dialog
        await cdp_evaluate(_JS_DISMISS_DIALOG)
        await asyncio.sleep(0.3)
        await cdp_press_key("Escape")
        await asyncio.sleep(0.5)

        # Step 2: click email at index via JS (bypasses pointer-event interception)
        clicked = await cdp_evaluate(f"""
            (() => {{
                const el = document.querySelectorAll('[role="listbox"] [role="option"]')[{req.index}];
                if (!el) return false;
                el.click();
                return true;
            }})()
        """)
        if not clicked.get("result"):
            raise HTTPException(
                status_code=404, detail=f"Email at index {req.index} not found"
            )
        await asyncio.sleep(2)

        # Step 3: click "Move to" toolbar button via JS
        move_to_clicked = await cdp_evaluate("""
            (() => {
                const btn = document.querySelector('[aria-label="Move to"]');
                if (!btn) return false;
                btn.click();
                return true;
            })()
        """)
        if not move_to_clicked.get("result"):
            raise HTTPException(status_code=502, detail="'Move to' button not found")
        await asyncio.sleep(1.5)

        # Step 4: click "Move to a different folder..." in the dropdown
        diff_clicked = await cdp_evaluate("""
            (() => {
                for (const el of document.querySelectorAll('button, [role="menuitem"]')) {
                    if ((el.innerText || '').includes('Move to a different folder')) {
                        el.click(); return true;
                    }
                }
                return false;
            })()
        """)
        if not diff_clicked.get("result"):
            raise HTTPException(
                status_code=502, detail="'Move to a different folder...' not found"
            )

        # Step 5: wait up to 5s for the Move Items dialog
        for _ in range(10):
            await asyncio.sleep(0.5)
            r = await cdp_evaluate('!!document.querySelector(\'[role="dialog"]\')')
            if r.get("result"):
                break
        else:
            raise HTTPException(
                status_code=502, detail="Move Items dialog did not appear"
            )

        # Step 6: verify folder exists in the tree
        available_r = await cdp_evaluate(_JS_TREE_FOLDER_NAMES)
        available = available_r.get("result")
        if available is None:
            await cdp_press_key("Escape")
            await asyncio.sleep(0.5)
            raise HTTPException(status_code=502, detail="No dialog tree found")

        folder_lower = req.folder.lower()
        matched = next(
            (n for n in available
             if n.lower() == folder_lower or n.lower().startswith(folder_lower)),
            None,
        )
        if not matched:
            await cdp_press_key("Escape")
            await asyncio.sleep(0.5)
            raise HTTPException(
                status_code=404,
                detail=f"Folder '{req.folder}' not found in picker",
                # available[:20] can't go in HTTPException detail directly as list
            )

        # Step 7: JS-focus search input, type folder name to filter tree
        await cdp_evaluate("""
            () => {
                const dialog = document.querySelector('[role="dialog"]');
                if (!dialog) return;
                const input = dialog.querySelector('input');
                if (input) input.focus();
            }
        """)
        await asyncio.sleep(0.2)
        await cdp_type_into_focused(matched, delay_ms=30)
        await asyncio.sleep(0.8)

        # Step 8: Tab → root header, ArrowDown → target folder
        await cdp_press_key("Tab")
        await asyncio.sleep(0.2)
        await cdp_press_key("ArrowDown")
        await asyncio.sleep(0.3)

        move_enabled = await cdp_evaluate(_JS_MOVE_BTN_ENABLED)
        if not move_enabled.get("result"):
            # Extra root node in some accounts — one more ArrowDown
            await cdp_press_key("ArrowDown")
            await asyncio.sleep(0.3)
            move_enabled = await cdp_evaluate(_JS_MOVE_BTN_ENABLED)

        if not move_enabled.get("result"):
            await cdp_press_key("Escape")
            await asyncio.sleep(0.5)
            raise HTTPException(
                status_code=502,
                detail="Move button still disabled after keyboard navigation",
            )

        # Step 9: Tab past "New Folder" → land on "Move" → Enter
        await cdp_press_key("Tab")
        await asyncio.sleep(0.15)
        await cdp_press_key("Tab")
        await asyncio.sleep(0.15)
        await cdp_press_key("Enter")
        await asyncio.sleep(2)

        # Step 10: dialog should be gone on success
        still_open = await cdp_evaluate('!!document.querySelector(\'[role="dialog"]\')')
        if still_open.get("result"):
            await cdp_press_key("Escape")
            await asyncio.sleep(0.5)
            raise HTTPException(
                status_code=502,
                detail="Dialog still open after Enter — move may have failed",
            )

        return {"status": "moved", "index": req.index, "folder": matched}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
