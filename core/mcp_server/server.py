"""
server.py — MCP server for the agent-sandbox.

Exposes tools over HTTP/SSE on port 8079:
  - shell_execute, file_read, file_write, file_list, file_delete
  - browser_navigate, browser_screenshot, browser_click, browser_type, browser_evaluate
  - outlook_list_emails, outlook_read_email, outlook_search_emails,
    outlook_send_email, outlook_reply_email, outlook_forward_email
  - whatsapp_list_chats, whatsapp_read_chat, whatsapp_send_message
  - google_messages_list_chats, google_messages_read_chat, google_messages_send_message
  - android_send_sms, android_screenshot

Start with:
    uvicorn server:create_app --factory --host 0.0.0.0 --port 8079
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import stat
import sys
from typing import Any, Sequence

# Allow importing cdp from the API directory (Docker path)
sys.path.insert(0, "/opt/sandbox/api")

import aiofiles
import aiofiles.os
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import (
    ImageContent,
    TextContent,
    Tool,
)
from starlette.applications import Starlette
from starlette.routing import Mount, Route

import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_server")

ADB_HOST: str = os.getenv("ADB_HOST", "localhost")

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

server = Server("agent-sandbox")


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="shell_execute",
        description="Run a shell command and return stdout, stderr, and exit code.",
        inputSchema={
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory", "default": "/root"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["cmd"],
        },
    ),
    Tool(
        name="file_read",
        description="Read a file and return its content.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="file_write",
        description="Write content to a file, creating it if necessary. Returns bytes written.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to file"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="file_list",
        description="List entries in a directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="file_delete",
        description="Delete a file or empty directory.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file or empty dir to delete"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="browser_navigate",
        description="Navigate the browser to a URL.",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="browser_screenshot",
        description="Capture a screenshot of the current browser page. Returns base64 PNG.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="browser_click",
        description="Click the first element matching a CSS selector.",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector"},
            },
            "required": ["selector"],
        },
    ),
    Tool(
        name="browser_type",
        description="Focus an element and type text into it.",
        inputSchema={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
    ),
    Tool(
        name="browser_evaluate",
        description="Evaluate JavaScript in the browser page context and return the result.",
        inputSchema={
            "type": "object",
            "properties": {
                "js": {"type": "string", "description": "JavaScript expression or statement"},
            },
            "required": ["js"],
        },
    ),
    # --- Outlook ---
    Tool(
        name="outlook_list_emails",
        description=(
            "List emails from the Outlook inbox visible in the browser. "
            "Returns sender, subject, time, preview for each email. "
            "Outlook must be open and logged in (via VNC)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max emails to return", "default": 10},
            },
        },
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
        name="outlook_search_emails",
        description=(
            "Search Outlook emails using the search bar and return matching results."
        ),
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
                "to": {"type": "string", "description": "Recipient address(es), comma-separated"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
                "cc": {"type": "string", "description": "CC address(es), comma-separated", "default": ""},
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
                "body": {"type": "string", "description": "Reply body text"},
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
                "to": {"type": "string", "description": "Recipient address(es), comma-separated"},
                "body": {"type": "string", "description": "Optional message to add", "default": ""},
            },
            "required": ["to"],
        },
    ),
    # --- Google Messages ---
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
                "limit": {"type": "integer", "description": "Max conversations to return", "default": 20},
            },
        },
    ),
    Tool(
        name="google_messages_read_chat",
        description=(
            "Open an SMS conversation in Google Messages Web and return recent messages. "
            "Accepts a contact name (partial match, e.g. 'Mom') or a conversation index from google_messages_list_chats."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "Contact name (partial match) or conversation index as string"},
                "limit": {"type": "integer", "description": "Number of recent messages to return", "default": 20},
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
                "to": {"type": "string", "description": "Contact name (existing chat) or phone number (new chat)"},
                "message": {"type": "string", "description": "SMS text to send"},
            },
            "required": ["to", "message"],
        },
    ),
    # --- Android ---
    Tool(
        name="android_send_sms",
        description="Send an SMS from the connected Android device via ADB.",
        inputSchema={
            "type": "object",
            "properties": {
                "number": {"type": "string", "description": "Recipient phone number"},
                "message": {"type": "string", "description": "SMS message body"},
            },
            "required": ["number", "message"],
        },
    ),
    Tool(
        name="android_screenshot",
        description="Capture a screenshot from the connected Android device via ADB. Returns base64 PNG.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    # --- WhatsApp ---
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
            "Accepts a contact/group name (e.g. 'EDE Internal') or a phone number (e.g. '880XXXXXXXXXX')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "Contact/group name or phone number"},
                "limit": {"type": "integer", "description": "Number of recent messages to return", "default": 20},
            },
            "required": ["chat"],
        },
    ),
    Tool(
        name="whatsapp_send_message",
        description=(
            "Send a WhatsApp message to a contact, group, or phone number. "
            "Accepts a contact/group name (e.g. 'EDE Internal') or a phone number (e.g. '880XXXXXXXXXX'). "
            "WhatsApp Web must be open and logged in via VNC."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Contact/group name or phone number"},
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["to", "message"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _shell_execute(cmd: str, cwd: str = "/root", timeout: int = 30) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1,
        }
    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode,
    }


async def _file_read(path: str) -> dict[str, Any]:
    async with aiofiles.open(path, "r", errors="replace") as f:
        content = await f.read()
    return {"content": content, "path": path}


async def _file_write(path: str, content: str) -> dict[str, Any]:
    async with aiofiles.open(path, "w") as f:
        await f.write(content)
    return {"path": path, "bytes": len(content.encode())}


async def _file_list(path: str) -> dict[str, Any]:
    entries_raw = await aiofiles.os.listdir(path)
    entries = []
    for name in sorted(entries_raw):
        full = os.path.join(path, name)
        try:
            st = await aiofiles.os.stat(full)
            entry_type = "dir" if stat.S_ISDIR(st.st_mode) else "file"
            entries.append(
                {
                    "name": name,
                    "type": entry_type,
                    "size": st.st_size,
                    "modified": st.st_mtime,
                }
            )
        except OSError:
            entries.append({"name": name, "type": "unknown", "size": 0, "modified": 0})
    return {"entries": entries}


async def _file_delete(path: str) -> dict[str, Any]:
    st = await aiofiles.os.stat(path)
    if stat.S_ISDIR(st.st_mode):
        await aiofiles.os.rmdir(path)
    else:
        await aiofiles.os.remove(path)
    return {"path": path, "deleted": True}


# ---------------------------------------------------------------------------
# Outlook implementations — use raw CDP (navigate, evaluate, click, type_text)
# Same JS extraction logic as autumn-sandbox/services/outlook.py
# ---------------------------------------------------------------------------

OUTLOOK_URL: str = os.getenv("OUTLOOK_URL", "https://outlook.office.com")

# Selectors — aria-label / role based for stability across Outlook updates
_OL_SEL = {
    "new_mail": '[aria-label="New mail"]',
    "email_list": '[role="listbox"]',
    "email_item": '[role="listbox"] [role="option"]',
    "reading_pane": '[role="document"]',
    "search_input": '#topSearchInput, input[aria-label*="Search"]',
    "to_field": 'div[aria-label="To"]',
    "cc_field": 'div[aria-label="Cc"]',
    "subject_field": 'input[placeholder="Add a subject"]',
    "body_field": 'div[aria-label="Message body, press Alt+F10 to exit"]',
    "send_button": 'button[aria-label="Send"]',
    "reply_button": 'button[aria-label="Reply"], [role="menuitem"][aria-label="Reply"]',
    "reply_all_button": 'button[aria-label="Reply all"], [role="menuitem"][aria-label="Reply all"]',
    "forward_button": 'button[aria-label="Forward"], [role="menuitem"][aria-label="Forward"]',
}

# JS: extract email list items from the inbox
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
            else if (!time && /\\d{1,2}:\\d{2}/.test(text)) { time = text; timeFull = title || text; }
            else if (sender && subject && time && !preview) { preview = text; }
        }
        return {index: idx, convId, unread, sender, senderEmail, subject, time, timeFull, preview};
    });
})(%d)
"""

# JS: read email header from the reading pane
_JS_READ_HEADER = """
(function() {
    const h3s = Array.from(document.querySelectorAll('[role="heading"][aria-level="3"]'));
    let subject = '', from_ = '', to_ = '', cc_ = '', date_ = '';
    for (const el of h3s) {
        const text = (el.innerText || '').trim();
        if (!text) continue;
        if (el.tagName === 'DIV' && !subject && !text.startsWith('To:') && !text.startsWith('Cc:') && !text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)/))
            subject = text.split('\\n')[0];
        if (el.tagName === 'SPAN' && text.includes('@') && !from_) from_ = text;
        if (text.startsWith('To:')) to_ = text;
        if (text.startsWith('Cc:')) cc_ = text;
        if (text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s/)) date_ = text;
    }
    return {subject, from_: from_, to_: to_, cc_: cc_, date_: date_};
})()
"""

# JS: read body from the reading pane
_JS_READ_BODY = """
(function() {
    const doc = document.querySelector('[role="document"]');
    if (!doc) return {body_text: ''};
    return {body_text: doc.innerText || ''};
})()
"""


async def _outlook_ensure_mail() -> dict[str, Any]:
    """Navigate to Outlook mail if not already there. Returns login check."""
    from cdp import evaluate, navigate
    # Check current URL
    url_result = await evaluate("window.location.href")
    current = str(url_result.get("result", "")).lower()
    if "outlook" not in current or "mail" not in current:
        await navigate(f"{OUTLOOK_URL}/mail/")
        await asyncio.sleep(3)
    # Check if logged in
    check = await evaluate(f'!!document.querySelector(\'{_OL_SEL["new_mail"]}\')')
    if not check.get("result"):
        return {"error": "Not logged in. Open VNC (port 6080) and log into Outlook manually."}
    return {"status": "ok"}


async def _outlook_list_emails(limit: int = 10) -> dict[str, Any]:
    from cdp import evaluate
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    await asyncio.sleep(1)
    result = await evaluate(_JS_LIST_EMAILS % limit)
    return {"emails": result.get("result", [])}


async def _outlook_read_email(index: int) -> dict[str, Any]:
    from cdp import evaluate, click
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    # Click email at index
    click_js = f'document.querySelectorAll(\'{_OL_SEL["email_item"]}\')[{index}].click()'
    await evaluate(click_js)
    await asyncio.sleep(2)
    # Check reading pane appeared
    check = await evaluate(f'!!document.querySelector(\'{_OL_SEL["reading_pane"]}\')')
    if not check.get("result"):
        return {"error": "Reading pane did not appear after clicking email"}
    header = await evaluate(_JS_READ_HEADER)
    body = await evaluate(_JS_READ_BODY)
    h = header.get("result", {})
    b = body.get("result", {})
    return {
        "index": index,
        "subject": h.get("subject", ""),
        "from": h.get("from_", ""),
        "to": h.get("to_", ""),
        "cc": h.get("cc_", ""),
        "date": h.get("date_", ""),
        "body_text": b.get("body_text", ""),
    }


async def _outlook_search_emails(query: str, limit: int = 10) -> dict[str, Any]:
    from cdp import evaluate, click, type_text
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    # Click search, type query, press Enter
    await click(_OL_SEL["search_input"])
    await asyncio.sleep(0.5)
    await type_text(_OL_SEL["search_input"], query)
    await asyncio.sleep(0.5)
    # Press Enter via JS
    await evaluate("""
        document.querySelector('#topSearchInput, input[aria-label*="Search"]')
            .dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
    """)
    await asyncio.sleep(3)
    result = await evaluate(_JS_LIST_EMAILS % limit)
    return {"query": query, "emails": result.get("result", [])}


async def _outlook_send_email(to: str, subject: str, body: str, cc: str = "") -> dict[str, Any]:
    from cdp import evaluate, click, type_text
    login = await _outlook_ensure_mail()
    if "error" in login:
        return login
    # Click New Mail
    await click(_OL_SEL["new_mail"])
    await asyncio.sleep(2)
    # To
    await click(_OL_SEL["to_field"])
    await asyncio.sleep(0.3)
    for addr in to.split(","):
        await type_text(_OL_SEL["to_field"], addr.strip())
        await asyncio.sleep(0.3)
        await evaluate("""
            document.querySelector('div[aria-label="To"]')
                .dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
        """)
        await asyncio.sleep(0.3)
    # CC
    if cc:
        # Try to show CC field
        await evaluate("""
            const btn = document.querySelector('button[aria-label="Show Cc"]');
            if (btn) btn.click();
        """)
        await asyncio.sleep(0.5)
        await click(_OL_SEL["cc_field"])
        for addr in cc.split(","):
            await type_text(_OL_SEL["cc_field"], addr.strip())
            await asyncio.sleep(0.3)
            await evaluate("""
                document.querySelector('div[aria-label="Cc"]')
                    .dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
            """)
            await asyncio.sleep(0.3)
    # Subject
    await click(_OL_SEL["subject_field"])
    await type_text(_OL_SEL["subject_field"], subject)
    # Body
    await click(_OL_SEL["body_field"])
    await asyncio.sleep(0.3)
    await type_text(_OL_SEL["body_field"], body)
    await asyncio.sleep(0.5)
    # Send
    await click(_OL_SEL["send_button"])
    await asyncio.sleep(2)
    return {"status": "sent", "to": to, "subject": subject}


async def _outlook_reply_email(body: str, reply_all: bool = False) -> dict[str, Any]:
    from cdp import evaluate, click, type_text
    sel = _OL_SEL["reply_all_button"] if reply_all else _OL_SEL["reply_button"]
    # Try each selector variant (comma-separated)
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
    action = "reply_all" if reply_all else "reply"
    return {"status": "sent", "action": action}


async def _outlook_forward_email(to: str, body: str = "") -> dict[str, Any]:
    from cdp import evaluate, click, type_text
    sel = _OL_SEL["forward_button"]
    for s in sel.split(", "):
        result = await click(s.strip())
        if result.get("status") == "ok":
            break
    await asyncio.sleep(2)
    # To
    await click(_OL_SEL["to_field"])
    for addr in to.split(","):
        await type_text(_OL_SEL["to_field"], addr.strip())
        await asyncio.sleep(0.3)
        await evaluate("""
            document.querySelector('div[aria-label="To"]')
                .dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, bubbles:true}))
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
# WhatsApp implementations — browser automation against WhatsApp Web (VNC)
# ---------------------------------------------------------------------------

_WA_INPUT_SEL = 'footer div[contenteditable="true"]'

# JS: extract chats from the sidebar
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
            time = texts.find(t => /^\\d{1,2}:\\d{2}/.test(t) || t === 'Yesterday' || /^\\d{1,2}\\//.test(t)) || '';
            preview = texts.filter(t => t !== time).join(' ').slice(0, 80);
        }
        chats.push({name, time, preview});
        if (chats.length >= limit) break;
    }
    return chats;
})(%d)
"""

# JS: extract messages from the open chat panel
_JS_WA_READ_MESSAGES = """
(function(limit) {
    // Try data-pre-plain-text first (group messages with sender info)
    const withMeta = document.querySelectorAll('[data-pre-plain-text]');
    if (withMeta.length > 0) {
        return Array.from(withMeta).slice(-limit).map(el => {
            const meta = el.getAttribute('data-pre-plain-text') || '';
            const match = meta.match(/\\[([^\\]]+)\\]\\s*([^:]+):\\s*/);
            const time   = match ? match[1].trim() : '';
            const sender = match ? match[2].trim() : '';
            const textEl = el.querySelector('.copyable-text');
            const text   = textEl ? textEl.innerText.trim() : el.innerText.trim();
            return {time, sender, text};
        }).filter(m => m.text);
    }
    // Fallback: grab all message bubbles (1:1 chats — no sender metadata)
    const bubbles = document.querySelectorAll('.message-in .copyable-text, .message-out .copyable-text');
    return Array.from(bubbles).slice(-limit).map(el => {
        const row = el.closest('.message-in, .message-out');
        const direction = row && row.classList.contains('message-out') ? 'You' : 'Them';
        const timeEl = row && row.querySelector('[data-pre-plain-text]');
        const timeMeta = timeEl ? timeEl.getAttribute('data-pre-plain-text') : '';
        const timeMatch = timeMeta.match(/\\[([^\\]]+)\\]/);
        // also try the timestamp span inside the bubble
        const tsEl = row && row.querySelector('span[class*="time"], span._ahhn');
        const time = (timeMatch && timeMatch[1]) || (tsEl && tsEl.innerText.trim()) || '';
        return {time, sender: direction, text: el.innerText.trim()};
    }).filter(m => m.text);
})(%d)
"""


def _is_phone(value: str) -> bool:
    """Return True if value looks like a phone number (digits, optional leading +)."""
    stripped = value.lstrip("+").replace(" ", "").replace("-", "")
    return stripped.isdigit() and len(stripped) >= 7


_WA_URL = "web.whatsapp.com"


async def _whatsapp_ensure_open() -> dict[str, Any]:
    """Ensure WhatsApp Web is open and logged in. navigate_if_needed style."""
    from cdp import evaluate_in_tab, navigate_in_tab
    url_result = await evaluate_in_tab("window.location.href", _WA_URL)
    current = str(url_result.get("result", ""))
    if "web.whatsapp.com" not in current:
        await navigate_in_tab("https://web.whatsapp.com", _WA_URL)
        await asyncio.sleep(6)
    # Confirm sidebar is present (logged in)
    check = await evaluate_in_tab('!!document.querySelector("#pane-side")', _WA_URL)
    if not check.get("result"):
        return {"error": "WhatsApp not logged in. Open VNC (port 6080) and scan the QR code."}
    return {"status": "ok"}


async def _whatsapp_open_chat(chat: str) -> dict[str, Any]:
    """Open a specific chat by name or phone number."""
    from cdp import evaluate_in_tab, navigate_in_tab
    if _is_phone(chat):
        phone = chat.lstrip("+").replace(" ", "").replace("-", "")
        login = await _whatsapp_ensure_open()
        if "error" in login:
            return login
        await navigate_in_tab(f"https://web.whatsapp.com/send?phone={phone}", _WA_URL)
        await asyncio.sleep(6)
        # Confirm input box appeared (chat opened)
        check = await evaluate_in_tab(f'!!document.querySelector(\'{_WA_INPUT_SEL}\')', _WA_URL)
        if not check.get("result"):
            return {"error": f"Could not open chat for phone {chat}. Number may not be on WhatsApp."}
    else:
        login = await _whatsapp_ensure_open()
        if "error" in login:
            return login
        # Get the bounding box of the matching sidebar item and click via CDP mouse event
        coords = await evaluate_in_tab(f"""
        (() => {{
            const query = {json.dumps(chat.lower())};
            const all = document.querySelectorAll('#pane-side span[title]');
            let el = null;
            for (const s of all) {{
                if ((s.getAttribute('title') || '').toLowerCase().includes(query)) {{
                    el = s; break;
                }}
            }}
            if (!el) return null;
            const row = el.closest('[role="listitem"]') || el.parentElement;
            const rect = (row || el).getBoundingClientRect();
            return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
        }})()
        """, _WA_URL)
        pos = coords.get("result")
        if not pos:
            return {"error": f"Chat '{chat}' not found in sidebar. Scroll or search manually first."}
        # Use real CDP mouse event — JS .click() doesn't reliably trigger React handlers
        from cdp import _open_session, _dispatch_click
        http, cdp = await _open_session(url_contains=_WA_URL)
        try:
            await _dispatch_click(cdp, pos["x"], pos["y"])
        finally:
            await cdp.close()
            await http.close()
        await asyncio.sleep(3)
    return {"status": "ok"}


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
    await asyncio.sleep(3)
    result = await evaluate_in_tab(_JS_WA_READ_MESSAGES % limit, _WA_URL)
    messages = result.get("result") or []
    return {"chat": chat, "messages": messages, "count": len(messages)}


async def _whatsapp_send_message(to: str, message: str) -> dict[str, Any]:
    from cdp import evaluate_in_tab, type_text_in_tab
    opened = await _whatsapp_open_chat(to)
    if "error" in opened:
        return opened
    # Focus and type
    await evaluate_in_tab(f'document.querySelector(\'{_WA_INPUT_SEL}\')?.focus()', _WA_URL)
    await asyncio.sleep(0.5)
    await type_text_in_tab(_WA_INPUT_SEL, message, _WA_URL)
    await asyncio.sleep(0.5)
    # Send with Enter keydown
    await evaluate_in_tab(f"""
    (() => {{
        const el = document.querySelector('{_WA_INPUT_SEL}');
        if (el) el.dispatchEvent(new KeyboardEvent('keydown', {{
            key: 'Enter', keyCode: 13, bubbles: true, cancelable: true
        }}));
    }})()
    """, _WA_URL)
    await asyncio.sleep(2)
    return {"status": "sent", "to": to, "message": message}


# ---------------------------------------------------------------------------
# Google Messages implementations — browser automation against messages.google.com
# ---------------------------------------------------------------------------

_GM_URL = "https://messages.google.com/web/conversations"
_GM_HOST = "messages.google.com"

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
        const convId = (href.match(/conversations\\/([^/?]+)/) || [])[1] || '';
        return {index: idx, convId, name, snippet, timestamp, unread: !!unread};
    });
})(%d)
"""

_JS_GM_GET_MESSAGES = """
(function(limit) {
    let wrappers = document.querySelectorAll('mws-message-wrapper');
    if (!wrappers.length) wrappers = document.querySelectorAll('[data-e2e-message-wrapper]');
    return Array.from(wrappers).slice(-limit).map(el => {
        const textEl = el.querySelector('.text-msg-content, [data-e2e-message-text-content]');
        const text = textEl ? textEl.innerText.trim() : '';
        const tsEl = el.querySelector('mws-relative-timestamp, .timestamp');
        const timestamp = tsEl ? tsEl.innerText.trim() : '';
        const isOutgoing = el.classList.contains('outgoing')
            || !!el.closest('.outgoing')
            || el.getAttribute('data-e2e-is-outgoing') === 'true';
        const senderEl = el.querySelector('.sender-name, [data-e2e-sender-name]');
        const sender = senderEl ? senderEl.innerText.trim() : (isOutgoing ? 'Me' : '');
        return {text, timestamp, is_outgoing: isOutgoing, sender};
    }).filter(m => m.text);
})(%d)
"""

_GM_COMPOSE_SEL = '[contenteditable="true"][aria-label*="message" i], [data-e2e-message-input-field], mws-autosize-textarea textarea'
_GM_SEND_SEL = '[data-e2e-send-button], button[aria-label*="Send" i], [aria-label="Send SMS message" i]'


async def _google_messages_ensure_open() -> dict[str, Any]:
    """Ensure messages.google.com is open and paired."""
    from cdp import evaluate_in_tab, navigate_in_tab
    url_result = await evaluate_in_tab("window.location.href", _GM_HOST)
    current = str(url_result.get("result", ""))
    if "messages.google.com" not in current:
        await navigate_in_tab(_GM_URL, _GM_HOST)
        await asyncio.sleep(5)
    check = await evaluate_in_tab(
        '!!document.querySelector("mws-conversations-list, mws-conversation-list-item, a[href*=\'conversations/\']")',
        _GM_HOST,
    )
    if not check.get("result"):
        return {"error": "Google Messages not paired. Open VNC (port 6080) and scan the QR code."}
    return {"status": "ok"}


async def _google_messages_list_chats(limit: int = 20) -> dict[str, Any]:
    from cdp import evaluate_in_tab
    login = await _google_messages_ensure_open()
    if "error" in login:
        return login
    await asyncio.sleep(1)
    result = await evaluate_in_tab(_JS_GM_LIST_CHATS % limit, _GM_HOST)
    chats = result.get("result") or []
    return {"chats": chats, "count": len(chats)}


async def _google_messages_open_chat(chat: str) -> dict[str, Any]:
    """Open a conversation by name (partial match) or index."""
    from cdp import evaluate_in_tab, _open_session, _dispatch_click
    login = await _google_messages_ensure_open()
    if "error" in login:
        return login

    # Get bounding box of the target item and click via real CDP mouse event
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


async def _google_messages_read_chat(chat: str, limit: int = 20) -> dict[str, Any]:
    from cdp import evaluate_in_tab
    opened = await _google_messages_open_chat(chat)
    if "error" in opened:
        return opened
    await asyncio.sleep(2)
    result = await evaluate_in_tab(_JS_GM_GET_MESSAGES % limit, _GM_HOST)
    messages = result.get("result") or []
    return {"chat": chat, "messages": messages, "count": len(messages)}


async def _google_messages_send_message(to: str, message: str) -> dict[str, Any]:
    from cdp import evaluate_in_tab, type_text_in_tab

    login = await _google_messages_ensure_open()
    if "error" in login:
        return login

    is_phone = to.lstrip("+").replace(" ", "").replace("-", "").isdigit() and len(to.lstrip("+").replace(" ", "").replace("-", "")) >= 7

    if is_phone:
        # Start Chat FAB flow for new conversations
        fab_js = """
        (() => {
            const fab = document.querySelector('[data-e2e-start-chat-fab], [aria-label="Start chat" i], a[href*="new"]');
            if (!fab) return 'NOT_FOUND';
            fab.click(); return 'CLICKED';
        })()
        """
        fab_result = await evaluate_in_tab(fab_js, _GM_HOST)
        if fab_result.get("result") == "NOT_FOUND":
            return {"error": "Could not find 'Start chat' button in Google Messages."}
        await asyncio.sleep(1)

        # Type recipient phone number
        input_selectors = [
            '[data-e2e-contact-input]',
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
        await evaluate_in_tab("""
        (() => {
            const el = document.activeElement || document.body;
            el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', keyCode:13, bubbles:true}));
        })()
        """, _GM_HOST)
        await asyncio.sleep(1.5)
    else:
        opened = await _google_messages_open_chat(to)
        if "error" in opened:
            return opened

    # Type the message into the compose field
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

    # Click Send button, fallback to Enter
    send_clicked = False
    for sel in _GM_SEND_SEL.split(", "):
        res = await evaluate_in_tab(f'!!document.querySelector("{sel}")', _GM_HOST)
        if res.get("result"):
            await evaluate_in_tab(f'document.querySelector("{sel}").click()', _GM_HOST)
            send_clicked = True
            break
    if not send_clicked:
        await evaluate_in_tab("""
        (() => {
            const el = document.activeElement || document.body;
            el.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', keyCode:13, bubbles:true}));
        })()
        """, _GM_HOST)

    await asyncio.sleep(1)
    return {"status": "sent", "to": to, "message": message}


async def _android_send_sms(number: str, message: str) -> dict[str, Any]:
    import urllib.parse
    encoded_msg = urllib.parse.quote(message)
    cmd = (
        f"adb -s {ADB_HOST}:5555 shell am start -a android.intent.action.SENDTO "
        f"-d 'sms:{number}' --es sms_body '{encoded_msg}' --ez exit_on_sent true"
    )
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    return {
        "number": number,
        "status": "sent" if proc.returncode == 0 else "error",
        "exit_code": proc.returncode,
        "stderr": stderr.decode(errors="replace").strip(),
    }


async def _android_screenshot() -> str:
    """Capture Android screenshot via ADB and return base64-encoded PNG."""
    cmd = f"adb -s {ADB_HOST}:5555 exec-out screencap -p"
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"ADB screencap failed: {stderr.decode(errors='replace').strip()}")
    return base64.b64encode(stdout).decode()


# ---------------------------------------------------------------------------
# MCP handlers
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent | ImageContent]:
    try:
        if name == "shell_execute":
            result = await _shell_execute(
                cmd=arguments["cmd"],
                cwd=arguments.get("cwd", "/root"),
                timeout=arguments.get("timeout", 30),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "file_read":
            result = await _file_read(arguments["path"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "file_write":
            result = await _file_write(arguments["path"], arguments["content"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "file_list":
            result = await _file_list(arguments["path"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "file_delete":
            result = await _file_delete(arguments["path"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "browser_navigate":
            from cdp import navigate
            result = await navigate(arguments["url"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "browser_screenshot":
            from cdp import screenshot
            result = await screenshot()
            return [
                ImageContent(
                    type="image",
                    data=result["data"],
                    mimeType="image/png",
                )
            ]

        elif name == "browser_click":
            from cdp import click
            result = await click(arguments["selector"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "browser_type":
            from cdp import type_text
            result = await type_text(arguments["selector"], arguments["text"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "browser_evaluate":
            from cdp import evaluate
            result = await evaluate(arguments["js"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "outlook_list_emails":
            result = await _outlook_list_emails(limit=arguments.get("limit", 10))
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "outlook_read_email":
            result = await _outlook_read_email(index=arguments["index"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "outlook_search_emails":
            result = await _outlook_search_emails(
                query=arguments["query"], limit=arguments.get("limit", 10)
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "outlook_send_email":
            result = await _outlook_send_email(
                to=arguments["to"],
                subject=arguments["subject"],
                body=arguments["body"],
                cc=arguments.get("cc", ""),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "outlook_reply_email":
            result = await _outlook_reply_email(
                body=arguments["body"],
                reply_all=arguments.get("reply_all", False),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "outlook_forward_email":
            result = await _outlook_forward_email(
                to=arguments["to"],
                body=arguments.get("body", ""),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "whatsapp_list_chats":
            result = await _whatsapp_list_chats(limit=arguments.get("limit", 20))
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "whatsapp_read_chat":
            result = await _whatsapp_read_chat(
                chat=arguments["chat"],
                limit=arguments.get("limit", 20),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "whatsapp_send_message":
            result = await _whatsapp_send_message(
                to=arguments["to"],
                message=arguments["message"],
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "google_messages_list_chats":
            result = await _google_messages_list_chats(limit=arguments.get("limit", 20))
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "google_messages_read_chat":
            result = await _google_messages_read_chat(
                chat=arguments["chat"],
                limit=arguments.get("limit", 20),
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "google_messages_send_message":
            result = await _google_messages_send_message(
                to=arguments["to"],
                message=arguments["message"],
            )
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "android_send_sms":
            result = await _android_send_sms(arguments["number"], arguments["message"])
            return [TextContent(type="text", text=json.dumps(result))]

        elif name == "android_screenshot":
            b64_data = await _android_screenshot()
            return [
                ImageContent(
                    type="image",
                    data=b64_data,
                    mimeType="image/png",
                )
            ]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as exc:
        logger.exception("Error calling tool %s", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


# ---------------------------------------------------------------------------
# Starlette app factory
# ---------------------------------------------------------------------------


def create_app() -> Starlette:
    sse = SseServerTransport("/mcp/messages")

    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    async def handle_messages(request):
        await sse.handle_post_message(request.scope, request.receive, request._send)

    starlette_app = Starlette(
        routes=[
            Route("/mcp/sse", endpoint=handle_sse),
            Route("/mcp/messages", endpoint=handle_messages, methods=["POST"]),
        ]
    )
    return starlette_app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="0.0.0.0", port=8079)
