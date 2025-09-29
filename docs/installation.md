# Installation

This guide covers installing and setting up LabLink for local development and testing.

## System Requirements

- **OS**: Linux, macOS, or Windows with WSL2
- **RAM**: 4GB minimum, 8GB recommended
- **Disk**: 10GB free space
- **Docker**: Version 20.10+
- **Python**: 3.9+ (for local development)

## Installation Methods

### Method 1: Docker Images (Recommended)

The easiest way to run LabLink is using pre-built Docker images.

#### Allocator Service

```bash
# Pull the latest image
docker pull ghcr.io/talmolab/lablink-allocator-image:latest

# Run the allocator
docker run -d \
  --name lablink-allocator \
  -p 5000:5000 \
  ghcr.io/talmolab/lablink-allocator-image:latest
```

Access at [http://localhost:5000](http://localhost:5000)

#### Client Service

```bash
# Pull the latest client image
docker pull ghcr.io/talmolab/lablink-client-base-image:latest

# Run with custom configuration
docker run -d \
  --name lablink-client \
  -e ALLOCATOR_HOST=<allocator_ip> \
  -e ALLOCATOR_PORT=80 \
  ghcr.io/talmolab/lablink-client-base-image:latest
```

### Method 2: Build from Source

For development or customization.

#### Clone the Repository

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink
```

#### Build Allocator Image

```bash
docker build --no-cache \
  -t lablink-allocator \
  -f lablink-allocator/Dockerfile \
  .
```

Run your local build:

```bash
docker run -d \
  --name lablink-allocator \
  -p 5000:5000 \
  lablink-allocator
```

#### Build Client Image

```bash
docker build --no-cache \
  -t lablink-client \
  -f lablink-client-base/lablink-client-base-image/Dockerfile \
  .
```

### Method 3: Local Python Development

For active development on the Python services.

#### Install uv (Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Allocator Service

```bash
cd lablink-allocator/lablink-allocator-service

# Install dependencies
uv sync

# Run with Hydra configuration
uv run python main.py
```

#### Client Service

```bash
cd lablink-client-base/lablink-client-service

# Install dependencies
uv sync

# Configure (edit config.yaml)
nano lablink_client_service/conf/config.yaml

# Run client services (as needed)
uv run python lablink_client_service/subscribe.py
```

## Configuration Files

### Allocator Configuration

Located at `lablink-allocator/lablink-allocator-service/conf/config.yaml`:

```yaml
db:
  dbname: "lablink_db"
  user: "lablink"
  password: "lablink"
  host: "localhost"
  port: 5432
  table_name: "vms"
  message_channel: "vm_updates"

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:latest"
  ami_id: "ami-067cc81f948e50e06"
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"

app:
  admin_user: "admin"
  admin_password: "IwanttoSLEAP"
  region: "us-west-2"

bucket_name: "tf-state-lablink-allocator-bucket"
```

See [Configuration](configuration.md) for detailed option descriptions.

### Client Configuration

Located at `lablink-client-base/lablink-client-service/lablink_client_service/conf/config.yaml`:

```yaml
allocator:
  host: "localhost"
  port: 80

client:
  software: "sleap"
```

## Environment Variables

You can override configuration with environment variables:

### Allocator

```bash
export DB_HOST=your-db-host
export DB_PASSWORD=secure-password
export ADMIN_PASSWORD=secure-admin-password
export AWS_REGION=us-west-2
```

### Client

```bash
export ALLOCATOR_HOST=allocator-ip
export ALLOCATOR_PORT=80
export CLIENT_SOFTWARE=sleap
```

## Testing Your Installation

### Verify Allocator

```bash
# Check if the container is running
docker ps | grep lablink-allocator

# Check logs
docker logs lablink-allocator

# Test the web interface
curl http://localhost:5000
```

### Verify Client

```bash
# Check container
docker ps | grep lablink-client

# Check logs
docker logs lablink-client
```

## Updating

### Pull Latest Images

```bash
# Allocator
docker pull ghcr.io/talmolab/lablink-allocator-image:latest
docker stop lablink-allocator
docker rm lablink-allocator
docker run -d -p 5000:5000 --name lablink-allocator \
  ghcr.io/talmolab/lablink-allocator-image:latest

# Client
docker pull ghcr.io/talmolab/lablink-client-base-image:latest
```

### Update from Source

```bash
cd lablink
git pull origin main
docker build --no-cache -t lablink-allocator \
  -f lablink-allocator/Dockerfile .
```

## Uninstallation

### Remove Containers

```bash
docker stop lablink-allocator lablink-client
docker rm lablink-allocator lablink-client
```

### Remove Images

```bash
docker rmi ghcr.io/talmolab/lablink-allocator-image:latest
docker rmi ghcr.io/talmolab/lablink-client-base-image:latest
```

### Clean Build Artifacts

```bash
cd lablink
rm -rf lablink-allocator/.terraform
rm -rf lablink-allocator/terraform/.terraform
```

## Next Steps

- [**Quickstart**](quickstart.md): Deploy to AWS quickly
- [**Configuration**](configuration.md): Customize LabLink
- [**Development**](testing.md): Run tests and contribute

## Troubleshooting

See [Troubleshooting](troubleshooting.md) for common installation issues.