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
