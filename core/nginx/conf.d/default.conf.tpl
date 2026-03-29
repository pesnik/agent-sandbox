server {
    listen 8080 default_server;
    server_name _;
    absolute_redirect off;
    port_in_redirect off;

    # -------------------------------------------------------------------------
    # Dashboard — index page listing all available services
    # -------------------------------------------------------------------------
    location = ${BASE_PATH}/ {
        default_type text/html;
        return 200 '<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Sandbox</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e2e8f0; min-height: 100vh;
         display: flex; flex-direction: column; align-items: center;
         padding: 40px 20px; }
  h1 { font-size: 2rem; font-weight: 700; margin-bottom: 8px; color: #fff; }
  p.sub { color: #94a3b8; margin-bottom: 40px; font-size: 0.95rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
          gap: 20px; width: 100%; max-width: 900px; }
  .card { background: #1e2130; border: 1px solid #2d3348; border-radius: 12px;
          padding: 24px; text-decoration: none; color: inherit;
          transition: border-color 0.2s, transform 0.2s; }
  .card:hover { border-color: #6366f1; transform: translateY(-2px); }
  .card h2 { font-size: 1.1rem; font-weight: 600; margin-bottom: 6px; color: #a5b4fc; }
  .card p { font-size: 0.85rem; color: #94a3b8; margin-bottom: 12px; }
  .badge { display: inline-block; font-size: 0.75rem; padding: 2px 8px;
           border-radius: 999px; background: #1a2740; color: #60a5fa;
           border: 1px solid #2563eb33; }
</style>
</head>
<body>
<h1>Agent Sandbox</h1>
<p class="sub">Composable AI agent infrastructure. Each card is an enabled module.</p>
<div class="grid">
  <a class="card" href="${BASE_PATH}/vnc/vnc.html?path=${NOVNC_WEBSOCKIFY_PATH}">
    <h2>noVNC Desktop</h2>
    <p>Full XFCE4 desktop streamed over WebSocket. Open this in your browser to interact with GUI apps.</p>
    <span class="badge">${BASE_PATH}/vnc/ (WebSocket)</span>
  </a>
  <a class="card" href="${BASE_PATH}/vscode/">
    <h2>VS Code Server</h2>
    <p>Browser-based VS Code connected to /root. No authentication required.</p>
    <span class="badge">${BASE_PATH}/vscode/</span>
  </a>
  <a class="card" href="${BASE_PATH}/v1/docs">
    <h2>REST API v1</h2>
    <p>FastAPI endpoints for shell, files, and browser control. Interactive OpenAPI docs.</p>
    <span class="badge">${BASE_PATH}/v1/docs</span>
  </a>
  <a class="card" href="${BASE_PATH}/mcp/sse">
    <h2>MCP Server</h2>
    <p>Model Context Protocol — 12 agent tools over SSE. Connect your AI agent here.</p>
    <span class="badge">${BASE_PATH}/mcp/sse</span>
  </a>
</div>
</body>
</html>';
    }

    # -------------------------------------------------------------------------
    # noVNC — WebSocket + static assets
    # -------------------------------------------------------------------------
    location ${BASE_PATH}/vnc/ {
        proxy_pass http://127.0.0.1:6080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # noVNC WebSocket endpoint — path configured via ?path= query param in the
    # dashboard link so each instance uses its own prefixed websockify path.
    location ${BASE_PATH}/websockify {
        proxy_pass http://127.0.0.1:6080/websockify;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # -------------------------------------------------------------------------
    # VS Code Server (code-server, enabled by vscode module)
    # -------------------------------------------------------------------------
    location ${BASE_PATH}/vscode/ {
        proxy_pass http://127.0.0.1:8200/;
        proxy_redirect / ${BASE_PATH}/vscode/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # -------------------------------------------------------------------------
    # Internal sandbox API
    # -------------------------------------------------------------------------
    location ${BASE_PATH}/api/ {
        proxy_pass http://127.0.0.1:8091/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # -------------------------------------------------------------------------
    # REST API v1
    # -------------------------------------------------------------------------
    location ${BASE_PATH}/v1/ {
        proxy_pass http://127.0.0.1:8091/v1/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }

    # -------------------------------------------------------------------------
    # MCP server (SSE — long-lived connections)
    # -------------------------------------------------------------------------
    location ${BASE_PATH}/mcp/ {
        proxy_pass http://127.0.0.1:8079/mcp/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
        proxy_cache off;
    }

    # -------------------------------------------------------------------------
    # Chromium CDP proxy — rewrites ws://localhost:9222 → ws://$host
    # so Playwright connect_over_cdp works through nginx on port 8080
    # -------------------------------------------------------------------------
    location ${BASE_PATH}/cdp/ {
        proxy_pass http://127.0.0.1:9222/;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }

    # Chromium DevTools WebSocket passthrough (used after URL rewrite above)
    location ${BASE_PATH}/devtools/ {
        proxy_pass http://127.0.0.1:9222/devtools/;
        proxy_http_version 1.1;
        proxy_set_header Host localhost;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }

    # -------------------------------------------------------------------------
    # Health check endpoint — always at /healthz regardless of BASE_PATH
    # -------------------------------------------------------------------------
    location /healthz {
        default_type text/plain;
        return 200 "ok\n";
    }
}
