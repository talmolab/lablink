# LabLink Allocator Docker Image

**Docker image for the LabLink Allocator service.**

[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-lablink--allocator--image-blue)](https://github.com/talmolab/lablink/pkgs/container/lablink-allocator-image)
[![License](https://img.shields.io/github/license/talmolab/lablink)](https://github.com/talmolab/lablink/blob/main/LICENSE)

This Docker image packages the LabLink allocator service with PostgreSQL database and Terraform for VM management.

---

## 📦 What's Included

- **Flask Application**: Web interface and API ([lablink-allocator-service](lablink-allocator-service/))
- **PostgreSQL Database**: VM state and assignment tracking
- **Terraform**: Infrastructure provisioning for client VMs
- **Startup Scripts**: Automatic database initialization and service startup

---

## 🚀 Quick Start

### Pull the Image

```bash
docker pull ghcr.io/talmolab/lablink-allocator-image:latest
```

### Run the Container

```bash
docker run -d -p 5000:5000 --name lablink-allocator \
  ghcr.io/talmolab/lablink-allocator-image:latest
```

The allocator will be accessible at `http://localhost:5000`

---

## 🏷️ Image Tags

Images are automatically built and pushed to GitHub Container Registry:

- **`latest`** - Latest stable release from `main` branch
- **`linux-amd64-latest`** - Platform-specific latest
- **`linux-amd64-<branch>-test`** - Test builds from feature branches
- **`linux-amd64-<tag>`** - Specific version releases

### Pull a Specific Version

```bash
# Latest stable
docker pull ghcr.io/talmolab/lablink-allocator-image:latest

# Test build from specific branch
docker pull ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test-test

# Specific version
docker pull ghcr.io/talmolab/lablink-allocator-image:linux-amd64-v0.3.0
```

---

## 🔧 Configuration

The allocator service is configured via environment variables or mounted configuration files.

### Environment Variables

```bash
docker run -d -p 5000:5000 \
  -e DB_PASSWORD=secure_password \
  -e ADMIN_PASSWORD=admin_password \
  -e AWS_REGION=us-west-2 \
  ghcr.io/talmolab/lablink-allocator-image:latest
```

### Mount Custom Configuration

```bash
docker run -d -p 5000:5000 \
  -v /path/to/config.yaml:/app/lablink-allocator-service/conf/config.yaml \
  ghcr.io/talmolab/lablink-allocator-image:latest
```

See the [Configuration Guide](https://talmolab.github.io/lablink/configuration/) for detailed options.

---

## 🏗️ Image Components

### Directory Structure

```
/app/
├── lablink-allocator-service/   # Python package
│   ├── main.py                  # Flask application
│   ├── database.py              # Database operations
│   ├── conf/                    # Configuration
│   ├── terraform/               # VM provisioning
│   └── templates/               # HTML templates
├── init.sql                     # Database initialization
└── start.sh                     # Container startup script
```

### Installed Components

- **PostgreSQL 12+**: Database server
- **Terraform**: Infrastructure as Code tool
- **Python 3.9+**: Runtime environment
- **Flask**: Web framework
- **lablink-allocator-service**: Python package

---

## 📡 Endpoints

Once running, the allocator provides:

- `GET /` - Home page for VM requests
- `POST /request_vm` - Request VM assignment
- `GET /admin` - Admin dashboard (requires authentication)
- `POST /admin/create` - Create client VMs
- `GET /admin/instances` - View VM list
- `POST /admin/destroy` - Destroy client VMs
- `POST /vm_startup` - Client VM registration (internal)

See the [API Reference](https://talmolab.github.io/lablink/reference/allocator/) for details.

---

## 🔨 Building Locally

### Build from Source

```bash
# From repository root
docker build --no-cache -t lablink-allocator -f lablink-allocator/Dockerfile .
```

### Run Local Build

```bash
docker run -d -p 5000:5000 --name lablink-allocator lablink-allocator
```

### Multi-platform Build

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t lablink-allocator \
  -f lablink-allocator/Dockerfile .
```

---

## 🚢 Deployment

This image is designed to be deployed as part of the LabLink infrastructure. For deployment instructions, see the **[LabLink Template Repository](https://github.com/talmolab/lablink-template)** (coming soon).

### Cloud Deployment

The allocator can be deployed to AWS EC2, Google Cloud, Azure, or any Docker-compatible platform.

**Example: Deploy to AWS EC2**
```bash
# Using Terraform (see template repository)
terraform init
terraform apply
```

---

## 🔍 Troubleshooting

### PostgreSQL Connection Issues

If clients can't connect to PostgreSQL, restart the database:

```bash
docker exec -it lablink-allocator bash
/etc/init.d/postgresql restart
```

### View Logs

```bash
# Container logs
docker logs lablink-allocator

# Follow logs
docker logs -f lablink-allocator
```

### Access Container Shell

```bash
docker exec -it lablink-allocator bash
```

### Check PostgreSQL Status

```bash
docker exec -it lablink-allocator pg_isready -U lablink
```

---

## 🔄 CI/CD

Images are automatically built and published via GitHub Actions:

- **[lablink-images.yml](../.github/workflows/lablink-images.yml)** - Docker image builds
- Builds triggered on push to `main`, `test`, or feature branches
- Images pushed to `ghcr.io/talmolab/lablink-allocator-image`

---

## 📚 Documentation

- **[Full Documentation](https://talmolab.github.io/lablink/)** - Complete guide
- **[Allocator Service Package](lablink-allocator-service/)** - Python package README
- **[Configuration](https://talmolab.github.io/lablink/configuration/)** - Configuration options
- **[Deployment](https://talmolab.github.io/lablink/deployment/)** - Deployment guide
- **[Troubleshooting](https://talmolab.github.io/lablink/troubleshooting/)** - Common issues

---

## 🤝 Contributing

Contributions are welcome! Please see:

- **[Contributing Guide](https://talmolab.github.io/lablink/contributing/)** - How to contribute
- **[Developer Guide (CLAUDE.md)](../CLAUDE.md)** - Developer overview

---

## 📝 License

BSD-3-Clause License. See [LICENSE](https://github.com/talmolab/lablink/blob/main/LICENSE) for details.

---

## 🔗 Links

- **Container Registry**: https://github.com/talmolab/lablink/pkgs/container/lablink-allocator-image
- **Source Package**: [lablink-allocator-service](lablink-allocator-service/)
- **Documentation**: https://talmolab.github.io/lablink/
- **Repository**: https://github.com/talmolab/lablink
- **Issues**: https://github.com/talmolab/lablink/issues

---

**Questions?** Check the [FAQ](https://talmolab.github.io/lablink/faq/) or open an [issue](https://github.com/talmolab/lablink/issues).
