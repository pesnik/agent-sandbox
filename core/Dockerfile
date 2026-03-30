FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:1 \
    VNC_PORT=5900 \
    NOVNC_PORT=6080 \
    NGINX_PORT=8080 \
    HOME=/root \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    # VNC / display stack
    tigervnc-standalone-server \
    tigervnc-common \
    x11-xserver-utils \
    xfce4 \
    xfce4-terminal \
    xfce4-session \
    dbus-x11 \
    # websockify (noVNC 1.4 downloaded separately — apt ships broken 1.0)
    websockify \
    # Web server
    nginx \
    # Process management
    supervisor \
    # Utilities
    curl \
    wget \
    git \
    unzip \
    ca-certificates \
    # Python
    python3 \
    python3-pip \
    python3-venv \
    # Fonts
    fonts-noto \
    fonts-noto-color-emoji \
    fonts-liberation \
    # Locale
    locales \
    # envsubst (for nginx template rendering at startup)
    gettext-base \
    && locale-gen en_US.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# noVNC 1.4.0 — download directly (apt ships broken 1.0.0 on Ubuntu 22.04)
RUN wget -qO /tmp/novnc.tar.gz \
      https://github.com/novnc/noVNC/archive/refs/tags/v1.4.0.tar.gz && \
    tar -xzf /tmp/novnc.tar.gz -C /opt && \
    mv /opt/noVNC-1.4.0 /opt/novnc && \
    ln -sf /opt/novnc/vnc.html /opt/novnc/index.html && \
    rm /tmp/novnc.tar.gz

# xdotool for X input automation
RUN apt-get update && apt-get install -y --no-install-recommends \
    xdotool \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# code-server (VS Code in browser)
RUN curl -fsSL https://code-server.dev/install.sh | sh

# Python deps for API and MCP server
COPY api/requirements.txt /tmp/api-requirements.txt
COPY mcp_server/requirements.txt /tmp/mcp-requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/api-requirements.txt -r /tmp/mcp-requirements.txt

# Google Chrome Stable — proper branded browser for VNC desktop
RUN wget -qO /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
    apt-get update && apt-get install -y --no-install-recommends /tmp/google-chrome.deb && \
    apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/google-chrome.deb && \
    echo "/usr/bin/google-chrome-stable" > /opt/chromium-path

# Playwright — Python bindings only, no separate Chromium download needed
# Chrome Stable is used for both VNC display and CDP automation.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers
RUN pip3 install --no-cache-dir playwright && \
    playwright install-deps chromium

# Create required directories
RUN mkdir -p \
    /etc/supervisor/conf.d \
    /var/log/supervisor \
    /sandbox/modules/enabled \
    /root/.vnc \
    /opt/sandbox/api \
    /opt/sandbox/mcp_server

# Copy supervisord configuration
COPY supervisord/supervisord.conf /etc/supervisor/supervisord.conf
COPY supervisord/conf.d/vnc.conf   /etc/supervisor/conf.d/vnc.conf
COPY supervisord/conf.d/novnc.conf /etc/supervisor/conf.d/novnc.conf
COPY supervisord/conf.d/nginx.conf /etc/supervisor/conf.d/nginx.conf
COPY supervisord/conf.d/api.conf    /etc/supervisor/conf.d/api.conf
COPY supervisord/conf.d/mcp.conf   /etc/supervisor/conf.d/mcp.conf
COPY supervisord/conf.d/vscode.conf   /etc/supervisor/conf.d/vscode.conf
COPY supervisord/conf.d/chromium.conf /etc/supervisor/conf.d/chromium.conf

# Copy nginx configuration
COPY nginx/nginx.conf       /etc/nginx/nginx.conf
COPY nginx/conf.d/default.conf.tpl /etc/nginx/conf.d/default.conf.tpl

# Copy API, MCP server, and stealth extension
COPY api/ /opt/sandbox/api/
COPY mcp_server/ /opt/sandbox/mcp_server/
COPY stealth-extension/ /opt/sandbox/stealth-extension/

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Remove default nginx site
RUN rm -f /etc/nginx/sites-enabled/default

EXPOSE 8080 5900 6080 8079 8091

ENTRYPOINT ["/entrypoint.sh"]
