"""Shell execution router."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ShellExecuteRequest(BaseModel):
    cmd: str
    cwd: str = "/root"
    timeout: int = 30


@router.post("/v1/shell/execute")
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
