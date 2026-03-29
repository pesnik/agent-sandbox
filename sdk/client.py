"""
sandbox_client — Python SDK for the agent-sandbox REST API.

Zero extra dependencies (stdlib only). Works against any running
agent-sandbox container.

Quick start:
    from sandbox_client import SandboxClient

    c = SandboxClient()                        # defaults to http://localhost:8091
    c.browser.navigate_if_needed("https://web.whatsapp.com")
    print(c.browser.get_text()[:200])
    c.browser.click(selector="button.send")
    c.browser.click(x=640, y=400)
    result = c.shell.execute("ls /root")
    print(result.stdout)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------


def _post(base: str, path: str, body: dict) -> dict:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _get(base: str, path: str) -> dict:
    url = base.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def _delete(base: str, path: str) -> dict:
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


@dataclass
class FileEntry:
    name: str
    type: str       # "file" | "dir" | "unknown"
    size: int
    modified: float


@dataclass
class ScreenshotResult:
    data: str       # base64-encoded PNG
    encoding: str   # always "base64"

    def save(self, path: str) -> None:
        """Decode and write the PNG to disk."""
        import base64
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(self.data))


@dataclass
class EvaluateResult:
    result: Any     # Python value returned by the JS expression
    type: str       # JS typeof string
    status: str     # "ok" | "error"


# ---------------------------------------------------------------------------
# Shell API
# ---------------------------------------------------------------------------


class ShellAPI:
    def __init__(self, base: str):
        self._base = base

    def execute(self, cmd: str, cwd: str = "/root", timeout: int = 30) -> ShellResult:
        """Run a shell command and return stdout, stderr, exit_code."""
        resp = _post(self._base, "/v1/shell/execute", {"cmd": cmd, "cwd": cwd, "timeout": timeout})
        return ShellResult(
            stdout=resp.get("stdout", ""),
            stderr=resp.get("stderr", ""),
            exit_code=resp.get("exit_code", -1),
            timed_out=resp.get("timed_out", False),
        )


# ---------------------------------------------------------------------------
# Files API
# ---------------------------------------------------------------------------


class FilesAPI:
    def __init__(self, base: str):
        self._base = base

    def read(self, path: str) -> str:
        """Read a file and return its content as a string."""
        resp = _get(self._base, f"/v1/files/read?path={urllib.request.quote(path, safe='')}")
        return resp["content"]

    def write(self, path: str, content: str) -> int:
        """Write content to a file. Returns bytes written."""
        resp = _post(self._base, "/v1/files/write", {"path": path, "content": content})
        return resp["bytes"]

    def list(self, path: str) -> list[FileEntry]:
        """List directory entries."""
        resp = _get(self._base, f"/v1/files/list?path={urllib.request.quote(path, safe='')}")
        return [
            FileEntry(
                name=e["name"], type=e["type"],
                size=e["size"], modified=e["modified"],
            )
            for e in resp.get("entries", [])
        ]

    def delete(self, path: str) -> bool:
        """Delete a file or empty directory. Returns True on success."""
        resp = _delete(self._base, f"/v1/files/delete?path={urllib.request.quote(path, safe='')}")
        return resp.get("deleted", False)


# ---------------------------------------------------------------------------
# Browser API
# ---------------------------------------------------------------------------


class BrowserAPI:
    def __init__(self, base: str):
        self._base = base

    # --- Navigation ---

    def navigate(self, url: str) -> str:
        """Navigate to url unconditionally. Returns final status string."""
        resp = _post(self._base, "/v1/browser/navigate", {"url": url})
        return resp.get("status", "ok")

    def navigate_if_needed(self, url: str, match: str | None = None) -> str:
        """
        Navigate to url only if the current page URL doesn't already contain
        `match` (defaults to `url` itself).

        Returns "already_there" if navigation was skipped, otherwise the
        navigate status string.
        """
        check = match if match is not None else url
        current = self.evaluate("window.location.href").result or ""
        if check in str(current):
            return "already_there"
        return self.navigate(url)

    # --- Interaction ---

    def click(self, selector: str | None = None, x: float | None = None, y: float | None = None) -> str:
        """
        Click by CSS selector or by absolute viewport coordinates.

            c.browser.click(selector="button.submit")
            c.browser.click(x=640, y=400)

        Returns status string ("ok" / "not_found").
        """
        if selector is not None:
            resp = _post(self._base, "/v1/browser/click", {"selector": selector})
        elif x is not None and y is not None:
            resp = _post(self._base, "/v1/browser/click", {"x": x, "y": y})
        else:
            raise ValueError("Provide 'selector' or both 'x' and 'y'")
        return resp.get("status", "ok")

    def type(self, selector: str, text: str) -> int:
        """Type text into the element matching selector. Returns chars typed."""
        resp = _post(self._base, "/v1/browser/type", {"selector": selector, "text": text})
        return resp.get("chars_typed", 0)

    def press_key(self, key: str) -> None:
        """
        Dispatch a keyboard event on the currently focused element.
        Uses JS KeyboardEvent since CDP key dispatch requires focus management.
        """
        key_codes = {
            "Enter": 13, "Tab": 9, "Escape": 27,
            "Backspace": 8, "ArrowUp": 38, "ArrowDown": 40,
        }
        code = key_codes.get(key, 0)
        js = f"""
        (() => {{
            const el = document.activeElement || document.body;
            ['keydown','keyup'].forEach(t => el.dispatchEvent(
                new KeyboardEvent(t, {{key:'{key}', keyCode:{code}, bubbles:true, cancelable:true}})
            ));
        }})()
        """
        self.evaluate(js)

    # --- Content ---

    def screenshot(self) -> ScreenshotResult:
        """Capture a screenshot. Returns a ScreenshotResult with base64 PNG data."""
        resp = _get(self._base, "/v1/browser/screenshot")
        return ScreenshotResult(data=resp["data"], encoding=resp.get("encoding", "base64"))

    def evaluate(self, js: str) -> EvaluateResult:
        """
        Evaluate a JavaScript expression in the page context.

        The expression is wrapped in an IIFE if it looks like an arrow function.
        """
        expr = f"({js})()" if js.strip().startswith("()") else js
        resp = _post(self._base, "/v1/browser/evaluate", {"js": expr})
        return EvaluateResult(
            result=resp.get("result"),
            type=resp.get("type", "undefined"),
            status=resp.get("status", "ok"),
        )

    def get_text(self) -> str:
        """Return the visible text content of the current page."""
        return str(self.evaluate("document.body.innerText").result or "")

    def get_url(self) -> str:
        """Return the current page URL."""
        return str(self.evaluate("window.location.href").result or "")

    def get_title(self) -> str:
        """Return the current page title."""
        return str(self.evaluate("document.title").result or "")


# ---------------------------------------------------------------------------
# Status API
# ---------------------------------------------------------------------------


class StatusAPI:
    def __init__(self, base: str):
        self._base = base

    def get(self) -> dict[str, bool]:
        """Return liveness of each service: {vnc, browser, vscode, mcp}."""
        return _get(self._base, "/v1/status").get("services", {})

    def is_ready(self) -> bool:
        """Return True if the browser service is up."""
        return self.get().get("browser", False)


# ---------------------------------------------------------------------------
# Top-level client
# ---------------------------------------------------------------------------


class SandboxClient:
    """
    Client for the agent-sandbox REST API.

    Usage:
        c = SandboxClient()                              # http://localhost:8091
        c = SandboxClient("http://localhost:8091")
        c = SandboxClient(base_url=os.getenv("SANDBOX_BASE_URL"))

    Sub-clients:
        c.browser   — BrowserAPI
        c.shell     — ShellAPI
        c.files     — FilesAPI
        c.status    — StatusAPI
    """

    def __init__(self, base_url: str | None = None):
        url = base_url or os.getenv("SANDBOX_BASE_URL", "http://localhost:8091")
        self._base = url.rstrip("/")
        self.browser = BrowserAPI(self._base)
        self.shell = ShellAPI(self._base)
        self.files = FilesAPI(self._base)
        self.status = StatusAPI(self._base)

    def __repr__(self) -> str:
        return f"SandboxClient({self._base!r})"
