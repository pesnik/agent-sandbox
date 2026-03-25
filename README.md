# Agent Sandbox

A composable, self-hosted Docker environment where an AI agent can control a full desktop, browser, Android emulator, VS Code, and more — all via MCP tools.

Each capability lives in its own **module**. Modules are opt-in: enable only what you need, restart the container, and the service appears.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Host machine                                               │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  agent-sandbox (Docker container)                     │  │
│  │                                                       │  │
│  │   nginx :8080  ──┬── /vnc/    → noVNC :6080           │  │
│  │   (dashboard)    ├── /vscode/ → code-server :8200     │  │
│  │                  └── /api/    → sandbox API :8091     │  │
│  │                                                       │  │
│  │   supervisord                                         │  │
│  │     ├── tigervncserver :5900  (XFCE4 desktop)         │  │
│  │     ├── websockify     :6080  (noVNC bridge)          │  │
│  │     ├── nginx          :8080                          │  │
│  │     │                                                 │  │
│  │     │   [enabled modules]                             │  │
│  │     ├── chromium       :9222  (CDP remote debug)      │  │
│  │     ├── code-server    :8200                          │  │
│  │     ├── teams (PWA in chromium)                       │  │
│  │     └── uvicorn        :8100  (SMS webhook)           │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  agent-android (optional sidecar)                     │  │
│  │   budtmo/docker-android:emulator_13.0                 │  │
│  │   ADB :5555 | noVNC :6081                             │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  MCP tools (run on host or in container)              │  │
│  │   mcp/tools/browser.py  → CDP → chromium :9222        │  │
│  │   mcp/tools/android.py  → ADB → android  :5555        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Port map

| Port | Service | Description |
|------|---------|-------------|
| 8080 | nginx | Dashboard + reverse proxy |
| 5900 | TigerVNC | Direct VNC access |
| 6080 | noVNC | Browser-based desktop (also at `/vnc/`) |
| 8200 | code-server | VS Code in browser (module: vscode) |
| 8100 | SMS webhook | FastAPI: SMS → Claude → WhatsApp (module: sms) |
| 9222 | Chromium CDP | Remote debugging / MCP browser tool (module: browser) |
| 5555 | ADB | Android device control (module: android) |
| 6081 | Android noVNC | Android screen in browser (module: android) |

---

## Quick start

### 1. Clone and configure

```bash
git clone <this-repo> agent-sandbox
cd agent-sandbox
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY if using the sms module
```

### 2. Enable the modules you want

```bash
# Enable browser automation and VS Code
./scripts/enable-module.sh browser vscode

# Enable SMS forwarding
./scripts/enable-module.sh sms

# Or enable everything at once
./scripts/enable-module.sh browser vscode teams sms
```

### 3. Start the core sandbox

```bash
docker compose up -d --build
```

Open **http://localhost:8080** for the dashboard.

### 4. (Optional) Start the Android sidecar

```bash
docker compose -f docker-compose.yml -f docker-compose.android.yml up -d
```

Then install android-sms-gateway on the emulator:

```bash
WEBHOOK_URL=http://host.docker.internal:8100/sms \
  ./modules/android/install.sh
```

---

## Module reference

### `browser` — Chromium with CDP

Starts Chromium in the desktop session with `--remote-debugging-port=9222`.
Use `mcp/tools/browser.py` to control it from an AI agent.

Enable: `./scripts/enable-module.sh browser`

### `vscode` — VS Code Server

Runs [code-server](https://github.com/coder/code-server) on port 8200.
Access via `http://localhost:8080/vscode/` or directly on port 8200.
No password (intended for local/trusted use only).

Enable: `./scripts/enable-module.sh vscode`

### `teams` — Microsoft Teams PWA

Opens `https://teams.microsoft.com` as a Chromium app with its own profile.
Appears in the noVNC desktop. Sign in once; the profile persists in the
`sandbox-home` Docker volume.

Enable: `./scripts/enable-module.sh teams`

### `sms` — SMS → Claude → WhatsApp bridge

FastAPI service on port 8100. Receives POST requests from android-sms-gateway,
forwards them to Claude (claude-sonnet-4-6), and sends the reply to a WhatsApp
recipient.

**Required env vars:** `ANTHROPIC_API_KEY`, `WHATSAPP_RECIPIENT`

Enable: `./scripts/enable-module.sh sms`

### `android` — Android 13 emulator

Runs `budtmo/docker-android:emulator_13.0` as a Docker sidecar.
Exposes ADB on port 5555 and a noVNC view on port 6081.

Start:
```bash
docker compose -f docker-compose.yml -f docker-compose.android.yml up -d
```

---

## MCP tools (AI agent control)

The `mcp/tools/` directory contains Python scripts the agent calls to control
the sandbox. See [mcp/README.md](mcp/README.md) for full documentation.

| Tool file | Controls | Transport |
|-----------|---------|-----------|
| `browser.py` | Chromium via CDP | Direct async / TCP server |
| `android.py` | Android via ADB | Direct async / TCP server |

Quick example — take a screenshot of the browser:

```python
import asyncio
from mcp.tools.browser import screenshot

result = asyncio.run(screenshot())
# result["data"] is a base64-encoded PNG
```

---

## Adding a new module

1. Create `modules/<name>/supervisord.conf` with a `[program:<name>]` block.
2. Optionally add a `modules/<name>/README.md`.
3. Enable it: `./scripts/enable-module.sh <name>`
4. Restart: `docker compose restart sandbox`

The supervisord conf is copied into `/etc/supervisor/conf.d/` on container start.
Any program defined there will be managed alongside the core services.

If your module needs its own sidecar container, add a
`modules/<name>/docker-compose.yml` and a top-level `docker-compose.<name>.yml`
override following the android pattern.

---

## Disabling a module

```bash
./scripts/disable-module.sh browser
docker compose restart sandbox
```

---

## Building the core image

```bash
docker compose build sandbox
```

Or to force a clean rebuild:

```bash
docker compose build --no-cache sandbox
```
