"""
main.py — FastAPI REST API for the agent-sandbox.

Serves all routes under /v1/ on port 8091.
OpenAPI docs available at /v1/docs.
"""

from __future__ import annotations

import asyncio
import base64
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
    selector: str


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
async def files_read(path: str = Query(..., description="Absolute path to file")) -> dict[str, Any]:
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
async def files_list(path: str = Query(..., description="Directory path to list")) -> dict[str, Any]:
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
async def files_delete(path: str = Query(..., description="Path to file or empty dir to delete")) -> dict[str, Any]:
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
    """Click the first element matching a CSS selector."""
    try:
        result = await cdp_click(req.selector)
        return {"selector": result["selector"], "status": result["status"]}
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
