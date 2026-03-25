"""
browser.py — MCP tool: CDP-based browser control

Connects to a Chromium instance with remote debugging enabled (--remote-debugging-port=9222).
Exposes five high-level tools that an AI agent can call:

    navigate(url)             — Load a URL in the active tab
    screenshot()              — Capture a full-page PNG, returned as base64
    click(selector)           — Click the first element matching a CSS selector
    type(selector, text)      — Focus a field and type text character-by-character
    evaluate(js)              — Run arbitrary JavaScript and return the result

Usage (as a standalone MCP server):
    python3 mcp/tools/browser.py

The CDP_URL env var controls which Chromium instance to connect to.
Default: http://localhost:9222
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("mcp.browser")

CDP_URL: str = os.getenv("CDP_URL", "http://localhost:9222")


# ---------------------------------------------------------------------------
# Low-level CDP helpers
# ---------------------------------------------------------------------------


async def _get_target_ws_url(session: aiohttp.ClientSession) -> str:
    """Return the WebSocket debugger URL for the first available page target."""
    async with session.get(f"{CDP_URL}/json/list") as resp:
        targets = await resp.json(content_type=None)

    pages = [t for t in targets if t.get("type") == "page"]
    if not pages:
        raise RuntimeError("No page targets found in Chromium. Is it running?")
    return pages[0]["webSocketDebuggerUrl"]


class CDPSession:
    """Thin async CDP session over a WebSocket connection."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self._ws = ws
        self._id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._listener_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if "id" in data:
                    fut = self._pending.pop(data["id"], None)
                    if fut and not fut.done():
                        if "error" in data:
                            fut.set_exception(RuntimeError(data["error"]["message"]))
                        else:
                            fut.set_result(data.get("result", {}))

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._id += 1
        msg_id = self._id
        fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        payload = {"id": msg_id, "method": method, "params": params or {}}
        await self._ws.send_str(json.dumps(payload))
        return await asyncio.wait_for(fut, timeout=30.0)

    async def close(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
        await self._ws.close()


async def _open_session() -> tuple[aiohttp.ClientSession, CDPSession]:
    http = aiohttp.ClientSession()
    ws_url = await _get_target_ws_url(http)
    ws = await http.ws_connect(ws_url)
    cdp = CDPSession(ws)
    await cdp.start()
    return http, cdp


# ---------------------------------------------------------------------------
# Public MCP tools
# ---------------------------------------------------------------------------


async def navigate(url: str) -> dict[str, Any]:
    """
    Navigate the active browser tab to `url`.

    Returns:
        { "frameId": str, "loaderId": str, "status": "ok" }
    """
    http, cdp = await _open_session()
    try:
        result = await cdp.send("Page.navigate", {"url": url})
        # Wait for load to settle
        await asyncio.sleep(1.0)
        return {**result, "status": "ok"}
    finally:
        await cdp.close()
        await http.close()


async def screenshot() -> dict[str, str]:
    """
    Capture a screenshot of the current page.

    Returns:
        { "data": "<base64-encoded PNG>", "encoding": "base64" }
    """
    http, cdp = await _open_session()
    try:
        # Ensure full viewport is captured
        layout = await cdp.send("Page.getLayoutMetrics")
        vp = layout.get("cssContentSize", layout.get("contentSize", {}))
        width = int(vp.get("width", 1280))
        height = int(vp.get("height", 800))

        result = await cdp.send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
                "captureBeyondViewport": True,
            },
        )
        return {"data": result["data"], "encoding": "base64"}
    finally:
        await cdp.close()
        await http.close()


async def click(selector: str) -> dict[str, Any]:
    """
    Click the first DOM element matching `selector` (CSS selector).

    Returns:
        { "selector": str, "status": "ok" | "not_found" }
    """
    http, cdp = await _open_session()
    try:
        # Resolve element and obtain bounding box
        doc = await cdp.send("DOM.getDocument", {"depth": 0})
        root_node_id = doc["root"]["nodeId"]

        query = await cdp.send(
            "DOM.querySelector",
            {"nodeId": root_node_id, "selector": selector},
        )
        node_id = query.get("nodeId", 0)
        if not node_id:
            return {"selector": selector, "status": "not_found"}

        box_result = await cdp.send("DOM.getBoxModel", {"nodeId": node_id})
        content = box_result["model"]["content"]
        # content is [x1,y1, x2,y2, x3,y3, x4,y4] (quad)
        cx = (content[0] + content[4]) / 2
        cy = (content[1] + content[5]) / 2

        await cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": cx, "y": cy, "button": "left", "clickCount": 1},
        )
        await cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": cx, "y": cy, "button": "left", "clickCount": 1},
        )
        return {"selector": selector, "status": "ok"}
    finally:
        await cdp.close()
        await http.close()


async def type_text(selector: str, text: str) -> dict[str, Any]:
    """
    Focus the element matching `selector` and type `text` character-by-character.

    Returns:
        { "selector": str, "chars_typed": int, "status": "ok" | "not_found" }
    """
    # First click the element to focus it
    click_result = await click(selector)
    if click_result["status"] != "ok":
        return {**click_result, "chars_typed": 0}

    http, cdp = await _open_session()
    try:
        for char in text:
            await cdp.send(
                "Input.dispatchKeyEvent",
                {"type": "keyDown", "text": char, "unmodifiedText": char},
            )
            await cdp.send(
                "Input.dispatchKeyEvent",
                {"type": "keyUp", "text": char, "unmodifiedText": char},
            )
        return {"selector": selector, "chars_typed": len(text), "status": "ok"}
    finally:
        await cdp.close()
        await http.close()


async def evaluate(js: str) -> dict[str, Any]:
    """
    Evaluate a JavaScript expression in the context of the current page.

    Returns:
        { "result": <any>, "type": str, "status": "ok" | "error" }
    """
    http, cdp = await _open_session()
    try:
        result = await cdp.send(
            "Runtime.evaluate",
            {
                "expression": js,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        rv = result.get("result", {})
        ex = result.get("exceptionDetails")
        if ex:
            return {
                "status": "error",
                "type": "exception",
                "result": ex.get("text", "Unknown JS exception"),
            }
        return {
            "status": "ok",
            "type": rv.get("type", "undefined"),
            "result": rv.get("value"),
        }
    finally:
        await cdp.close()
        await http.close()


# ---------------------------------------------------------------------------
# MCP server entry point
# ---------------------------------------------------------------------------

TOOLS = {
    "navigate": navigate,
    "screenshot": screenshot,
    "click": click,
    "type": type_text,
    "evaluate": evaluate,
}

TOOL_SCHEMAS = {
    "navigate": {
        "description": "Navigate the browser to a URL.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL to load"}},
            "required": ["url"],
        },
    },
    "screenshot": {
        "description": "Capture a screenshot of the current page. Returns base64 PNG.",
        "parameters": {"type": "object", "properties": {}},
    },
    "click": {
        "description": "Click the first element matching a CSS selector.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector"}
            },
            "required": ["selector"],
        },
    },
    "type": {
        "description": "Focus an element and type text into it.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector"},
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["selector", "text"],
        },
    },
    "evaluate": {
        "description": "Run JavaScript in the page context and return the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "js": {"type": "string", "description": "JavaScript expression or statement"}
            },
            "required": ["js"],
        },
    },
}


async def _handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Handle a single MCP JSON-RPC request over stdio/socket."""
    data = await reader.read(65536)
    try:
        req = json.loads(data)
        tool_name = req.get("tool")
        params = req.get("params", {})
        if tool_name == "__list__":
            response = {"tools": TOOL_SCHEMAS}
        elif tool_name in TOOLS:
            result = await TOOLS[tool_name](**params)
            response = {"result": result}
        else:
            response = {"error": f"Unknown tool: {tool_name}"}
    except Exception as exc:
        logger.exception("Error handling MCP request")
        response = {"error": str(exc)}

    writer.write(json.dumps(response).encode())
    await writer.drain()
    writer.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        # TCP server mode: python3 browser.py serve [port]
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 9100

        async def _main() -> None:
            server = await asyncio.start_server(_handle_request, "0.0.0.0", port)
            logger.info("MCP browser tool listening on port %d", port)
            async with server:
                await server.serve_forever()

        asyncio.run(_main())
    else:
        # Quick smoke-test: navigate to example.com and take a screenshot
        async def _smoke() -> None:
            print("Testing navigate...")
            result = await navigate("https://example.com")
            print("navigate:", result)
            print("Testing screenshot...")
            ss = await screenshot()
            img_bytes = base64.b64decode(ss["data"])
            with open("/tmp/browser_test.png", "wb") as f:
                f.write(img_bytes)
            print(f"Screenshot saved to /tmp/browser_test.png ({len(img_bytes)} bytes)")
            print("Testing evaluate...")
            ev = await evaluate("document.title")
            print("evaluate:", ev)

        asyncio.run(_smoke())
