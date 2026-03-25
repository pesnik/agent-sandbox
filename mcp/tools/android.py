"""
android.py — MCP tool: ADB-based Android control

Controls an Android device/emulator via the `adb` command-line tool.
Designed to work with the docker-android emulator exposed on ADB_HOST:ADB_PORT.

Exposes four high-level tools:

    send_sms(number, message)   — Send an SMS from the device
    tap(x, y)                   — Tap a screen coordinate
    screenshot()                — Capture the device screen (PNG, base64)
    shell(cmd)                  — Run an arbitrary adb shell command

Usage (as a standalone MCP server):
    python3 mcp/tools/android.py serve [port]

Environment variables:
    ADB_HOST    Hostname/IP of the ADB device  (default: localhost)
    ADB_PORT    TCP port for ADB               (default: 5555)
    ADB_SERIAL  Full serial to pass to -s      (overrides ADB_HOST:ADB_PORT)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import tempfile
from typing import Any

logger = logging.getLogger("mcp.android")

ADB_HOST: str = os.getenv("ADB_HOST", "localhost")
ADB_PORT: str = os.getenv("ADB_PORT", "5555")
_ADB_SERIAL_ENV: str | None = os.getenv("ADB_SERIAL")


def _serial() -> str:
    return _ADB_SERIAL_ENV or f"{ADB_HOST}:{ADB_PORT}"


def _adb(*args: str) -> list[str]:
    """Build a full adb command list targeting the configured device."""
    return ["adb", "-s", _serial(), *args]


# ---------------------------------------------------------------------------
# Low-level subprocess helper
# ---------------------------------------------------------------------------


async def _run(*cmd: str, input_data: bytes | None = None) -> tuple[int, str, str]:
    """
    Run a command asynchronously.

    Returns:
        (returncode, stdout_str, stderr_str)
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if input_data else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(input=input_data), timeout=30.0)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def _ensure_connected() -> None:
    """Connect ADB to the device if not already connected."""
    rc, out, _ = await _run("adb", "connect", _serial())
    if rc != 0:
        raise RuntimeError(f"adb connect failed: {out}")


# ---------------------------------------------------------------------------
# Public MCP tools
# ---------------------------------------------------------------------------


async def send_sms(number: str, message: str) -> dict[str, Any]:
    """
    Send an SMS from the Android device to `number` with body `message`.

    Uses `am start` with an intent targeting the SMS app.

    Returns:
        { "to": str, "status": "ok" | "error", "detail": str }
    """
    await _ensure_connected()

    # Use the built-in SMS intent to compose and auto-send
    intent_cmd = _adb(
        "shell", "am", "start",
        "-a", "android.intent.action.SENDTO",
        "-d", f"smsto:{number}",
        "--es", "sms_body", message,
        "--ez", "exit_on_sent", "true",
    )
    rc, out, err = await _run(*intent_cmd)
    if rc != 0:
        return {"to": number, "status": "error", "detail": err or out}

    # Short delay for the activity to open, then simulate Send button tap
    await asyncio.sleep(1.5)

    # Press the send button — standard KEYCODE_ENTER (66) triggers send in most ROMs
    key_rc, key_out, key_err = await _run(*_adb("shell", "input", "keyevent", "66"))
    detail = "SMS sent via intent + keyevent 66"
    if key_rc != 0:
        detail = f"Intent OK but keyevent failed: {key_err or key_out}"

    return {"to": number, "status": "ok", "detail": detail}


async def tap(x: int, y: int) -> dict[str, Any]:
    """
    Tap the Android screen at pixel coordinate (x, y).

    Returns:
        { "x": int, "y": int, "status": "ok" | "error" }
    """
    await _ensure_connected()
    rc, out, err = await _run(*_adb("shell", "input", "tap", str(x), str(y)))
    if rc != 0:
        return {"x": x, "y": y, "status": "error", "detail": err or out}
    return {"x": x, "y": y, "status": "ok"}


async def screenshot() -> dict[str, str]:
    """
    Capture a screenshot of the Android device screen.

    Returns:
        { "data": "<base64-encoded PNG>", "encoding": "base64" }
    """
    await _ensure_connected()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Take screenshot on device and pull to host
        rc, out, err = await _run(*_adb("exec-out", "screencap", "-p"))
        if rc != 0:
            raise RuntimeError(f"screencap failed: {err or out}")

        # Re-run and capture raw bytes
        proc = await asyncio.create_subprocess_exec(
            *_adb("exec-out", "screencap", "-p"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        png_bytes, err_bytes = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        if proc.returncode != 0:
            raise RuntimeError(f"screencap failed: {err_bytes.decode(errors='replace')}")

        return {"data": base64.b64encode(png_bytes).decode(), "encoding": "base64"}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def shell(cmd: str) -> dict[str, Any]:
    """
    Run an arbitrary `adb shell` command on the device.

    Returns:
        { "cmd": str, "returncode": int, "stdout": str, "stderr": str }
    """
    await _ensure_connected()
    rc, out, err = await _run(*_adb("shell", cmd))
    return {"cmd": cmd, "returncode": rc, "stdout": out, "stderr": err}


# ---------------------------------------------------------------------------
# MCP server scaffolding
# ---------------------------------------------------------------------------

TOOLS = {
    "send_sms": send_sms,
    "tap": tap,
    "screenshot": screenshot,
    "shell": shell,
}

TOOL_SCHEMAS = {
    "send_sms": {
        "description": "Send an SMS from the Android device.",
        "parameters": {
            "type": "object",
            "properties": {
                "number": {"type": "string", "description": "Recipient phone number"},
                "message": {"type": "string", "description": "SMS body text"},
            },
            "required": ["number", "message"],
        },
    },
    "tap": {
        "description": "Tap a coordinate on the Android screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X pixel coordinate"},
                "y": {"type": "integer", "description": "Y pixel coordinate"},
            },
            "required": ["x", "y"],
        },
    },
    "screenshot": {
        "description": "Capture a screenshot of the Android device. Returns base64 PNG.",
        "parameters": {"type": "object", "properties": {}},
    },
    "shell": {
        "description": "Run an adb shell command on the Android device.",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "description": "Shell command to execute"}
            },
            "required": ["cmd"],
        },
    },
}


async def _handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
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
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 9101

        async def _main() -> None:
            server = await asyncio.start_server(_handle_request, "0.0.0.0", port)
            logger.info("MCP android tool listening on port %d", port)
            async with server:
                await server.serve_forever()

        asyncio.run(_main())
    else:
        # Quick smoke-test: take a screenshot and save it
        async def _smoke() -> None:
            if not shutil.which("adb"):
                print("ERROR: adb not found in PATH")
                return
            print(f"Connecting to {_serial()}...")
            await _ensure_connected()
            print("Taking screenshot...")
            ss = await screenshot()
            img_bytes = base64.b64decode(ss["data"])
            with open("/tmp/android_test.png", "wb") as f:
                f.write(img_bytes)
            print(f"Screenshot saved to /tmp/android_test.png ({len(img_bytes)} bytes)")
            print("Running shell command: uname -a")
            result = await shell("uname -a")
            print("shell:", result)

        asyncio.run(_smoke())
