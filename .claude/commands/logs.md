Tail logs from all supervisord-managed services in the running container.

```bash
docker exec agent-sandbox-sandbox-1 tail -f \
  /var/log/supervisor/supervisord.log \
  /var/log/supervisor/chromium.log \
  /var/log/supervisor/chromium-err.log \
  /var/log/supervisor/nginx.log \
  /var/log/supervisor/api.log \
  /var/log/supervisor/mcp.log \
  /var/log/supervisor/vscode.log
```

For a single service, e.g. just the API:

```bash
docker exec agent-sandbox-sandbox-1 tail -f /var/log/supervisor/api.log
```
