FROM ghcr.io/astral-sh/uv:python3.11-trixie-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV DATABASE_URL=postgresql://lablink:lablink@localhost:5432/lablink_db
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

# Copy application files and requirements
COPY lablink-allocator/lablink-allocator-service /app

COPY lablink-allocator/lablink-allocator-service/pg_hba.conf /etc/postgresql/15/main/pg_hba.conf

# Install Python dependencies using UV
RUN uv venv && uv pip install -r pyproject.toml

COPY lablink-allocator/lablink-allocator-service/generate-init-sql.py /app
RUN uv run generate-init-sql.py

# Expose ports for Flask
EXPOSE 5000

# Copy and set permissions for startup script
COPY lablink-allocator/start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Set the entrypoint script to start the Flask application
CMD ["/bin/bash", "-c", "/app/start.sh"]

