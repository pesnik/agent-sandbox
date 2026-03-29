# Agent Sandbox — Claude Code Guide

## Project layout

```
core/                        # Single Docker image (Ubuntu 22.04)
  Dockerfile                 # Build definition
  entrypoint.sh              # Container start: writes supervisord confs, starts supervisord
  supervisord/conf.d/        # One .conf per service (always-on)
    vnc.conf                 # Xtigervnc :5900 + xfce session
    novnc.conf               # websockify :6080 → :5900
    nginx.conf               # nginx :8080
    chromium.conf            # Playwright Chromium :9222
    vscode.conf              # code-server :8200
    api.conf                 # uvicorn FastAPI :8091
    mcp.conf                 # MCP SSE server :8079
  nginx/conf.d/default.conf  # Reverse proxy routing
  api/main.py                # FastAPI routes (/v1/shell, /v1/files, /v1/browser)
  api/cdp.py                 # Pure CDP client (no Playwright dependency in the API)
  mcp_server/                # MCP server (FastAPI + SSE transport)
  stealth-extension/         # Chrome extension — hides automation signals
    manifest.json            # Manifest V3, content_script, world: MAIN
    stealth.js               # Removes navigator.webdriver, spoofs plugins/mimeTypes

sdk/                         # Zero-dependency Python SDK for the REST API
  client.py                  # SandboxClient — browser / shell / files / status
  __init__.py
  pyproject.toml             # pip install ./sdk
  README.md

docker-compose.yml           # Main compose file (sandbox service)
docker-compose.android.yml   # Optional Android 13 sidecar
tests/e2e.py                 # 37 e2e tests — run against a live container
modules/                     # Optional sidecar module definitions
scripts/                     # Helper scripts
mcp/                         # MCP tool definitions (for external agent use)
```

## Key design decisions

**Single container, always-on services.** Everything (VNC, browser, VS Code, API, MCP) starts automatically via supervisord. There are no opt-in modules for core services — just build and run.

**Playwright Chromium, not system Chromium.** Ubuntu 22.04 ships chromium-browser as a snap stub. We install via `playwright install chromium` with `PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers` (outside `/root` so it isn't hidden by the home volume mount).

**CDP proxied through nginx.** Chromium's CDP rejects connections with a non-localhost `Host` header. Direct port 9222 access from macOS host fails through OrbStack. Solution: nginx proxies `/cdp/` and `/devtools/` with `proxy_set_header Host localhost`. Python clients must rewrite the `ws://` URL host:port after fetching `/json/version`.

**No VNC password.** TigerVNC runs with `-SecurityTypes None`. `Xtigervnc` is invoked directly (not `tigervncserver` wrapper) to avoid needing `vncpasswd`.

**Supervisord single-line commands.** Multiline `command=` with `\` line continuation is silently broken in supervisord — only the first line runs. All commands are on one line.

**Singleton lock cleanup.** Chromium writes `Singleton*` files to its user-data-dir. If the container restarts without these being cleaned up, Chromium refuses to start. The `chromium.conf` command starts with `rm -f /root/.config/chromium-sandbox/Singleton*`.

**noVNC 1.4.0, not apt.** The apt package is version 1.0.0 which has bugs with `SecurityTypes None`. We download 1.4.0 directly from GitHub in the Dockerfile.

## Port reference

| External | Service | Notes |
|----------|---------|-------|
| 8080 | nginx | All services proxied here |
| 5900 | TigerVNC | Direct VNC |
| 6080 | noVNC | Direct WebSocket |
| 8079 | MCP server | Also at `/mcp/sse` via nginx |
| 8091 | REST API | Also at `/v1/` via nginx |
| 9222 | Chromium CDP | Also at `/cdp/` via nginx — prefer the proxy |

## Running tests

Container must be running before tests:

```bash
docker compose up -d --build
python tests/e2e.py
# Expected: 37/37 passing
```

Tests cover: status, shell (9), files (10), browser/CDP (7), MCP (2), concurrency (2), security/edge cases (6).

## Python SDK (sdk/)

The `sdk/` directory ships a zero-dependency Python client that wraps the REST API.
No pip installs needed beyond stdlib — or `pip install ./sdk` for package use.

```python
from sdk.client import SandboxClient

c = SandboxClient()  # reads SANDBOX_BASE_URL env, defaults to http://localhost:8091

c.browser.navigate_if_needed("https://web.whatsapp.com")  # skips if already there
c.browser.click(selector="button.submit")
c.browser.click(x=640, y=400)                             # coordinate click
c.browser.type(selector="input", text="hello")
c.browser.press_key("Enter")
shot = c.browser.screenshot()
shot.save("screen.png")
print(c.browser.get_text())

r = c.shell.execute("ls /root")
print(r.stdout, r.exit_code)

c.files.write("/root/out.txt", "hello")
print(c.files.read("/root/out.txt"))
```

**Key methods:**

| Sub-client | Useful methods |
|------------|---------------|
| `browser` | `navigate(url)`, `navigate_if_needed(url)`, `click(selector=\|x=,y=)`, `type`, `press_key`, `screenshot`, `evaluate`, `get_text`, `get_url`, `get_title` |
| `shell` | `execute(cmd, cwd, timeout)` → `ShellResult` |
| `files` | `read`, `write`, `list`, `delete` |
| `status` | `get()`, `is_ready()` |

**`navigate_if_needed` design note.** The sandbox browser is persistent (VNC session).
Calling `navigate()` unconditionally reloads the page and destroys live state (e.g. a
WhatsApp login session). `navigate_if_needed` checks `window.location.href` first and
only issues `Page.navigate` when the current URL doesn't already match.

## Google Messages MCP tools

Three tools for Google Messages Web (`messages.google.com`) running in the VNC browser.
Requires one-time QR pairing via VNC — session persists across runs.

| Tool | Required args | Optional |
|------|--------------|---------|
| `google_messages_list_chats` | — | `limit` (default 20) |
| `google_messages_read_chat` | `chat` | `limit` (default 20) |
| `google_messages_send_message` | `to`, `message` | — |

`chat` / `to` accepts a **contact name** (partial match) or a **conversation index**
(string digit, from `google_messages_list_chats`).

For `google_messages_send_message`: existing contacts are opened by name; phone numbers
trigger the "Start chat" FAB flow to initiate a new SMS conversation.

DOM selectors used: `mws-conversation-list-item` for the sidebar,
`mws-message-wrapper` for message bubbles, `[data-e2e-send-button]` for send —
matching the same elements used by the Playwright-based `GoogleMessagesService`.

## WhatsApp MCP tools

Three tools exposed via the MCP server (`/mcp/sse`) that automate WhatsApp Web running
in the persistent VNC browser session. No re-login needed — session state is preserved.

| Tool | Required args | Optional |
|------|--------------|---------|
| `whatsapp_list_chats` | — | `limit` (default 20) |
| `whatsapp_read_chat` | `chat` | `limit` (default 20) |
| `whatsapp_send_message` | `to`, `message` | — |

`chat` / `to` accepts either a **contact/group name** (e.g. `"EDE Internal"`) or a
**phone number** (e.g. `"880XXXXXXXXXX"`). Phone numbers open via
`https://web.whatsapp.com/send?phone=NUMBER`; names are resolved from the visible
sidebar via `span[title="..."]`.

Message content is extracted from `[data-pre-plain-text]` attributes on message
bubbles — format `[HH:MM, DD/MM/YYYY] Sender: ` — so sender and time are always
structured fields, not parsed text.

`_whatsapp_ensure_open()` checks `window.location.href` before navigating, matching
the SDK's `navigate_if_needed` pattern — the existing login session is never disrupted.

## `/v1/browser/click` — selector or coordinates

The click endpoint accepts either a CSS selector or absolute viewport coordinates:

```json
{ "selector": "button.submit" }
{ "x": 640, "y": 400 }
```

Implemented via `cdp.click(selector)` and `cdp.click_at(x, y)` respectively.
Coordinates map directly to `Input.dispatchMouseEvent` — no DOM query needed.

## Common failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| VNC "connection failed" | noVNC 1.0 (apt) | Use noVNC 1.4 from GitHub |
| Chromium invisible in VNC | `--disable-software-rasterizer` | Use `--use-gl=swiftshader` |
| Chromium won't start on restart | Singleton lock file | `rm -f Singleton*` in command |
| `--no-sandbox` banner | Missing flag | Add `--test-type` |
| CDP empty reply from host | Host header rejected | Use nginx `/cdp/` proxy |
| Playwright WebSocket 404 | ws:// URL points at wrong host:port | Rewrite host after fetching `/json/version` |
| File write 500 | Parent dir missing | `os.makedirs(parent, exist_ok=True)` |
| Shell timeout hangs | Child process keeps pipes open | Double `wait_for` with `communicate()` timeout |
| reCAPTCHA / bot detected | `navigator.webdriver = true` | Stealth extension injected at `document_start` in MAIN world |

## Adding a new always-on service

1. Add `core/supervisord/conf.d/<name>.conf` with a `[program:<name>]` block
2. If it needs an nginx route, add a `location` block to `core/nginx/conf.d/default.conf`
3. Rebuild: `docker compose build --no-cache sandbox && docker compose up -d`

## Stealth extension

Located at `core/stealth-extension/`. Manifest V3, runs at `document_start` in the `MAIN` world (not isolated — has access to page globals).

What it patches:
- `navigator.webdriver` → `undefined`
- `navigator.plugins` → non-empty fake list
- `navigator.mimeTypes` → matching fake list
- `navigator.languages` → `['en-US', 'en']`
- `Permissions.query` → always returns `granted` for notifications
- Removes `window.__playwright*`, `window.__pw_*`, `window.cdc_*` CDP globals

Loaded via `--load-extension` and `--disable-extensions-except` Chromium flags.
