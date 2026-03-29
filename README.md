# Agent Sandbox

A composable, self-hosted Docker environment where an AI agent can control a full desktop, browser, VS Code, and more — all via REST API and MCP tools. Drop-in replacement for `agent-infra/sandbox`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Host machine                                               │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  agent-sandbox (single Docker container)              │  │
│  │                                                       │  │
│  │   nginx :8080  ──┬── /vnc/      → noVNC      :6080   │  │
│  │   (dashboard)    ├── /vscode/   → code-server :8200  │  │
│  │                  ├── /v1/       → REST API    :8091  │  │
│  │                  ├── /mcp/      → MCP server  :8079  │  │
│  │                  ├── /cdp/      → Chromium CDP :9222 │  │
│  │                  └── /devtools/ → Chromium CDP :9222 │  │
│  │                                                       │  │
│  │   supervisord (always-on core services)               │  │
│  │     ├── xtigervnc    :5900  (XFCE4 desktop)          │  │
│  │     ├── xfce                (desktop session)        │  │
│  │     ├── websockify   :6080  (noVNC WebSocket bridge) │  │
│  │     ├── nginx        :8080  (reverse proxy)          │  │
│  │     ├── chromium     :9222  (CDP remote debug)       │  │
│  │     ├── code-server  :8200  (VS Code in browser)     │  │
│  │     ├── uvicorn      :8091  (REST API v1)            │  │
│  │     └── mcp-server   :8079  (MCP SSE server)        │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  agent-android (optional sidecar)                     │  │
│  │   budtmo/docker-android:emulator_13.0                 │  │
│  │   ADB :5555 | noVNC :6081                             │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

All core services start automatically — no modules to enable for the base stack.

---

## Port map

| Port | Path | Service | Notes |
|------|------|---------|-------|
| 8080 | `/` | nginx dashboard | Links to all services |
| 8080 | `/vnc/` | noVNC | Browser-based XFCE4 desktop |
| 8080 | `/vscode/` | VS Code Server | No auth required |
| 8080 | `/v1/` | REST API | Shell, files, browser control |
| 8080 | `/v1/docs` | OpenAPI docs | Interactive Swagger UI |
| 8080 | `/mcp/sse` | MCP server | SSE transport for AI agents |
| 8080 | `/cdp/` | CDP proxy | Chromium DevTools Protocol |
| 5900 | — | TigerVNC | Direct VNC access |
| 6080 | — | noVNC | WebSocket desktop stream |
| 8079 | — | MCP server | Direct (also proxied at `/mcp/`) |
| 8091 | — | REST API | Direct (also proxied at `/v1/`) |
| 9222 | — | Chromium CDP | Direct (also proxied at `/cdp/`) |
| 5555 | — | ADB | Android sidecar only |
| 6081 | — | Android noVNC | Android sidecar only |

---

## Quick start

Two runtimes are supported — pick one based on your environment.

### Local (native macOS) — no Docker, low memory

Runs Chrome headless + REST API + MCP server directly on macOS. No VNC, no VS Code, no container overhead (~60–70% less RAM than Docker).

```bash
git clone https://github.com/pesnik/agent-sandbox
cd agent-sandbox

# One-time: log into WhatsApp, Google Messages, Outlook (headed Chrome for QR/auth)
make login

# Start the sandbox (headless Chrome + API + MCP)
make start
```

Services are available directly on their ports:

| Service | URL |
|---------|-----|
| REST API | http://localhost:8091/v1/docs |
| MCP SSE | http://localhost:8079/mcp/sse |
| CDP | http://localhost:9222 |

### Docker — full stack (VNC desktop, VS Code, nginx proxy)

```bash
git clone https://github.com/pesnik/agent-sandbox
cd agent-sandbox
make docker-up
```

Open **http://localhost:8080** — the dashboard links to all services.

No configuration required for the core stack. All services start automatically.

---

## REST API v1

The sandbox exposes a FastAPI service at `/v1/` (port 8091 direct, or `http://localhost:8080/v1/`).

Interactive docs: **http://localhost:8080/v1/docs**

### Shell

```bash
# Run a command
curl -X POST http://localhost:8080/v1/shell/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "ls /root", "timeout": 10}'

# Response
{"stdout": "...", "stderr": "", "exit_code": 0, "timed_out": false}
```

### Files

```bash
# Read a file
curl http://localhost:8080/v1/files/read?path=/etc/hostname

# Write a file
curl -X POST http://localhost:8080/v1/files/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/root/hello.txt", "content": "hello world"}'
```

### Browser (CDP)

```bash
# Navigate to a URL
curl -X POST http://localhost:8080/v1/browser/navigate \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'

# Take a screenshot (returns base64 PNG)
curl http://localhost:8080/v1/browser/screenshot
```

---

## MCP server

The sandbox runs a Model Context Protocol server at `/mcp/sse` (SSE transport).

Connect from Claude Desktop or any MCP client:

```json
{
  "mcpServers": {
    "agent-sandbox": {
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

Available tools: `shell_run`, `file_read`, `file_write`, `browser_navigate`, `browser_screenshot`, `browser_click`, `browser_type`, `browser_scroll`, `browser_evaluate`, `browser_wait`, `browser_get_url`, `browser_get_content`

---

## Playwright / CDP access

Chromium runs with `--remote-debugging-port=9222` and is proxied through nginx at `/cdp/`.

### From outside the container

```python
from playwright.async_api import async_playwright
import urllib.request, json, urllib.parse

# Fetch the WebSocket URL and rewrite the host:port
cdp_url = "http://localhost:8080/cdp"
data = json.loads(urllib.request.urlopen(cdp_url + "/json/version").read())
ws_url = data["webSocketDebuggerUrl"]          # ws://localhost:9222/devtools/browser/UUID
parsed = urllib.parse.urlparse(ws_url)
ws_url = ws_url.replace(f"{parsed.hostname}:{parsed.port}", "localhost:8080")
# → ws://localhost:8080/devtools/browser/UUID

async with async_playwright() as p:
    browser = await p.chromium.connect_over_cdp(ws_url)
    page = browser.contexts[0].pages[0]
    await page.goto("https://example.com")
```

### Using the autumn-sandbox shim

If you're using `autumn-sandbox`, the `agent_sandbox` Python shim handles URL rewriting automatically:

```python
from agent_sandbox import Sandbox

client = Sandbox()  # reads SANDBOX_CDP_URL from env
ws_url = client.browser.get_info().data.cdp_url  # ready for Playwright
```

Set in `.env`:
```
SANDBOX_CDP_URL=http://localhost:8080/cdp
SANDBOX_BASE_URL=http://localhost:8091
```

---

## Stealth / bot detection

Chromium launches with a stealth Chrome extension (`core/stealth-extension/`) that:

- Removes `navigator.webdriver` and CDP automation globals
- Spoofs `navigator.plugins`, `navigator.mimeTypes`, `navigator.languages`
- Fixes `Permissions.query` to return `granted` for notifications
- Runs at `document_start` in the `MAIN` world — executes before any page script

This makes the browser undetectable by standard bot checks (reCAPTCHA, Cloudflare, etc.).

---

## Android sidecar (optional)

```bash
docker compose -f docker-compose.yml -f docker-compose.android.yml up -d
```

- Android 13 emulator via `budtmo/docker-android:emulator_13.0`
- ADB on port 5555, noVNC desktop on port 6081
- No kernel modules or `--privileged` required

---

## Adding a module

Add a `[program:<name>]` block to a new file under `core/supervisord/conf.d/`:

```ini
[program:myservice]
command=/usr/local/bin/myservice --port=8300
autostart=true
autorestart=true
priority=60
user=root
stdout_logfile=/var/log/supervisor/myservice.log
stderr_logfile=/var/log/supervisor/myservice-err.log
```

Rebuild and restart:

```bash
docker compose build --no-cache sandbox
docker compose up -d
```

For a sidecar container, add a `docker-compose.override.yml` following the android pattern.

---

## Makefile reference

All lifecycle commands are in the `Makefile`. Run `make` to see the full list.

### Local commands

| Command | Description |
|---------|-------------|
| `make setup` | Create `.venv-local` and install Python deps |
| `make login` | Open headed Chrome for one-time login / QR pairing |
| `make start` | Start headless Chrome + REST API + MCP |
| `make stop` | Kill all local sandbox processes |
| `make restart` | `stop` + `start` |
| `make status` | Show which ports are live |
| `make logs` | Tail Chrome + API + MCP logs simultaneously |
| `make logs-chrome` | Chrome log only |
| `make logs-api` | API log only |
| `make logs-mcp` | MCP log only |
| `make test` | Run e2e suite against the running local stack |
| `make clean` | Remove `.venv-local` and Chrome profile data |

### Docker commands

| Command | Description |
|---------|-------------|
| `make docker-build` | Rebuild image from scratch (`--no-cache`) |
| `make docker-up` | Start container |
| `make docker-down` | Stop and remove container |
| `make docker-restart` | `down` + `up` |
| `make docker-logs` | Follow container logs |
| `make docker-shell` | Open bash inside the container |
| `make docker-test` | Run e2e suite against the running container |

### Local runtime notes

- Sessions (WhatsApp, Google Messages, Outlook) persist in `~/.config/agent-sandbox-local`. Re-run `make login` when a session expires.
- Logs are written to `/tmp/agent-sandbox-{chrome,api,mcp}.log`.
- Port overrides: `CDP_PORT=9333 API_PORT=8092 make start`
- The `make login` step requires stopping `make start` first — both use the same Chrome user-data-dir and cannot run simultaneously.
