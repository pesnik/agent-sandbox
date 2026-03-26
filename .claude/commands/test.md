Run the full e2e test suite against the live container. Container must already be up.

```bash
cd /Users/r_hasan/VibeChecks/autumn/agent-sandbox && python tests/e2e.py
```

Expected: 37/37 passing. If the container isn't running, start it first:

```bash
docker compose up -d
```
