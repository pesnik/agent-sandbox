"""
main.py — FastAPI REST API for the agent-sandbox.

Serves all routes under /v1/ on port 8091.
OpenAPI docs available at /v1/docs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import stat
from typing import Any

import aiofiles
import aiofiles.os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cdp import (
    click as cdp_click,
    click_at as cdp_click_at,
    evaluate as cdp_evaluate,
    navigate as cdp_navigate,
    screenshot as cdp_screenshot,
    type_text as cdp_type_text,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title="Agent Sandbox API",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Return True if something is listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ShellExecuteRequest(BaseModel):
    cmd: str
    cwd: str = "/root"
    timeout: int = 30


class FileWriteRequest(BaseModel):
    path: str
    content: str


class BrowserNavigateRequest(BaseModel):
    url: str


class BrowserClickRequest(BaseModel):
    selector: str | None = None
    x: float | None = None
    y: float | None = None


class BrowserTypeRequest(BaseModel):
    selector: str
    text: str


class BrowserEvaluateRequest(BaseModel):
    js: str


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@app.get("/v1/status")
async def get_status() -> dict[str, Any]:
    """Return liveness of each service based on port connectivity."""
    return {
        "services": {
            "vnc": _port_open(5900),
            "browser": _port_open(9222),
            "vscode": _port_open(8200),
            "mcp": _port_open(8079),
        }
    }


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------


@app.post("/v1/shell/execute")
async def shell_execute(req: ShellExecuteRequest) -> dict[str, Any]:
    """Execute a shell command and return stdout, stderr, and exit code."""
    try:
        proc = await asyncio.create_subprocess_shell(
            req.cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=req.cwd,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=req.timeout
            )
            return {
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "exit_code": proc.returncode,
                "timed_out": False,
            }
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.communicate(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
            return {
                "stdout": "",
                "stderr": f"Command timed out after {req.timeout}s",
                "exit_code": -1,
                "timed_out": True,
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


@app.get("/v1/files/read")
async def files_read(
    path: str = Query(..., description="Absolute path to file"),
) -> dict[str, Any]:
    """Read a file and return its content as a string."""
    try:
        async with aiofiles.open(path, "r", errors="replace") as f:
            content = await f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except IsADirectoryError:
        raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"content": content, "path": path}


@app.post("/v1/files/write")
async def files_write(req: FileWriteRequest) -> dict[str, Any]:
    """Write content to a file, creating intermediate directories if needed."""
    try:
        parent = os.path.dirname(req.path)
        if parent:
            await aiofiles.os.makedirs(parent, exist_ok=True)
        async with aiofiles.open(req.path, "w") as f:
            await f.write(req.content)
        byte_count = len(req.content.encode())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"path": req.path, "bytes": byte_count}


@app.get("/v1/files/list")
async def files_list(
    path: str = Query(..., description="Directory path to list"),
) -> dict[str, Any]:
    """List entries in a directory."""
    try:
        entries_raw = await aiofiles.os.listdir(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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


@app.delete("/v1/files/delete")
async def files_delete(
    path: str = Query(..., description="Path to file or empty dir to delete"),
) -> dict[str, Any]:
    """Delete a file or empty directory."""
    try:
        st = await aiofiles.os.stat(path)
        if stat.S_ISDIR(st.st_mode):
            await aiofiles.os.rmdir(path)
        else:
            await aiofiles.os.remove(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"path": path, "deleted": True}


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------


@app.post("/v1/browser/navigate")
async def browser_navigate(req: BrowserNavigateRequest) -> dict[str, Any]:
    """Navigate the browser to a URL."""
    try:
        result = await cdp_navigate(req.url)
        return {"status": result.get("status", "ok"), "url": req.url}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/browser/screenshot")
async def browser_screenshot() -> dict[str, Any]:
    """Capture a screenshot of the current browser page."""
    try:
        result = await cdp_screenshot()
        return {"data": result["data"], "encoding": "base64"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/browser/click")
async def browser_click(req: BrowserClickRequest) -> dict[str, Any]:
    """Click by CSS selector or by absolute viewport coordinates (x, y)."""
    try:
        if req.selector is not None:
            result = await cdp_click(req.selector)
            return {"selector": result["selector"], "status": result["status"]}
        elif req.x is not None and req.y is not None:
            result = await cdp_click_at(req.x, req.y)
            return {"x": result["x"], "y": result["y"], "status": result["status"]}
        else:
            raise HTTPException(
                status_code=400, detail="Provide 'selector' or 'x' and 'y'"
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/browser/type")
async def browser_type(req: BrowserTypeRequest) -> dict[str, Any]:
    """Type text into an element identified by a CSS selector."""
    try:
        result = await cdp_type_text(req.selector, req.text)
        return {"status": result["status"], "chars_typed": result.get("chars_typed", 0)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/v1/browser/evaluate")
async def browser_evaluate(req: BrowserEvaluateRequest) -> dict[str, Any]:
    """Evaluate JavaScript in the browser page context."""
    try:
        result = await cdp_evaluate(req.js)
        return {
            "result": result.get("result"),
            "type": result.get("type", "undefined"),
            "status": result.get("status", "ok"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Google Messages
# ---------------------------------------------------------------------------

_GM_HOST = "messages.google.com"

_JS_GM_GET_MESSAGES = """
(function(limit) {
    const items = document.querySelectorAll('mws-tombstone-message-wrapper, mws-message-wrapper');
    const result = [];
    let currentDate = '';

    for (const item of items) {
        if (item.nodeName === 'MWS-TOMBSTONE-MESSAGE-WRAPPER') {
            const raw = (item.textContent || '').replace(/\\u00A0/g, ' ').trim();
            if (raw) {
                const parts = raw.split('\\u00B7').map(s => s.trim());
                const dayPart = parts[0] || '';
                if (dayPart && !dayPart.match(/^\\d{1,2}:\\d{2}/)) {
                    currentDate = dayPart;
                } else {
                    currentDate = 'today';
                }
            }
            continue;
        }

        const textEl = item.querySelector('.text-msg-content, [data-e2e-message-text-content]');
        const text = textEl ? textEl.innerText.trim() : '';
        if (!text) continue;

        const absTs = item.querySelector('mws-absolute-timestamp');
        const relTs = item.querySelector('mws-relative-timestamp, .timestamp');
        const time = absTs ? absTs.textContent.trim() : (relTs ? relTs.innerText.trim() : '');

        const isOutgoing = item.getAttribute('is-outgoing') === 'true';
        const senderEl = item.querySelector('.sender-name, [data-e2e-sender-name]');
        const sender = senderEl ? senderEl.innerText.trim() : (isOutgoing ? 'Me' : '');
        const msgId = item.getAttribute('msg-id') || '';

        result.push({text, time, date: currentDate, is_outgoing: isOutgoing, sender, msg_id: msgId});
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
    let items = document.querySelectorAll('mws-conversation-list-item');
    if (!items.length) items = document.querySelectorAll('a[href*="conversations/"]');
    const lower = name.toLowerCase();
    for (const el of items) {
        const nameEl = el.querySelector('.name, [data-e2e-conversation-name], h3') || {innerText: ''};
        if (nameEl.innerText.trim().toLowerCase().includes(lower)) {
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


@app.post("/v1/google-messages/read")
async def google_messages_read(req: GoogleMessagesReadRequest) -> dict[str, Any]:
    """Read messages from a Google Messages conversation.

    Handles scrolling to load older messages when limit > 25.
    Returns messages with date (tombstone day name) and time (absolute timestamp).
    """
    try:
        # Navigate to Google Messages if not already there
        url_result = await cdp_evaluate("window.location.href")
        current = str(url_result.get("result", ""))
        if _GM_HOST not in current:
            await cdp_navigate(f"https://{_GM_HOST}/web/conversations")
            await asyncio.sleep(5)

        # Find and click the conversation
        safe_name = json.dumps(req.chat.lower())
        coords = await cdp_evaluate(_JS_FIND_CHAT % safe_name)
        pos = coords.get("result")
        if not pos:
            raise HTTPException(
                status_code=404, detail=f"Conversation '{req.chat}' not found"
            )

        await cdp_click_at(pos["x"], pos["y"])
        await asyncio.sleep(2)

        # Scroll up to load older messages (scale iterations with limit)
        if req.limit > 25:
            max_scrolls = max(10, req.limit // 25)
            prev_count = 0
            for _ in range(max_scrolls):
                scroll_result = await cdp_evaluate(_JS_SCROLL_UP)
                current_count = scroll_result.get("result", 0) or 0
                if current_count >= req.limit or current_count == prev_count:
                    break
                prev_count = current_count
                await asyncio.sleep(2)

        # Read messages
        result = await cdp_evaluate(_JS_GM_GET_MESSAGES % req.limit)
        messages = result.get("result") or []

        return {"chat": req.chat, "messages": messages, "count": len(messages)}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
