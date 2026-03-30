---
name: read-outlook
description: Use this skill when reading Outlook emails via the agent-sandbox REST API — e.g. "read my emails", "list inbox", "read email from <name>", "check unread emails", or when /v1/outlook/list or /v1/outlook/read returns errors or empty results.
version: 1.0.0
---

# Read Outlook Emails via agent-sandbox

## Quick path

```bash
# List inbox (most recent 20)
curl -s -X POST http://localhost:8091/v1/outlook/list \
  -H 'Content-Type: application/json' \
  -d '{"limit": 20}'

# List unread only
curl -s -X POST http://localhost:8091/v1/outlook/list \
  -H 'Content-Type: application/json' \
  -d '{"limit": 50, "unread_only": true}'

# Read full email by index (from list output)
curl -s -X POST http://localhost:8091/v1/outlook/read \
  -H 'Content-Type: application/json' \
  -d '{"index": 1}'
```

---

## List response format

```json
{
  "emails": [
    {
      "index": 0,
      "convId": "AAQkADM...",
      "unread": true,
      "sender": "Sheikh Masud Hossain",
      "senderEmail": "Smasud@banglalink.net",
      "subject": "ID card access validity revoke",
      "time": "4:38 PM",
      "preview": "Dear concern, Please revoke Access validity..."
    }
  ],
  "count": 7
}
```

## Read response format

```json
{
  "index": 1,
  "subject": "ID card access validity revoke",
  "from": "Sheikh Masud Hossain",
  "to": "To:\u200bSecurity Control Room Officer\u200b",
  "cc": "Cc:\u200bMozammel Haque Bhuiyan;\u200b+7 others",
  "date": "Mon 3/30/2026 4:38 PM",
  "body_text": "Dear concern,\n\nPlease revoke Access validity..."
}
```

---

## Diagnostics

### 1. Is Outlook the active tab?

`/v1/outlook/list` and `/v1/outlook/read` both use `cdp_evaluate` which targets the **active tab**. Outlook must be the active/focused tab.

Check current tab:
```bash
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"js": "window.location.href"}'
# expect: https://outlook.cloud.microsoft/mail/...
```

If not Outlook, the endpoint auto-navigates: `GET https://outlook.cloud.microsoft/mail/inbox`. But if the browser is on a completely different service, activate the Outlook tab first:

```bash
OL_ID=$(curl -s http://localhost:9222/json | python3 -c "
import json,sys
tabs=json.load(sys.stdin)
ol=[t for t in tabs if 'outlook' in t.get('url','')]
print(ol[0]['id'] if ol else '')
")
curl -s "http://localhost:9222/json/activate/$OL_ID" > /dev/null
sleep 1
```

### 2. Is Outlook logged in?

The endpoint checks for `[aria-label="New mail"]`. If absent, it returns `503`.

```bash
curl -s -X POST http://localhost:8091/v1/browser/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"js": "!!document.querySelector(\"[aria-label=\\\\\"New mail\\\\\"]\")"}'
```

If not logged in: open VNC (port 6080), navigate to https://outlook.cloud.microsoft/mail/inbox, and sign in.

### 3. Inbox not loading / email list empty

Outlook may still be loading. Wait 3–5s after navigation and retry. Check visually:

```bash
curl -s http://localhost:8091/v1/browser/screenshot \
  | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('/tmp/ol.png','wb').write(base64.b64decode(d['data']))"
open /tmp/ol.png
```

### 4. `senderEmail` is empty

Outlook only puts the email address in a span's `title` attribute for some email types. The `sender` (display name) is always populated. If you need the email address specifically, read the full email with `/v1/outlook/read` and inspect the `from` field.

---

## Workflow: list then read

```python
import requests

BASE = "http://localhost:8091"

# 1. List inbox
emails = requests.post(f"{BASE}/v1/outlook/list", json={"limit": 20}).json()["emails"]
for e in emails:
    print(f"[{e['index']}] {'*' if e['unread'] else ' '} {e['sender']:<25} {e['subject'][:50]}")

# 2. Read email at index 1
email = requests.post(f"{BASE}/v1/outlook/read", json={"index": 1}).json()
print(email["from"], email["date"])
print(email["body_text"])
```

---

## Known failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `503 Outlook not logged in` | Session expired or not signed in | Open VNC, navigate to Outlook, log in |
| Empty `emails` list | Outlook still loading or wrong tab active | Activate Outlook tab via CDP, wait 3–5s, retry |
| Empty `sender`/`subject` in list | Email row not fully rendered | Retry after brief delay; some rows need focus |
| `from` field empty | Sender span came before subject in DOM | Fixed: reads first SPAN regardless of `@` |
| `404 No email at index N` | Index out of range or reading pane failed to open | Check `count` from list; use valid index |
| Wrong emails shown | Outlook focused on a folder other than inbox | Navigate explicitly: `POST /v1/browser/navigate {"url": "https://outlook.cloud.microsoft/mail/inbox"}` |
