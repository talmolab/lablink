# Installation

## Prerequisites

- Docker 20.10+
- Python 3.9+ (for development)
- 8GB RAM, 10GB disk space

## Install via Docker

=== "Allocator"

    ```bash
    docker pull ghcr.io/talmolab/lablink-allocator-image:latest
    docker run -d -p 5000:5000 --name lablink-allocator \
      ghcr.io/talmolab/lablink-allocator-image:latest
    ```

    Access at http://localhost:5000

=== "Client"

    ```bash
    docker pull ghcr.io/talmolab/lablink-client-base-image:latest
    docker run -d --name lablink-client \
      -e ALLOCATOR_HOST=<allocator_ip> \
      -e ALLOCATOR_PORT=80 \
      ghcr.io/talmolab/lablink-client-base-image:latest
    ```

## Install from source

=== "Clone"

    ```bash
    git clone https://github.com/talmolab/lablink.git
    cd lablink
    ```

=== "Build allocator"

    ```bash
    docker build -t lablink-allocator \
      -f lablink-infrastructure/Dockerfile .
    docker run -d -p 5000:5000 lablink-allocator
    ```

=== "Build client"

    ```bash
    docker build -t lablink-client \
      -f lablink-client-base/lablink-client-base-image/Dockerfile .
    ```

## Python development

=== "Install uv"

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

=== "Allocator"

    ```bash
    cd packages/allocator
    uv sync
    uv run lablink-allocator
    ```

=== "Client"

    ```bash
    cd packages/client
    uv sync
    uv run subscribe
    ```

## Configuration

See [Configuration](configuration.md) for environment variables and config files.

## Next steps

- [Quickstart](quickstart.md) - Deploy to AWS
- [Configuration](configuration.md) - Customize settings
- [Troubleshooting](troubleshooting.md) - Common issues