"""Android tools: send SMS and capture screenshot via ADB."""
from __future__ import annotations

import asyncio
import base64
import os
from typing import Any

from mcp.types import Tool

ADB_HOST: str = os.getenv("ADB_HOST", "localhost")

# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="android_send_sms",
        description="Send an SMS from the connected Android device via ADB.",
        inputSchema={
            "type": "object",
            "properties": {
                "number":  {"type": "string", "description": "Recipient phone number"},
                "message": {"type": "string", "description": "SMS message body"},
            },
            "required": ["number", "message"],
        },
    ),
    Tool(
        name="android_screenshot",
        description="Capture a screenshot from the connected Android device via ADB. Returns base64 PNG.",
        inputSchema={"type": "object", "properties": {}},
    ),
]

IMAGE_TOOLS: set[str] = {"android_screenshot"}

# ---------------------------------------------------------------------------
# Implementations
# ---------------------------------------------------------------------------


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
        "number":    number,
        "status":    "sent" if proc.returncode == 0 else "error",
        "exit_code": proc.returncode,
        "stderr":    stderr.decode(errors="replace").strip(),
    }


async def _android_screenshot() -> str:
    """Return base64-encoded PNG of the Android screen."""
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
# Handler wrappers
# ---------------------------------------------------------------------------


async def _h_android_send_sms(a: dict) -> dict:
    return await _android_send_sms(a["number"], a["message"])


async def _h_android_screenshot(a: dict) -> str:
    return await _android_screenshot()


HANDLERS: dict = {
    "android_send_sms":    _h_android_send_sms,
    "android_screenshot":  _h_android_screenshot,
}
