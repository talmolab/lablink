FROM ghcr.io/astral-sh/uv:0.10-python3.11-trixie-slim

# Build argument for package version
ARG PACKAGE_VERSION=0.0.3a0

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV CONFIG_DIR=/config
ENV CONFIG_NAME=config.yaml
VOLUME [ "/config" ]

# Install dependencies
RUN apt-get update && apt-get install -y \
    postgresql postgresql-contrib \
    rsync \
    openssh-client \
    libpq-dev && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y curl unzip && \
    curl -fsSL https://releases.hashicorp.com/terraform/1.6.6/terraform_1.6.6_linux_amd64.zip -o /tmp/terraform.zip && \
    unzip /tmp/terraform.zip -d /usr/local/bin && \
    rm /tmp/terraform.zip && \
    rm -rf /var/lib/apt/lists/*

# nginx is the only network-facing process in this container.
# noVNC is served from /usr/share/kasmvnc/www/ — the Kasm-bundled
# viewer that ships in the kasmvncserver .deb. We MUST NOT use
# Debian's generic `novnc` package: it sends RFB extension message
# types (e.g. 97) that KasmVNC's stricter parser rejects, killing the
# connection on the first mouse/keyboard event. Kasm's bundled noVNC
# is the only viewer that's protocol-compatible with kasmvncserver.
ARG KASMVNC_VERSION=1.4.0
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx curl ca-certificates && \
    curl -L -o /tmp/kasmvncserver.deb \
      "https://github.com/kasmtech/KasmVNC/releases/download/v${KASMVNC_VERSION}/kasmvncserver_jammy_${KASMVNC_VERSION}_amd64.deb" && \
    apt-get install -y --no-install-recommends /tmp/kasmvncserver.deb && \
    rm /tmp/kasmvncserver.deb && \
    rm -rf /var/lib/apt/lists/*

# Fix the bundled noVNC viewer's RFB VncAuth handshake. nginx (above)
# serves /static/novnc/ from /usr/share/kasmvnc/www/ on THIS container,
# so the browser-loaded bundle is the allocator's, not the client's.
# The Kasm fork hardcodes `this._rfbCredentials.password=""` immediately
# before `genDES` in `_negotiateStdVNCAuth`, which kills the page's
# `?password=<cred>` and makes the browser send a zero-key challenge
# response — KasmVNC then rejects every login with
# `AuthFailureException`. Targeted, idempotent sed.
RUN sed -i 's/this\._rfbCredentials\.password="";//g' \
    /usr/share/kasmvnc/www/assets/ui-*.js

COPY lablink-nginx.conf /etc/nginx/conf.d/lablink.conf

# Disable nginx's default site so it doesn't compete with lablink-nginx.conf.
RUN rm -f /etc/nginx/sites-enabled/default

# Set working directory
WORKDIR /app

# Copy PostgreSQL config
COPY pg_hba.conf /etc/postgresql/15/main/pg_hba.conf

# Install package from PyPI using UV in explicit venv location
RUN uv init --python 3.11 --no-readme && \
    uv venv /app/.venv && \
    uv add lablink-allocator-service==${PACKAGE_VERSION} --no-cache

# Ensure terraform directory has write permissions for state files
RUN chmod -R 777 /app/.venv/lib/python*/site-packages/lablink_allocator_service/terraform/

# Expose ports for Flask
EXPOSE 5000

# Copy and set permissions for startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Set the entrypoint script to start the Flask application
CMD ["/bin/bash", "-c", "/app/start.sh"]

