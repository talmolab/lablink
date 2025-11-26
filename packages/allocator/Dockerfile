FROM ghcr.io/astral-sh/uv:python3.11-trixie-slim

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
    curl -fsSL https://releases.hashicorp.com/terraform/1.4.6/terraform_1.4.6_linux_amd64.zip -o /tmp/terraform.zip && \
    unzip /tmp/terraform.zip -d /usr/local/bin && \
    rm /tmp/terraform.zip

# Set working directory
WORKDIR /app

# Copy PostgreSQL config
COPY pg_hba.conf /etc/postgresql/15/main/pg_hba.conf

# Install package from PyPI using UV in explicit venv location
RUN uv init --python 3.11 --no-readme && \
    uv venv /app/.venv && \
    uv add lablink-allocator-service==${PACKAGE_VERSION} --no-cache && \
    uv sync

# Ensure terraform directory has write permissions for state files
RUN chmod -R 777 /app/.venv/lib/python*/site-packages/lablink_allocator_service/terraform/

# Expose ports for Flask
EXPOSE 5000

# Copy and set permissions for startup script
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Set the entrypoint script to start the Flask application
CMD ["/bin/bash", "-c", "/app/start.sh"]

