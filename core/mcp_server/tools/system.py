"""System tools: shell execution and file I/O."""
from __future__ import annotations

import asyncio
import os
import stat
from typing import Any

import aiofiles
import aiofiles.os
from mcp.types import Tool

# ---------------------------------------------------------------------------
# Definitions
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
                "path": {"type": "string", "description": "Path to file or empty directory"},
            },
            "required": ["path"],
        },
    ),
]

# ---------------------------------------------------------------------------
# Implementations
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
        return {"stdout": "", "stderr": f"Command timed out after {timeout}s", "exit_code": -1}
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
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
            entries.append({"name": name, "type": entry_type, "size": st.st_size, "modified": st.st_mtime})
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


# ---------------------------------------------------------------------------
# Handler wrappers  (arguments dict → result)
# ---------------------------------------------------------------------------


async def _h_shell_execute(a: dict) -> dict:
    return await _shell_execute(a["cmd"], a.get("cwd", "/root"), a.get("timeout", 30))


async def _h_file_read(a: dict) -> dict:
    return await _file_read(a["path"])


async def _h_file_write(a: dict) -> dict:
    return await _file_write(a["path"], a["content"])


async def _h_file_list(a: dict) -> dict:
    return await _file_list(a["path"])


async def _h_file_delete(a: dict) -> dict:
    return await _file_delete(a["path"])


HANDLERS: dict = {
    "shell_execute": _h_shell_execute,
    "file_read": _h_file_read,
    "file_write": _h_file_write,
    "file_list": _h_file_list,
    "file_delete": _h_file_delete,
}
