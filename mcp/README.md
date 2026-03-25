# MCP Tools

This directory contains Model Context Protocol (MCP) tool implementations that let an AI agent control sandbox modules programmatically.

## Structure

```
mcp/
└── tools/
    ├── browser.py   — CDP-based browser automation (Chromium)
    └── android.py   — ADB-based Android device control
```

## How MCP tools work

Each tool file exposes:
- A set of `async def` functions that perform the actual work
- A `TOOL_SCHEMAS` dict describing the JSON schema for each function's parameters
- A TCP server mode (`python3 <tool>.py serve [port]`) that speaks a minimal JSON-RPC protocol

### Request format

```json
{ "tool": "<tool_name>", "params": { ... } }
```

### Response format

```json
{ "result": { ... } }
```

or on error:

```json
{ "error": "description" }
```

List available tools by sending `{ "tool": "__list__" }`.

---

## browser.py

Connects to Chromium via Chrome DevTools Protocol (CDP).

**Prerequisites:** The `browser` module must be enabled so Chromium is running with `--remote-debugging-port=9222`.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `navigate` | `url: str` | Load a URL in the active tab |
| `screenshot` | — | Capture a full-page PNG (base64) |
| `click` | `selector: str` | Click the first element matching a CSS selector |
| `type` | `selector: str`, `text: str` | Focus an element and type text |
| `evaluate` | `js: str` | Run JavaScript and return the result |

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CDP_URL` | `http://localhost:9222` | Chromium CDP endpoint |

**Quick start:**

```bash
# Run the smoke test (navigates to example.com, saves screenshot)
python3 mcp/tools/browser.py

# Start as a TCP MCP server on port 9100
python3 mcp/tools/browser.py serve 9100
```

---

## android.py

Controls an Android device or emulator via `adb`.

**Prerequisites:** The `android` module must be running and ADB must be connected.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `send_sms` | `number: str`, `message: str` | Send an SMS from the device |
| `tap` | `x: int`, `y: int` | Tap a screen coordinate |
| `screenshot` | — | Capture the device screen (base64 PNG) |
| `shell` | `cmd: str` | Run an adb shell command |

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `ADB_HOST` | `localhost` | Hostname or IP of the ADB device |
| `ADB_PORT` | `5555` | TCP port for ADB |
| `ADB_SERIAL` | — | Full serial string (overrides host:port) |

**Quick start:**

```bash
# Run the smoke test (connects, takes screenshot)
python3 mcp/tools/android.py

# Start as a TCP MCP server on port 9101
python3 mcp/tools/android.py serve 9101
```

---

## Adding a new tool

1. Create `mcp/tools/<module>.py`
2. Implement `async def` functions for each tool action
3. Populate `TOOL_SCHEMAS` with the JSON schema for each function
4. Optionally add the TCP server pattern from an existing tool
5. Document it here
