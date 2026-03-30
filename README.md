# Agent Sandbox

A composable, self-hosted Docker environment where an AI agent can control a full desktop, browser, VS Code, and more — all via REST API and MCP tools.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Host machine                                                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  agent-sandbox (core container)                                │  │
│  │                                                                │  │
│  │   nginx :8080  ──┬── /vnc/            → noVNC        :6080    │  │
│  │   (dashboard)    ├── /vscode/         → code-server  :8200    │  │
│  │                  ├── /v1/             → REST API     :8091    │  │
│  │                  ├── /mcp/sse         → MCP (browser):8079    │  │
│  │                  ├── /cdp/            → Chromium CDP :9222    │  │
│  │                  ├── /whatsapp-mcp/   → WA sidecar   :8081    │  │
│  │                  └── /gmessages/      → GM sidecar   :7007    │  │
│  │                                                                │  │
│  │   supervisord (always-on)                                      │  │
│  │     ├── xtigervnc    :5900  (XFCE4 desktop)                   │  │
│  │     ├── websockify   :6080  (noVNC WebSocket bridge)           │  │
│  │     ├── nginx        :8080  (reverse proxy + dashboard)        │  │
│  │     ├── chromium     :9222  (CDP remote debug)                 │  │
│  │     ├── code-server  :8200  (VS Code in browser)               │  │
│  │     ├── uvicorn      :8091  (REST API v1)                      │  │
│  │     └── mcp-server   :8079  (browser-based MCP — Outlook etc.) │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  agent-whatsapp-mcp (optional sidecar)                      │     │
│  │   whatsmeow Go bridge :8080 (internal)                       │     │
│  │   FastMCP SSE server  :8081  (/whatsapp-mcp/sse via nginx)  │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  agent-gmessages-mcp (optional sidecar)                     │     │
│  │   OpenMessage (libgm) :7007  (/gmessages/ + /gmessages/mcp/sse)│  │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  agent-android (optional sidecar)                           │     │
│  │   budtmo/docker-android:emulator_13.0                       │     │
│  │   ADB :5555 | noVNC :6081                                   │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

All sidecars join `agent-sandbox-net`. The core nginx proxies to them by Docker service name using the embedded DNS resolver — starts cleanly even when sidecars are offline.

---

## Port map

| Port | Path | Service | Notes |
|------|------|---------|-------|
| 8080 | `/` | nginx dashboard | Links to all services |
| 8080 | `/vnc/` | noVNC | Browser-based XFCE4 desktop |
| 8080 | `/vscode/` | VS Code Server | No auth required |
| 8080 | `/v1/` | REST API | Shell, files, browser control |
| 8080 | `/v1/docs` | OpenAPI docs | Interactive Swagger UI |
| 8080 | `/mcp/sse` | MCP server (browser) | Outlook, browser-based WhatsApp/GMessages |
| 8080 | `/cdp/` | CDP proxy | Chromium DevTools Protocol |
| 8080 | `/whatsapp-mcp/sse` | WhatsApp MCP | Native protocol sidecar (whatsmeow) |
| 8080 | `/gmessages/` | Google Messages UI | QR pairing web interface |
| 8080 | `/gmessages/mcp/sse` | Google Messages MCP | Native protocol sidecar (libgm) |
| 5900 | — | TigerVNC | Direct VNC access |
| 6080 | — | noVNC | WebSocket desktop stream |
| 8079 | — | MCP server (browser) | Direct (also at `/mcp/`) |
| 8081 | — | WhatsApp MCP SSE | Direct (also at `/whatsapp-mcp/`) |
| 7007 | — | Google Messages | Direct (also at `/gmessages/`) |
| 8091 | — | REST API | Direct (also at `/v1/`) |
| 9222 | — | Chromium CDP | Direct (also at `/cdp/`) |
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

### Docker — with native messaging sidecars

For reliable, browser-independent WhatsApp and Google Messages sessions:

```bash
# Start core sandbox
make docker-up

# Start both messaging sidecars (builds on first run)
make messaging-up

# Or individually
make whatsapp-up
make gmessages-up
```

**First-time pairing:**

```bash
# WhatsApp — QR code printed in container logs
make whatsapp-qr
# Scan with WhatsApp → Settings → Linked Devices → Link a Device

# Google Messages — QR shown in web UI
open http://localhost:8080/gmessages/
# Scan with Google Messages → profile icon → Device pairing → Pair new device
```

Once paired, sessions persist in named Docker volumes and survive container restarts and rebuilds indefinitely (until you unlink from the phone).

**QR code expired before you could scan?**

- **WhatsApp:** The Go bridge auto-generates a new QR when the old one expires. No restart needed — just run `make whatsapp-qr` again and scan the fresh code.
- **Google Messages:** If you see `Timeout waiting for QR code scan`, restart the sidecar to trigger a fresh pairing attempt:
  ```bash
  docker compose -f docker-compose.gmessages-mcp.yml restart
  make gmessages-logs
  ```

**Seeing `127.0.0.11:53: server misbehaving` in gmessages logs?** That's Docker's internal DNS resolver having a transient hiccup. The client retries automatically with increasing backoff. It self-heals in under a minute — only restart if errors persist longer than ~2 minutes.

---

## MCP endpoints

Three independent MCP SSE endpoints — connect your agent to one or all:

| Endpoint | Tools | Backend |
|----------|-------|---------|
| `/mcp/sse` | Browser, shell, files, Outlook, WhatsApp (browser), Google Messages (browser) | Chrome automation via CDP |
| `/whatsapp-mcp/sse` | `whatsapp_list_chats`, `whatsapp_read_chat`, `whatsapp_send_message`, `whatsapp_search_contacts` | whatsmeow Go bridge (native protocol) |
| `/gmessages/mcp/sse` | `get_messages`, `list_conversations`, `send_message`, `search_messages`, `get_status` | OpenMessage / libgm (native protocol) |

Connect from Claude Desktop or any MCP client:

```json
{
  "mcpServers": {
    "sandbox": {
      "url": "http://localhost:8080/mcp/sse"
    },
    "whatsapp": {
      "url": "http://localhost:8080/whatsapp-mcp/sse"
    },
    "gmessages": {
      "url": "http://localhost:8080/gmessages/mcp/sse"
    }
  }
}
```

---

## REST API v1

The sandbox exposes a FastAPI service at `/v1/` (port 8091 direct, or `http://localhost:8080/v1/`).

Interactive docs: **http://localhost:8080/v1/docs**

### Shell

```bash
curl -X POST http://localhost:8080/v1/shell/run \
  -H 'Content-Type: application/json' \
  -d '{"command": "ls /root", "timeout": 10}'
# → {"stdout": "...", "stderr": "", "exit_code": 0, "timed_out": false}
```

### Files

```bash
curl http://localhost:8080/v1/files/read?path=/etc/hostname
curl -X POST http://localhost:8080/v1/files/write \
  -H 'Content-Type: application/json' \
  -d '{"path": "/root/hello.txt", "content": "hello world"}'
```

### Browser (CDP)

```bash
curl -X POST http://localhost:8080/v1/browser/navigate \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com"}'

curl http://localhost:8080/v1/browser/screenshot  # base64 PNG
```

### Outlook (dedicated endpoints)

```bash
# List inbox
curl -X POST http://localhost:8080/v1/outlook/list \
  -H 'Content-Type: application/json' \
  -d '{"limit": 20, "unread_only": false}'
# → {"emails": [{index, unread, sender, senderEmail, subject, time, preview}], "count": N}

# Read full email by index
curl -X POST http://localhost:8080/v1/outlook/read \
  -H 'Content-Type: application/json' \
  -d '{"index": 1}'
# → {index, subject, from, to, cc, date, body_text}

# List all folders from the nav pane
curl -X POST http://localhost:8080/v1/outlook/list-folders
# → {"folders": [{name, level}], "count": N}

# Apply or clear the Unread filter
curl -X POST http://localhost:8080/v1/outlook/filter \
  -H 'Content-Type: application/json' \
  -d '{"active": true}'
# → {"active": true, "status": "ok"}

# Move an email to a named folder
curl -X POST http://localhost:8080/v1/outlook/move \
  -H 'Content-Type: application/json' \
  -d '{"index": 2, "folder": "Reports"}'
# → {"status": "moved", "index": 2, "folder": "Reports"}
```

> Targets the active tab — Outlook must be focused. Activate via `http://localhost:9222/json/activate/<tab-id>` if needed.

### WhatsApp (dedicated endpoint)

```bash
curl -X POST http://localhost:8080/v1/whatsapp/read \
  -H 'Content-Type: application/json' \
  -d '{"chat": "Furkan", "limit": 20}'
# → {"chat": "Furkan", "count": 5, "messages": [{time, sender, text}, ...]}
```

Targets the `web.whatsapp.com` tab directly. Requires WhatsApp Web open and logged in.

> **If chat not found:** WhatsApp sidebar shows only recent chats. Use `/v1/browser/scroll` on `#pane-side` (activate WA tab first via `http://localhost:9222/json/activate/<id>`).
> **If count is 0:** Chat may be syncing history from phone — wait 10–30s and retry.

### Browser scroll (native virtual-scroll trigger)

```bash
curl -X POST http://localhost:8080/v1/browser/scroll \
  -H 'Content-Type: application/json' \
  -d '{"x": 170, "y": 430, "delta_y": 1500}'
# → {"x": 170, "y": 430, "delta_x": 0, "delta_y": 1500, "status": "ok"}
```

Sends a native CDP `mouseWheel` event. Required for virtual-scroll lists (e.g. the Google Messages sidebar) where JS `WheelEvent` dispatch is ignored. Call repeatedly to load more items into the DOM.

### Google Messages (dedicated endpoint)

```bash
curl -X POST http://localhost:8080/v1/google-messages/read \
  -H 'Content-Type: application/json' \
  -d '{"chat": "Alice", "limit": 50}'
# → {"chat": "Alice", "count": 50, "messages": [...]}
```

> **Note:** The sidebar only renders ~25 conversations (virtual scroll). If the target chat is not in the first 25, use `/v1/browser/scroll` to scroll the sidebar (x≈170, y≈430) until the chat appears in the DOM before calling `/read`.

---

## Session persistence

### Native protocol sidecars (recommended)

The WhatsApp MCP and Google Messages MCP sidecars use native protocol clients — no browser required. Sessions are stored in named Docker volumes:

- `agent-whatsapp-mcp-data` — whatsmeow SQLite session + message history
- `agent-gmessages-mcp-data` — OpenMessage session token + cache

Sessions survive: container restarts, image rebuilds, and `docker compose down` (volumes are not removed). The only trigger for re-pairing is unlinking from the phone.

### Browser-based sessions (local runtime / Outlook)

The local runtime (`make start`) and Docker VNC browser share a Chrome profile at `~/.config/agent-sandbox-local`. Key fixes that make these sessions reliable:

- `--disable-background-networking` removed — was silently killing WhatsApp/Google Messages service workers
- `--disable-sync` removed — was blocking Outlook MSAL token writes
- Graceful Chrome shutdown waits up to 15s for IndexedDB/cookies to flush to disk
- `login.sh` and `run-local.sh` use identical Chrome flags (same stealth extension, same Outlook URL) so service worker fingerprints match between headed login and headless runtime

---

## Playwright / CDP access

```python
from playwright.async_api import async_playwright
import urllib.request, json, urllib.parse

cdp_url = "http://localhost:8080/cdp"
data = json.loads(urllib.request.urlopen(cdp_url + "/json/version").read())
ws_url = data["webSocketDebuggerUrl"]
parsed = urllib.parse.urlparse(ws_url)
ws_url = ws_url.replace(f"{parsed.hostname}:{parsed.port}", "localhost:8080")

async with async_playwright() as p:
    browser = await p.chromium.connect_over_cdp(ws_url)
    page = browser.contexts[0].pages[0]
    await page.goto("https://example.com")
```

---

## Stealth / bot detection

Chromium launches with a stealth Chrome extension (`core/stealth-extension/`) that:

- Removes `navigator.webdriver` and CDP automation globals
- Spoofs `navigator.plugins`, `navigator.mimeTypes`, `navigator.languages`
- Fixes `Permissions.query` to return `granted` for notifications
- Runs at `document_start` in the `MAIN` world — executes before any page script

---

## Android sidecar (optional)

```bash
docker compose -f docker-compose.yml -f docker-compose.android.yml up -d
```

- Android 13 emulator via `budtmo/docker-android:emulator_13.0`
- ADB on port 5555, noVNC desktop on port 6081

---

## Makefile reference

Run `make` for the full list.

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
| `make test` | Run e2e suite against the running local stack |
| `make clean` | Remove `.venv-local` and Chrome profile data |

### Docker commands

| Command | Description |
|---------|-------------|
| `make docker-build` | Rebuild image from scratch (`--no-cache`) |
| `make docker-up` | Start core container |
| `make docker-down` | Stop and remove container |
| `make docker-restart` | `down` + `up` |
| `make docker-logs` | Follow container logs |
| `make docker-shell` | Open bash inside the container |
| `make docker-test` | Run e2e suite against the running container |

### Messaging sidecar commands

| Command | Description |
|---------|-------------|
| `make messaging-up` | Build + start both WhatsApp and Google Messages sidecars |
| `make messaging-down` | Stop both sidecars |
| `make whatsapp-up` | Build + start WhatsApp MCP sidecar |
| `make whatsapp-down` | Stop WhatsApp MCP sidecar |
| `make whatsapp-logs` | Follow WhatsApp MCP logs |
| `make whatsapp-qr` | Alias for `whatsapp-logs` — QR code appears here on first run |
| `make gmessages-up` | Build + start Google Messages MCP sidecar |
| `make gmessages-down` | Stop Google Messages MCP sidecar |
| `make gmessages-logs` | Follow Google Messages MCP logs |
