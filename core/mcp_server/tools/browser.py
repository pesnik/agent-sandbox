"""Generic browser tools: navigate, screenshot, click, type, evaluate."""
from __future__ import annotations

from typing import Any

from mcp.types import Tool

# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
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
        inputSchema={"type": "object", "properties": {}},
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
]

IMAGE_TOOLS: set[str] = {"browser_screenshot"}

# ---------------------------------------------------------------------------
# Handler wrappers
# ---------------------------------------------------------------------------


async def _h_browser_navigate(a: dict) -> dict:
    from cdp import navigate
    return await navigate(a["url"])


async def _h_browser_screenshot(a: dict) -> str:
    from cdp import screenshot
    result = await screenshot()
    return result["data"]  # base64 string


async def _h_browser_click(a: dict) -> dict:
    from cdp import click
    return await click(a["selector"])


async def _h_browser_type(a: dict) -> dict:
    from cdp import type_text
    return await type_text(a["selector"], a["text"])


async def _h_browser_evaluate(a: dict) -> Any:
    from cdp import evaluate
    return await evaluate(a["js"])


HANDLERS: dict = {
    "browser_navigate": _h_browser_navigate,
    "browser_screenshot": _h_browser_screenshot,
    "browser_click": _h_browser_click,
    "browser_type": _h_browser_type,
    "browser_evaluate": _h_browser_evaluate,
}
