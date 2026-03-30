---
name: read-google-messages
description: Use this skill when reading messages from Google Messages Web via the agent-sandbox REST API — e.g. "read messages from LC_STATUS", "check Family Pack sender", "get messages from <contact>", or when POST /v1/google-messages/read returns 0 messages or 404.
version: 1.0.0
---

# Read Google Messages via agent-sandbox

## Quick path

```bash
curl -s -X POST http://localhost:8091/v1/google-messages/read \
  -H 'Content-Type: application/json' \
  -d '{"chat": "LC_STATUS", "limit": 200}'
```

If this returns `{"messages": [], "count": 0}` or `{"detail": "Conversation '...' not found"}`, follow the diagnostics below.

---

## Diagnostics

### 1. Is the sandbox running?

```bash
curl -s http://localhost:8091/v1/status
# expect: {"services": {"browser": true, ...}}
```

### 2. Is Google Messages open in the browser?

```bash
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"js": "document.title"}'
# expect: "Google Messages for web: Conversations"
```

If not, navigate there:
```bash
curl -s -X POST http://localhost:8091/v1/browser/navigate \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://messages.google.com/web/conversations"}'
sleep 5
```

### 3. Is the chat in the visible sidebar (first ~25 items)?

```bash
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"js": "Array.from(document.querySelectorAll(\"mws-conversation-list-item\")).map(el => (el.querySelector(\".name,h3\")||{innerText:\"\"}).innerText.trim()).filter(n=>n).join(\"|\")"}'
```

**If the chat is in this list** → the `scrollIntoView` fix in `_JS_FIND_CHAT` handles off-screen items automatically. Just call `/read` directly.

**If the chat is NOT in this list** → the sidebar uses virtual scrolling; you must scroll to load it into the DOM first (see below).

---

## Scrolling the sidebar to load more conversations

The Google Messages sidebar only renders ~25 conversations in the DOM at a time (virtual scrolling). JS `WheelEvent` dispatch is ignored — use the native CDP scroll endpoint:

```bash
# Scroll down in the sidebar (x≈170, y≈430 is center of conversation list)
for i in 1 2 3 4 5 6 7 8; do
  curl -s -X POST http://localhost:8091/v1/browser/scroll \
    -H 'Content-Type: application/json' \
    -d '{"x": 170, "y": 430, "delta_y": 800}' > /dev/null
  sleep 0.8
done
```

Then check again:
```bash
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"js": "Array.from(document.querySelectorAll(\"mws-conversation-list-item\")).map(el => (el.querySelector(\".name,h3\")||{innerText:\"\"}).innerText.trim()).filter(n=>n).join(\"|\")"}'
```

Repeat scroll batches until the target chat name appears, then call `/read`.

> **Why native scroll?** Angular's virtual-scroll ignores synthetic `WheelEvent` from JS.
> `POST /v1/browser/scroll` dispatches `Input.dispatchMouseEvent` type `mouseWheel` via CDP — the only way to trigger true scroll-driven DOM loading.

---

## `/v1/browser/scroll` reference

```json
POST /v1/browser/scroll
{
  "x": 170,
  "y": 430,
  "delta_x": 0,
  "delta_y": 800
}
```

- `x`, `y`: viewport coordinates of the element to scroll (center of sidebar ≈ `170, 430`)
- `delta_y`: positive = scroll down (load later conversations), negative = scroll up

---

## Known issues & fixes

| Symptom | Root cause | Fix |
|---------|-----------|-----|
| `/read` returns 0 messages, chat exists in sidebar | Chat item is below the viewport; `getBoundingClientRect()` returned off-screen coords; `cdp_click_at` clicked outside the window | Fixed in `_JS_FIND_CHAT`: `el.scrollIntoView({block:'center'})` is called before reading rect |
| `/read` returns 404, chat exists on phone | Chat not in DOM — virtual scroll only loads first ~25 items | Scroll sidebar via `/v1/browser/scroll` until chat appears in DOM, then call `/read` |
| Scroll goes to wrong tab | Another tab (e.g. Outlook) was focused when scroll was sent | Navigate to Google Messages first: `POST /v1/browser/navigate {"url": "https://messages.google.com/web/conversations"}` |
