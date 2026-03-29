# sandbox-client

Zero-dependency Python SDK for the [agent-sandbox](https://github.com/pesnik/agent-sandbox) REST API.

## Install

```bash
# From the repo root
pip install ./sdk

# Or just copy sdk/client.py into your project — no dependencies needed
```

## Quick start

```python
from sdk.client import SandboxClient

c = SandboxClient()  # reads SANDBOX_BASE_URL env, defaults to http://localhost:8091

# Browser
c.browser.navigate_if_needed("https://web.whatsapp.com")  # no-op if already there
print(c.browser.get_url())
print(c.browser.get_title())
print(c.browser.get_text()[:200])

# Click — by selector or by coordinates
c.browser.click(selector="button.submit")
c.browser.click(x=640, y=400)

# Type & send
c.browser.type(selector="input[name='q']", text="hello world")
c.browser.press_key("Enter")

# Screenshot
shot = c.browser.screenshot()
shot.save("screen.png")          # writes PNG to disk

# Evaluate JS
result = c.browser.evaluate("document.title")
print(result.result)             # Python value

# Shell
r = c.shell.execute("ls /root")
print(r.stdout)
print(r.exit_code)

# Files
content = c.files.read("/etc/hostname")
c.files.write("/root/hello.txt", "world\n")
entries = c.files.list("/root")
for e in entries:
    print(e.name, e.type, e.size)

# Service health
print(c.status.get())            # {"vnc": True, "browser": True, ...}
print(c.status.is_ready())       # True if browser is up
```

## API reference

### `SandboxClient(base_url=None)`

Reads `SANDBOX_BASE_URL` env var; defaults to `http://localhost:8091`.

| Sub-client | Description |
|------------|-------------|
| `.browser` | Browser automation |
| `.shell`   | Shell command execution |
| `.files`   | File read/write/list/delete |
| `.status`  | Service liveness check |

### `BrowserAPI`

| Method | Description |
|--------|-------------|
| `navigate(url)` | Navigate unconditionally |
| `navigate_if_needed(url, match=None)` | Skip if URL already contains `match` |
| `click(selector=None, x=None, y=None)` | Click by selector or coordinates |
| `type(selector, text)` | Type text into element |
| `press_key(key)` | Dispatch keyboard event on focused element |
| `screenshot()` → `ScreenshotResult` | Capture page as PNG |
| `evaluate(js)` → `EvaluateResult` | Run JS, get Python value back |
| `get_text()` | `document.body.innerText` |
| `get_url()` | `window.location.href` |
| `get_title()` | `document.title` |

### `ShellAPI`

| Method | Description |
|--------|-------------|
| `execute(cmd, cwd="/root", timeout=30)` → `ShellResult` | Run shell command |

### `FilesAPI`

| Method | Description |
|--------|-------------|
| `read(path)` → `str` | Read file contents |
| `write(path, content)` → `int` | Write file, returns bytes written |
| `list(path)` → `list[FileEntry]` | List directory |
| `delete(path)` → `bool` | Delete file or empty dir |

### `StatusAPI`

| Method | Description |
|--------|-------------|
| `get()` → `dict` | `{vnc, browser, vscode, mcp}` liveness |
| `is_ready()` → `bool` | True if browser is up |
