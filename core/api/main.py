"""
main.py — FastAPI REST API for the agent-sandbox.

Serves all routes under /v1/ on port 8091.
OpenAPI docs available at /v1/docs.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from fastapi import FastAPI

from routers import browser, files, google_messages, outlook, shell, whatsapp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title="Agent Sandbox API",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)

app.include_router(shell.router)
app.include_router(files.router)
app.include_router(browser.router)
app.include_router(google_messages.router)
app.include_router(whatsapp.router)
app.include_router(outlook.router)


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


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
