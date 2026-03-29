"""Outlook Web tools: list, read, search, move, send, reply, forward."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.types import Tool

OUTLOOK_URL: str = os.getenv("OUTLOOK_URL", "https://outlook.office.com")

# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

_OL_SEL = {
    "new_mail":        '[aria-label="New mail"]',
    "email_list":      '[role="listbox"]',
    "email_item":      '[role="listbox"] [role="option"]',
    "reading_pane":    '[role="document"]',
    "search_input":    '#topSearchInput, input[aria-label*="Search"]',
    "to_field":        'div[aria-label="To"]',
    "cc_field":        'div[aria-label="Cc"]',
    "subject_field":   'input[placeholder="Add a subject"]',
    "body_field":      'div[aria-label="Message body, press Alt+F10 to exit"]',
    "send_button":     'button[aria-label="Send"]',
    "reply_button":    'button[aria-label="Reply"], [role="menuitem"][aria-label="Reply"]',
    "reply_all_button":'button[aria-label="Reply all"], [role="menuitem"][aria-label="Reply all"]',
    "forward_button":  'button[aria-label="Forward"], [role="menuitem"][aria-label="Forward"]',
}

# ---------------------------------------------------------------------------
# JavaScript snippets
# ---------------------------------------------------------------------------

# Extract email rows from the inbox list
_JS_LIST_EMAILS = """
(function(limit) {
    const items = document.querySelectorAll('[role="listbox"] [role="option"]');
    return Array.from(items).slice(0, limit).map((el, idx) => {
        const label = el.getAttribute('aria-label') || '';
        const convId = el.getAttribute('data-convid') || '';
        const unread = label.toLowerCase().startsWith('unread');
        const leaves = Array.from(el.querySelectorAll('span, div'))
            .filter(s => s.children.length === 0 && (s.innerText || '').trim());
        let sender = '', senderEmail = '', subject = '', time = '', timeFull = '', preview = '';
        for (const s of leaves) {
            const text = (s.innerText || '').trim();
            const title = s.getAttribute('title') || '';
            if (!sender && title.includes('@')) { sender = text; senderEmail = title; }
            else if (!subject && sender && !time) { subject = text; }
            else if (!time && /\d{1,2}:\d{2}/.test(text)) { time = text; timeFull = title || text; }
            else if (sender && subject && time && !preview) { preview = text; }
        }
        return {index: idx, convId, unread, sender, senderEmail, subject, time, timeFull, preview};
    });
})(%d)
"""

# Extract header fields from the reading pane
_JS_READ_HEADER = """
(function() {
    const h3s = Array.from(document.querySelectorAll('[role="heading"][aria-level="3"]'));
    let subject = '', from_ = '', to_ = '', cc_ = '', date_ = '';
    for (const el of h3s) {
        const text = (el.innerText || '').trim();
        if (!text) continue;
        if (el.tagName === 'DIV' && !subject && !text.startsWith('To:') && !text.startsWith('Cc:')
                && !text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)/))
            subject = text.split('\n')[0];
        if (el.tagName === 'SPAN' && text.includes('@') && !from_) from_ = text;
        if (text.startsWith('To:')) to_ = text;
        if (text.startsWith('Cc:')) cc_ = text;
        if (text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s/)) date_ = text;
    }
    return {subject, from_: from_, to_: to_, cc_: cc_, date_: date_};
})()
"""

# Extract body text from the reading pane
_JS_READ_BODY = """
(function() {
    const doc = document.querySelector('[role="document"]');
    if (!doc) return {body_text: ''};
    return {body_text: doc.innerText || ''};
})()
"""

# Extract folder tree from the left navigation pane
_JS_LIST_FOLDERS = """
(function() {
    const tree = document.querySelector('[role="tree"]');
    if (!tree) return [];
    const SKIP = new Set(['selected', 'unread', 'starred', 'flagged']);
    return Array.from(tree.querySelectorAll('[role="treeitem"]')).map(el => {
        const lines = (el.innerText || '').split('\n')
            .map(s => s.trim())
            .filter(s => s.length > 1 && !/^\d+$/.test(s) && !SKIP.has(s.toLowerCase()));
        const name = lines[0] || '';
        return {
            name,
            level: parseInt(el.getAttribute('aria-level') || '1'),
        };
    }).filter(f => f.name && f.name.length < 80);
})()
"""

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="outlook_list_emails",
        description=(
            "List emails from the Outlook inbox visible in the browser. "
            "Returns sender, subject, time, unread flag, and preview for each. "
            "Outlook must be open and logged in (via VNC or local runtime)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max emails to return", "default": 10},
            },
        },
    ),
    Tool(
        name="outlook_list_unread",
        description=(
            "List only unread emails from the Outlook inbox. "
            "Scans up to `scan_limit` emails and returns those flagged as unread. "
            "Use this before outlook_move_email to get the current unread indexes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "scan_limit": {
                    "type": "integer",
                    "description": "How many inbox rows to scan for unread emails",
                    "default": 50,
                },
            },
        },
    ),
    Tool(
        name="outlook_list_folders",
        description=(
            "List all mail folders shown in the Outlook left navigation pane. "
            "Returns folder names and nesting level. "
            "Use this to discover valid target folders before calling outlook_move_email."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="outlook_read_email",
        description=(
            "Click an email at the given index in the Outlook inbox and return its full content "
            "(subject, from, to, cc, date, body text)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "Email index in the list (0-based)"},
            },
            "required": ["index"],
        },
    ),
    Tool(
        name="outlook_move_email",
        description=(
            "Move the email at the given index to a named folder. "
            "First call outlook_list_folders to see available folder names, "
            "and outlook_list_unread to get current indexes. "
            "After moving, remaining email indexes shift — always re-list before the next move."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "index": {
                    "type": "integer",
                    "description": "Email index in the current inbox list (0-based)",
                },
                "folder": {
                    "type": "string",
                    "description": "Exact or partial name of the destination folder",
                },
            },
            "required": ["index", "folder"],
        },
    ),
    Tool(
        name="outlook_search_emails",
        description="Search Outlook emails using the search bar and return matching results.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query text"},
                "limit": {"type": "integer", "description": "Max results to return", "default": 10},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="outlook_send_email",
        description=(
            "Compose and send a new email via Outlook Web. "
            "Clicks New Mail, fills To/Subject/Body, and clicks Send."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to":      {"type": "string", "description": "Recipient address(es), comma-separated"},
                "subject": {"type": "string", "description": "Email subject"},
                "body":    {"type": "string", "description": "Email body text"},
                "cc":      {"type": "string", "description": "CC address(es), comma-separated", "default": ""},
            },
            "required": ["to", "subject", "body"],
        },
    ),
    Tool(
        name="outlook_reply_email",
        description=(
            "Reply (or reply-all) to the currently open email in Outlook. "
            "Use outlook_read_email first to open the email you want to reply to."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "body":      {"type": "string", "description": "Reply body text"},
                "reply_all": {"type": "boolean", "description": "Reply-all instead of reply", "default": False},
            },
            "required": ["body"],
        },
    ),
    Tool(
        name="outlook_forward_email",
        description=(
            "Forward the currently open email in Outlook to new recipient(s). "
            "Use outlook_read_email first to open the email you want to forward."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to":   {"type": "string", "description": "Recipient address(es), comma-separated"},
                "body": {"type": "string", "description": "Optional message to prepend", "default": ""},
            },
            "required": ["to"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


async def _outlook_ensure_mail() -> dict[str, Any]:
    """Navigate to Outlook mail if not already there, verify login."""
    from cdp import evaluate, navigate
    url_result = await evaluate("window.location.href")
    current = str(url_result.get("result", "")).lower()
    if "outlook" not in current or "mail" not in current:
        await navigate(f"{OUTLOOK_URL}/mail/")
        await asyncio.sleep(3)
    check = await evaluate(f'!!document.querySelector(\'{_OL_SEL["new_mail"]}\')')
    if not check.get("result"):
        return {"error": "Not logged in. Open VNC (port 6080) and log into Outlook manually."}
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


async def _outlook_list_emails(limit: int = 10) -> dict[str, Any]:
    from cdp import evaluate
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    await asyncio.sleep(1)
    result = await evaluate(_JS_LIST_EMAILS % limit)
    return {"emails": result.get("result", [])}


async def _outlook_list_unread(scan_limit: int = 50) -> dict[str, Any]:
    """List only unread emails by scanning up to scan_limit inbox rows."""
    from cdp import evaluate
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    await asyncio.sleep(1)
    result = await evaluate(_JS_LIST_EMAILS % scan_limit)
    all_emails = result.get("result", [])
    unread = [e for e in all_emails if e.get("unread")]
    return {"unread_count": len(unread), "emails": unread}


async def _outlook_list_folders() -> dict[str, Any]:
    """List folders from the Outlook left navigation pane."""
    from cdp import evaluate
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    result = await evaluate(_JS_LIST_FOLDERS)
    folders = result.get("result", [])
    return {"folders": folders, "count": len(folders)}


async def _outlook_read_email(index: int) -> dict[str, Any]:
    from cdp import evaluate
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    click_js = f'document.querySelectorAll(\'{_OL_SEL["email_item"]}\')[{index}]?.click()'
    await evaluate(click_js)
    await asyncio.sleep(2)
    check = await evaluate(f'!!document.querySelector(\'{_OL_SEL["reading_pane"]}\')')
    if not check.get("result"):
        return {"error": "Reading pane did not appear after clicking email"}
    header = await evaluate(_JS_READ_HEADER)
    body = await evaluate(_JS_READ_BODY)
    h = header.get("result", {})
    b = body.get("result", {})
    return {
        "index": index,
        "subject":   h.get("subject", ""),
        "from":      h.get("from_", ""),
        "to":        h.get("to_", ""),
        "cc":        h.get("cc_", ""),
        "date":      h.get("date_", ""),
        "body_text": b.get("body_text", ""),
    }


async def _outlook_move_email(index: int, folder: str) -> dict[str, Any]:
    """
    Move the email at `index` to `folder`.

    Strategy:
    1. Click email to open it in the reading pane.
    2. Look for a Move toolbar button.
    3. If not found, open the "More actions" (…) menu and look there.
    4. As a last resort, right-click the email item for context menu.
    5. In the resulting submenu / folder picker, click the matching folder.
    """
    from cdp import evaluate
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login

    # Step 1: click the email to select it / open reading pane
    await evaluate(f"""
        const el = document.querySelectorAll('{_OL_SEL["email_item"]}')[{index}];
        if (el) el.click();
    """)
    await asyncio.sleep(1.5)

    # Step 2: try the direct "Move to" toolbar button
    found = await evaluate("""
    (function() {
        const candidates = [
            '[aria-label="Move to"]',
            '[aria-label="Move"]',
            'button[title*="Move"]',
        ];
        for (const sel of candidates) {
            const el = document.querySelector(sel);
            if (el) { el.click(); return {ok: true, via: sel}; }
        }
        return {ok: false};
    })()
    """)

    if not (found.get("result") or {}).get("ok"):
        # Step 3: open the "More actions" (…) ellipsis menu
        await evaluate("""
        (function() {
            const more = document.querySelector(
                '[aria-label="More actions"], [aria-label="More email actions"], '
                + '[aria-label="More commands"], button[title="More"]'
            );
            if (more) more.click();
        })()
        """)
        await asyncio.sleep(0.8)

        # Now look for Move inside the dropdown
        found = await evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
            const btn = items.find(el => {
                const t = (el.getAttribute('aria-label') || el.innerText || '').toLowerCase();
                return t.includes('move') && !t.includes('sweep');
            });
            if (btn) { btn.click(); return {ok: true, via: 'more_menu'}; }
            return {ok: false};
        })()
        """)

    if not (found.get("result") or {}).get("ok"):
        # Step 4: right-click context menu fallback
        await evaluate(f"""
        (function() {{
            const el = document.querySelectorAll('{_OL_SEL["email_item"]}')[{index}];
            if (el) el.dispatchEvent(new MouseEvent('contextmenu', {{bubbles: true, button: 2}}));
        }})()
        """)
        await asyncio.sleep(0.8)
        found = await evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll('[role="menuitem"]'));
            const btn = items.find(el => {
                const t = (el.getAttribute('aria-label') || el.innerText || '').toLowerCase();
                return t.includes('move') && !t.includes('sweep');
            });
            if (btn) { btn.click(); return {ok: true, via: 'context_menu'}; }
            return {ok: false};
        })()
        """)

    if not (found.get("result") or {}).get("ok"):
        return {"error": "Could not find a Move action for this email", "index": index}

    await asyncio.sleep(1)

    # Step 5: select the target folder from the picker / submenu
    folder_lower = folder.lower()
    pick = await evaluate(f"""
    (function() {{
        const selectors = '[role="menuitem"], [role="option"], [role="treeitem"], button';
        const candidates = Array.from(document.querySelectorAll(selectors));
        const btn = candidates.find(el => {{
            const t = (
                el.getAttribute('aria-label')
                || el.getAttribute('title')
                || el.innerText
                || ''
            ).trim().toLowerCase();
            return t === '{folder_lower}' || t.startsWith('{folder_lower}');
        }});
        if (!btn) {{
            const available = candidates
                .map(e => (e.getAttribute('aria-label') || e.innerText || '').trim())
                .filter(t => t && t.length < 60)
                .slice(0, 25);
            return {{ok: false, available}};
        }}
        btn.click();
        return {{ok: true, matched: btn.getAttribute('aria-label') || btn.innerText}};
    }})()
    """)

    r = pick.get("result") or {}
    if not r.get("ok"):
        return {
            "error":     f"Folder '{folder}' not found in the move picker",
            "available": r.get("available", []),
            "index":     index,
        }

    await asyncio.sleep(1)
    return {"status": "moved", "index": index, "folder": r.get("matched", folder)}


async def _outlook_search_emails(query: str, limit: int = 10) -> dict[str, Any]:
    from cdp import click, evaluate, type_text
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    await click(_OL_SEL["search_input"])
    await asyncio.sleep(0.5)
    await type_text(_OL_SEL["search_input"], query)
    await asyncio.sleep(0.5)
    await evaluate("""
        document.querySelector('#topSearchInput, input[aria-label*="Search"]')
            ?.dispatchEvent(new KeyboardEvent('keydown',
                {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
    """)
    await asyncio.sleep(3)
    result = await evaluate(_JS_LIST_EMAILS % limit)
    return {"query": query, "emails": result.get("result", [])}


async def _outlook_send_email(to: str, subject: str, body: str, cc: str = "") -> dict[str, Any]:
    from cdp import click, evaluate, type_text
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    await click(_OL_SEL["new_mail"])
    await asyncio.sleep(2)
    await click(_OL_SEL["to_field"])
    await asyncio.sleep(0.3)
    for addr in to.split(","):
        await type_text(_OL_SEL["to_field"], addr.strip())
        await asyncio.sleep(0.3)
        await evaluate("""
            document.querySelector('div[aria-label="To"]')
                ?.dispatchEvent(new KeyboardEvent('keydown',
                    {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
        """)
        await asyncio.sleep(0.3)
    if cc:
        await evaluate("""
            document.querySelector('button[aria-label="Show Cc"]')?.click()
        """)
        await asyncio.sleep(0.5)
        await click(_OL_SEL["cc_field"])
        for addr in cc.split(","):
            await type_text(_OL_SEL["cc_field"], addr.strip())
            await asyncio.sleep(0.3)
            await evaluate("""
                document.querySelector('div[aria-label="Cc"]')
                    ?.dispatchEvent(new KeyboardEvent('keydown',
                        {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
            """)
            await asyncio.sleep(0.3)
    await click(_OL_SEL["subject_field"])
    await type_text(_OL_SEL["subject_field"], subject)
    await click(_OL_SEL["body_field"])
    await asyncio.sleep(0.3)
    await type_text(_OL_SEL["body_field"], body)
    await asyncio.sleep(0.5)
    await click(_OL_SEL["send_button"])
    await asyncio.sleep(2)
    return {"status": "sent", "to": to, "subject": subject}


async def _outlook_reply_email(body: str, reply_all: bool = False) -> dict[str, Any]:
    from cdp import click, type_text
    sel = _OL_SEL["reply_all_button"] if reply_all else _OL_SEL["reply_button"]
    for s in sel.split(", "):
        result = await click(s.strip())
        if result.get("status") == "ok":
            break
    await asyncio.sleep(2)
    await click(_OL_SEL["body_field"])
    await asyncio.sleep(0.3)
    await type_text(_OL_SEL["body_field"], body)
    await asyncio.sleep(0.5)
    await click(_OL_SEL["send_button"])
    await asyncio.sleep(2)
    return {"status": "sent", "action": "reply_all" if reply_all else "reply"}


async def _outlook_forward_email(to: str, body: str = "") -> dict[str, Any]:
    from cdp import click, evaluate, type_text
    sel = _OL_SEL["forward_button"]
    for s in sel.split(", "):
        result = await click(s.strip())
        if result.get("status") == "ok":
            break
    await asyncio.sleep(2)
    await click(_OL_SEL["to_field"])
    for addr in to.split(","):
        await type_text(_OL_SEL["to_field"], addr.strip())
        await asyncio.sleep(0.3)
        await evaluate("""
            document.querySelector('div[aria-label="To"]')
                ?.dispatchEvent(new KeyboardEvent('keydown',
                    {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
        """)
        await asyncio.sleep(0.3)
    if body:
        await click(_OL_SEL["body_field"])
        await asyncio.sleep(0.3)
        await type_text(_OL_SEL["body_field"], body)
    await asyncio.sleep(0.5)
    await click(_OL_SEL["send_button"])
    await asyncio.sleep(2)
    return {"status": "sent", "action": "forward", "to": to}


# ---------------------------------------------------------------------------
# Handler wrappers
# ---------------------------------------------------------------------------


async def _h_outlook_list_emails(a: dict) -> dict:
    return await _outlook_list_emails(limit=a.get("limit", 10))


async def _h_outlook_list_unread(a: dict) -> dict:
    return await _outlook_list_unread(scan_limit=a.get("scan_limit", 50))


async def _h_outlook_list_folders(a: dict) -> dict:
    return await _outlook_list_folders()


async def _h_outlook_read_email(a: dict) -> dict:
    return await _outlook_read_email(index=a["index"])


async def _h_outlook_move_email(a: dict) -> dict:
    return await _outlook_move_email(index=a["index"], folder=a["folder"])


async def _h_outlook_search_emails(a: dict) -> dict:
    return await _outlook_search_emails(query=a["query"], limit=a.get("limit", 10))


async def _h_outlook_send_email(a: dict) -> dict:
    return await _outlook_send_email(
        to=a["to"], subject=a["subject"], body=a["body"], cc=a.get("cc", "")
    )


async def _h_outlook_reply_email(a: dict) -> dict:
    return await _outlook_reply_email(body=a["body"], reply_all=a.get("reply_all", False))


async def _h_outlook_forward_email(a: dict) -> dict:
    return await _outlook_forward_email(to=a["to"], body=a.get("body", ""))


HANDLERS: dict = {
    "outlook_list_emails":   _h_outlook_list_emails,
    "outlook_list_unread":   _h_outlook_list_unread,
    "outlook_list_folders":  _h_outlook_list_folders,
    "outlook_read_email":    _h_outlook_read_email,
    "outlook_move_email":    _h_outlook_move_email,
    "outlook_search_emails": _h_outlook_search_emails,
    "outlook_send_email":    _h_outlook_send_email,
    "outlook_reply_email":   _h_outlook_reply_email,
    "outlook_forward_email": _h_outlook_forward_email,
}
