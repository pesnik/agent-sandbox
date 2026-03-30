"""File system router."""

from __future__ import annotations

import os
import stat
from typing import Any

import aiofiles
import aiofiles.os
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class FileWriteRequest(BaseModel):
    path: str
    content: str


@router.get("/v1/files/read")
async def files_read(
    path: str = Query(..., description="Absolute path to file"),
) -> dict[str, Any]:
    """Read a file and return its content as a string."""
    try:
        async with aiofiles.open(path, "r", errors="replace") as f:
            content = await f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except IsADirectoryError:
        raise HTTPException(status_code=400, detail=f"Path is a directory: {path}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"content": content, "path": path}


@router.post("/v1/files/write")
async def files_write(req: FileWriteRequest) -> dict[str, Any]:
    """Write content to a file, creating intermediate directories if needed."""
    try:
        parent = os.path.dirname(req.path)
        if parent:
            await aiofiles.os.makedirs(parent, exist_ok=True)
        async with aiofiles.open(req.path, "w") as f:
            await f.write(req.content)
        byte_count = len(req.content.encode())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"path": req.path, "bytes": byte_count}


@router.get("/v1/files/list")
async def files_list(
    path: str = Query(..., description="Directory path to list"),
) -> dict[str, Any]:
    """List entries in a directory."""
    try:
        entries_raw = await aiofiles.os.listdir(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Directory not found: {path}")
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {path}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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


@router.delete("/v1/files/delete")
async def files_delete(
    path: str = Query(..., description="Path to file or empty dir to delete"),
) -> dict[str, Any]:
    """Delete a file or empty directory."""
    try:
        st = await aiofiles.os.stat(path)
        if stat.S_ISDIR(st.st_mode):
            await aiofiles.os.rmdir(path)
        else:
            await aiofiles.os.remove(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"path": path, "deleted": True}
