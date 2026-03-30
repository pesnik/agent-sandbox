---
name: read-whatsapp
description: Use this skill when reading messages from WhatsApp via the agent-sandbox REST API — e.g. "read messages from Furkan", "check WhatsApp chat with <name>", "get WhatsApp messages from <contact>", or when /v1/whatsapp/read returns 0 messages, 404, or 503.
version: 1.0.0
---

# Read WhatsApp Messages via agent-sandbox

## Quick path

```bash
curl -s -X POST http://localhost:8091/v1/whatsapp/read \
  -H 'Content-Type: application/json' \
  -d '{"chat": "Furkan", "limit": 20}'
```

Returns: `{"chat": "Furkan", "messages": [{time, sender, text}, ...], "count": N}`

---

## Diagnostics

### 1. Is WhatsApp Web open and logged in?

```bash
curl -s http://localhost:9222/json | python3 -c "
import json,sys
tabs = json.load(sys.stdin)
wa = [t for t in tabs if 'whatsapp' in t.get('url','')]
print('WA tabs:', len(wa))
"
```

If no WhatsApp tab: open VNC (port 6080), navigate to https://web.whatsapp.com, and scan the QR code.

### 2. Activate the WhatsApp tab before reading

The `evaluate` endpoint always targets the **currently active tab**. Activate WhatsApp explicitly:

```bash
# Get WhatsApp tab ID
WA_ID=$(curl -s http://localhost:9222/json | python3 -c "
import json,sys
tabs=json.load(sys.stdin)
wa=[t for t in tabs if 'web.whatsapp.com' in t.get('url','') and 'sw.js' not in t.get('url','')]
print(wa[0]['id'] if wa else '')
")
curl -s "http://localhost:9222/json/activate/$WA_ID" > /dev/null
sleep 1
```

### 3. Is the chat in the visible sidebar?

WhatsApp sidebar shows the most recent ~20–30 chats. If the contact hasn't messaged recently, they may not be visible:

```bash
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  --data-raw '{"js": "Array.from(document.querySelectorAll(\"#pane-side span[title]\")).map(el=>el.getAttribute(\"title\")).filter((v,i,a)=>a.indexOf(v)===i).join(\"|\")"}' \
  | python3 -c "import sys,json; [print(n) for n in json.load(sys.stdin).get('result','').split('|') if n]"
```

**If the chat is NOT listed** → scroll the sidebar to load it (see below).

---

## Scrolling the sidebar to find a chat

WhatsApp sidebar uses virtual scrolling. Use the native CDP scroll endpoint:

```bash
# Get #pane-side center coordinates first
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  --data-raw '{"js": "const p=document.getElementById(\"pane-side\"); p ? p.getBoundingClientRect().left+\",\"+p.getBoundingClientRect().top+\",\"+p.getBoundingClientRect().width+\",\"+p.getBoundingClientRect().height : \"not found\""}'
# e.g. → "65,154,511,559"  → center x=320, y=434

# Scroll down in batches until the contact appears
for i in 1 2 3 4 5 6 7 8 10; do
  curl -s -X POST http://localhost:8091/v1/browser/scroll \
    -H 'Content-Type: application/json' \
    -d '{"x": 320, "y": 434, "delta_y": 800}' > /dev/null
  sleep 0.8
done
```

Then verify the contact is in the DOM and retry `/v1/whatsapp/read`.

---

## "Syncing older messages" — chat opens but returns 0 messages

When a chat hasn't been opened in a while, WhatsApp Web needs to sync history from the phone. The chat header shows **"Syncing older messages. Click to see progress."**

**Fix:** wait for sync to complete (usually 10–30 seconds), then retry:

```bash
# Wait and poll until messages appear
for i in $(seq 1 6); do
  sleep 5
  COUNT=$(curl -s -X POST http://localhost:8091/v1/whatsapp/read \
    -H 'Content-Type: application/json' \
    -d '{"chat": "Furkan", "limit": 5}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))")
  echo "Attempt $i: $COUNT messages"
  [ "$COUNT" -gt 0 ] && break
done
```

If sync never completes: check that the phone has an active internet connection and WhatsApp is running in the background.

---

## Message format

Each message has:

| Field | Description | Example |
|-------|-------------|---------|
| `time` | Timestamp from `data-pre-plain-text` | `"9:32 AM, 3/30/2026"` |
| `sender` | Contact name or `"You"` | `"Furkan"` |
| `text` | Message body | `"Hey, how are you?"` |

---

## Known failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `503 WhatsApp Web tab not found` | No WhatsApp tab open | Open `https://web.whatsapp.com` in the browser |
| `503 WhatsApp not logged in` | QR not scanned or session expired | Open VNC (port 6080), navigate to WhatsApp Web, scan QR |
| `404 Chat not found in sidebar` | Contact not in visible sidebar (not recent) | Activate WA tab, scroll sidebar via `/v1/browser/scroll` at `#pane-side` center |
| `count: 0` after opening chat | "Syncing older messages" — history pulling from phone | Wait 10–30s and retry; ensure phone is online |
| Scroll goes to wrong tab | Outlook or another tab is active | Activate WhatsApp tab via `curl http://localhost:9222/json/activate/<id>` first |
