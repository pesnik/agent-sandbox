"""Generic browser control router (CDP-backed)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cdp import (
    click as cdp_click,
    click_at as cdp_click_at,
    evaluate as cdp_evaluate,
    navigate as cdp_navigate,
    screenshot as cdp_screenshot,
    scroll_at as cdp_scroll_at,
    type_text as cdp_type_text,
)

router = APIRouter()


class BrowserNavigateRequest(BaseModel):
    url: str


class BrowserClickRequest(BaseModel):
    selector: str | None = None
    x: float | None = None
    y: float | None = None


class BrowserTypeRequest(BaseModel):
    selector: str
    text: str


class BrowserEvaluateRequest(BaseModel):
    js: str


class BrowserScrollRequest(BaseModel):
    x: float
    y: float
    delta_x: float = 0
    delta_y: float = 0


@router.post("/v1/browser/navigate")
async def browser_navigate(req: BrowserNavigateRequest) -> dict[str, Any]:
    """Navigate the browser to a URL."""
    try:
        result = await cdp_navigate(req.url)
        return {"status": result.get("status", "ok"), "url": req.url}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/v1/browser/screenshot")
async def browser_screenshot() -> dict[str, Any]:
    """Capture a screenshot of the current browser page."""
    try:
        result = await cdp_screenshot()
        return {"data": result["data"], "encoding": "base64"}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/browser/click")
async def browser_click(req: BrowserClickRequest) -> dict[str, Any]:
    """Click by CSS selector or by absolute viewport coordinates (x, y)."""
    try:
        if req.selector is not None:
            result = await cdp_click(req.selector)
            return {"selector": result["selector"], "status": result["status"]}
        elif req.x is not None and req.y is not None:
            result = await cdp_click_at(req.x, req.y)
            return {"x": result["x"], "y": result["y"], "status": result["status"]}
        else:
            raise HTTPException(
                status_code=400, detail="Provide 'selector' or 'x' and 'y'"
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/browser/scroll")
async def browser_scroll(req: BrowserScrollRequest) -> dict[str, Any]:
    """Dispatch a native mouseWheel scroll event at viewport coordinates (x, y)."""
    try:
        result = await cdp_scroll_at(req.x, req.y, req.delta_x, req.delta_y)
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/browser/type")
async def browser_type(req: BrowserTypeRequest) -> dict[str, Any]:
    """Type text into an element identified by a CSS selector."""
    try:
        result = await cdp_type_text(req.selector, req.text)
        return {"status": result["status"], "chars_typed": result.get("chars_typed", 0)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/v1/browser/evaluate")
async def browser_evaluate(req: BrowserEvaluateRequest) -> dict[str, Any]:
    """Evaluate JavaScript in the browser page context."""
    try:
        result = await cdp_evaluate(req.js)
        return {
            "result": result.get("result"),
            "type": result.get("type", "undefined"),
            "status": result.get("status", "ok"),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
