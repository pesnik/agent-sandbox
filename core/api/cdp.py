"""
cdp.py — Pure CDP client library for browser control.

Connects to a Chromium instance with remote debugging enabled (--remote-debugging-port=9222).
Provides five high-level async functions:

    navigate(url)             — Load a URL in the active tab
    screenshot()              — Capture a full-page PNG, returned as base64
    click(selector)           — Click the first element matching a CSS selector
    type_text(selector, text) — Focus a field and type text character-by-character
    evaluate(js)              — Run arbitrary JavaScript and return the result

The CDP_URL env var controls which Chromium instance to connect to.
Default: http://localhost:9222
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("cdp")

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
# Stealth — hides automation signals on every new document
# ---------------------------------------------------------------------------

_STEALTH_SCRIPT = """
(() => {
  // Hide navigator.webdriver
  Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true,
  });

  // Spoof plugins array (empty in headless)
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
    configurable: true,
  });

  // Spoof languages
  Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true,
  });

  // Remove automation-related chrome runtime signals
  if (window.chrome) {
    window.chrome.runtime = window.chrome.runtime || {};
  }

  // Fix permissions.query — headless returns 'denied' for notifications
  const origQuery = window.Permissions && window.Permissions.prototype.query;
  if (origQuery) {
    window.Permissions.prototype.query = function(params) {
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
      }
      return origQuery.apply(this, arguments);
    };
  }
})();
"""


async def _install_stealth(cdp: "CDPSession") -> None:
    """Inject stealth script so it runs before every page's JS."""
    try:
        await cdp.send("Page.enable", {})
        await cdp.send(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": _STEALTH_SCRIPT},
        )
    except Exception:
        pass  # non-fatal


# ---------------------------------------------------------------------------
# Public CDP tools
# ---------------------------------------------------------------------------


async def navigate(url: str) -> dict[str, Any]:
    """
    Navigate the active browser tab to `url`.

    Returns:
        { "frameId": str, "loaderId": str, "status": "ok" }
    """
    http, cdp = await _open_session()
    try:
        await _install_stealth(cdp)
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


async def _dispatch_click(cdp: "CDPSession", x: float, y: float) -> None:
    """Send a mousePressed + mouseReleased pair at (x, y) via CDP."""
    await cdp.send(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
    )
    await cdp.send(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
    )


async def click(selector: str) -> dict[str, Any]:
    """
    Click the first DOM element matching `selector` (CSS selector).

    Returns:
        { "selector": str, "status": "ok" | "not_found" }
    """
    http, cdp = await _open_session()
    try:
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

        await _dispatch_click(cdp, cx, cy)
        return {"selector": selector, "status": "ok"}
    finally:
        await cdp.close()
        await http.close()


async def click_at(x: float, y: float) -> dict[str, Any]:
    """
    Click at absolute viewport coordinates (x, y).

    Returns:
        { "x": float, "y": float, "status": "ok" }
    """
    http, cdp = await _open_session()
    try:
        await _dispatch_click(cdp, x, y)
        return {"x": x, "y": y, "status": "ok"}
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
