"""
server.py — MCP server for the agent-sandbox.

Exposes tools over HTTP/SSE on port 8079.
Tool implementations live in tools/ sub-modules; this file is a thin dispatcher.

Start with:
    uvicorn server:create_app --factory --host 0.0.0.0 --port 8079
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Sequence

# Allow importing cdp from the API directory (Docker: /opt/sandbox/api, local: core/api)
sys.path.insert(0, os.getenv("PYTHONPATH", "/opt/sandbox/api"))

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import ImageContent, TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Route

import uvicorn

from tools import HANDLERS, IMAGE_TOOLS, TOOLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_server")

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

server = Server("agent-sandbox")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> Sequence[TextContent | ImageContent]:
    try:
        handler = HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        result = await handler(arguments)

        if name in IMAGE_TOOLS:
            # Handler returns a raw base64 string for image tools
            return [ImageContent(type="image", data=result, mimeType="image/png")]
        return [TextContent(type="text", text=json.dumps(result))]

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

    return Starlette(
        routes=[
            Route("/mcp/sse", endpoint=handle_sse),
            Route("/mcp/messages", endpoint=handle_messages, methods=["POST"]),
        ]
    )


if __name__ == "__main__":
    uvicorn.run(create_app(), host="0.0.0.0", port=8079)
