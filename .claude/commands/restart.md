Restart the sandbox container (picks up supervisord conf changes without a full rebuild).

```bash
cd /Users/r_hasan/VibeChecks/autumn/agent-sandbox && docker compose restart sandbox
```

Note: if you changed the Dockerfile or any file copied at build time (nginx conf, stealth extension, api/, mcp_server/), use `/build` instead — restart won't pick up image-level changes.
