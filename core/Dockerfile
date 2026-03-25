FROM ubuntu:22.04

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
    # noVNC / websockify
    novnc \
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
    && locale-gen en_US.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# noVNC is installed at /usr/share/novnc — symlink a predictable path
RUN ln -sf /usr/share/novnc /opt/novnc

# Create required directories
RUN mkdir -p \
    /etc/supervisor/conf.d \
    /var/log/supervisor \
    /sandbox/modules/enabled \
    /root/.vnc

# Copy supervisord configuration
COPY supervisord/supervisord.conf /etc/supervisor/supervisord.conf
COPY supervisord/conf.d/vnc.conf   /etc/supervisor/conf.d/vnc.conf
COPY supervisord/conf.d/novnc.conf /etc/supervisor/conf.d/novnc.conf
COPY supervisord/conf.d/nginx.conf /etc/supervisor/conf.d/nginx.conf

# Copy nginx configuration
COPY nginx/nginx.conf       /etc/nginx/nginx.conf
COPY nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Remove default nginx site
RUN rm -f /etc/nginx/sites-enabled/default

EXPOSE 8080 5900 6080

ENTRYPOINT ["/entrypoint.sh"]
