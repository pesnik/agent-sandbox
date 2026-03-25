"""
server.py — MCP server for the agent-sandbox.

Exposes 12 tools over HTTP/SSE on port 8079:
  - shell_execute, file_read, file_write, file_list, file_delete
  - browser_navigate, browser_screenshot, browser_click, browser_type, browser_evaluate
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
