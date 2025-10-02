# LabLink Client Base Docker Image

**Docker image for LabLink client VMs with GPU support.**

[![GitHub Container Registry](https://img.shields.io/badge/ghcr.io-lablink--client--base--image-blue)](https://github.com/talmolab/lablink/pkgs/container/lablink-client-base-image)
[![License](https://img.shields.io/github/license/talmolab/lablink)](https://github.com/talmolab/lablink/blob/main/LICENSE)

This Docker image provides the base environment for LabLink client VMs, including NVIDIA GPU support, Chrome Remote Desktop, and the client service package.

---

## 📦 What's Included

- **NVIDIA CUDA 11.6.1**: GPU support with cuDNN 8
- **Ubuntu 20.04**: Base operating system
- **Chrome Remote Desktop**: Remote desktop access
- **lablink-client-service**: Client service package ([lablink-client-service](../lablink-client-service/))
- **Docker**: Container runtime for research workloads
- **Python 3.9+**: Runtime environment
- **GPU Utilities**: nvidia-smi, CUDA samples

**Base Image**: `nvidia/cuda:11.6.1-cudnn8-devel-ubuntu20.04`

**Image Size**: ~10.1 GB

---

## 🚀 Quick Start

### Pull the Image

```bash
docker pull ghcr.io/talmolab/lablink-client-base-image:latest
```

### Run the Container

```bash
docker run --gpus all \
  -e ALLOCATOR_HOST=your-allocator.com \
  -it ghcr.io/talmolab/lablink-client-base-image:latest
```

### Test GPU Access

Inside the container:

```bash
nvidia-smi
```

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
docker pull ghcr.io/talmolab/lablink-client-base-image:latest

# Test build from specific branch
docker pull ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test-test

# Specific version
docker pull ghcr.io/talmolab/lablink-client-base-image:linux-amd64-v0.1.5
```

---

## 🔧 Configuration

### Environment Variables

- **`ALLOCATOR_HOST`** (required): Hostname of the allocator service
- **`ALLOCATOR_PORT`** (optional): Port of the allocator service (default: 5000)

### Run with Configuration

```bash
docker run --gpus all \
  -e ALLOCATOR_HOST=allocator.example.com \
  -e ALLOCATOR_PORT=5000 \
  -it ghcr.io/talmolab/lablink-client-base-image:latest
```

### Mount Volumes

To persist data or mount code:

```bash
docker run --gpus all \
  -v /path/to/data:/data \
  -v /path/to/code:/workspace \
  -e ALLOCATOR_HOST=your-allocator.com \
  -it ghcr.io/talmolab/lablink-client-base-image:latest
```

---

## 🎮 Docker Run Options

Useful Docker flags for running the client image:

| Flag | Purpose |
|------|---------|
| `--gpus all` | Enable all GPUs |
| `-it` | Interactive terminal |
| `--rm` | Auto-remove container on exit |
| `-v /host:/container` | Mount volume |
| `-e VAR=value` | Set environment variable |
| `-p 3389:3389` | Expose remote desktop port |
| `--name my-client` | Name the container |

### Examples

**Interactive session with GPU:**
```bash
docker run --gpus all -it --rm \
  -e ALLOCATOR_HOST=allocator.example.com \
  ghcr.io/talmolab/lablink-client-base-image:latest
```

**Detached mode with remote desktop:**
```bash
docker run -d --gpus all \
  -p 3389:3389 \
  -e ALLOCATOR_HOST=allocator.example.com \
  --name lablink-client \
  ghcr.io/talmolab/lablink-client-base-image:latest
```

**With workspace mounted:**
```bash
docker run --gpus all -it --rm \
  -v $(pwd):/workspace \
  -e ALLOCATOR_HOST=allocator.example.com \
  ghcr.io/talmolab/lablink-client-base-image:latest
```

---

## 🏗️ Image Components

### Installed Software

- **NVIDIA CUDA Toolkit**: GPU computing platform
- **cuDNN**: Deep learning library
- **Chrome Remote Desktop**: Remote access
- **Docker**: Container runtime
- **Git**: Version control
- **Python**: Programming environment
- **lablink-client-service**: Client service package

### Service Components

The image automatically starts the client service that:
- Registers with the allocator
- Reports GPU health status
- Manages research workloads
- Handles remote desktop sessions

---

## 🔨 Building Locally

### Prerequisites

- Docker with NVIDIA Container Toolkit installed
- NVIDIA GPU on host machine

### Build from Source

```bash
# From repository root
docker build --no-cache -t lablink-client \
  -f lablink-client-base/lablink-client-base-image/Dockerfile \
  lablink-client-base/lablink-client-base-image
```

### Run Local Build

```bash
docker run --gpus all -it --rm \
  -e ALLOCATOR_HOST=your-allocator.com \
  --name lablink-client \
  lablink-client
```

---

## 🚢 Deployment

This image is designed to be deployed as part of the LabLink infrastructure in client VMs. For deployment instructions, see the **[LabLink Template Repository](https://github.com/talmolab/lablink-template)** (coming soon).

### Cloud Deployment

The client image is typically deployed to AWS EC2 instances with GPU support (e.g., `g4dn.xlarge`, `p3.2xlarge`).

**Terraform deployment example:**
```hcl
resource "aws_instance" "lablink_client" {
  ami           = "ami-gpu-enabled"
  instance_type = "g4dn.xlarge"

  user_data = <<-EOF
    #!/bin/bash
    docker run -d --gpus all \
      -e ALLOCATOR_HOST=${allocator_host} \
      ghcr.io/talmolab/lablink-client-base-image:latest
  EOF
}
```

---

## 🔍 Troubleshooting

### GPU Not Detected

Ensure NVIDIA Container Toolkit is installed on the host:

```bash
# Install NVIDIA Container Toolkit (Ubuntu)
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Test GPU Access

```bash
# Test NVIDIA Docker runtime
docker run --rm --gpus all nvidia/cuda:11.6.1-base-ubuntu20.04 nvidia-smi
```

### View Container Logs

```bash
docker logs lablink-client
docker logs -f lablink-client  # Follow logs
```

### Access Container Shell

```bash
docker exec -it lablink-client bash
```

---

## 🔄 CI/CD

Images are automatically built and published via GitHub Actions:

- **[lablink-images.yml](../../.github/workflows/lablink-images.yml)** - Docker image builds
- Builds triggered on push to `main`, `test`, or feature branches
- Images pushed to `ghcr.io/talmolab/lablink-client-base-image`

---

## 💻 Development Container

For VS Code development inside the container, use the provided devcontainer configuration:

```json
// .devcontainer/devcontainer.json
{
  "name": "LabLink Client Development",
  "image": "ghcr.io/talmolab/lablink-client-base-image:latest",
  "runArgs": ["--gpus", "all"],
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-python.python",
        "ms-python.vscode-pylance"
      ]
    }
  }
}
```

---

## 📚 Documentation

- **[Full Documentation](https://talmolab.github.io/lablink/)** - Complete guide
- **[Client Service Package](../lablink-client-service/)** - Python package README
- **[Configuration](https://talmolab.github.io/lablink/configuration/)** - Configuration options
- **[Deployment](https://talmolab.github.io/lablink/deployment/)** - Deployment guide

---

## 🤝 Contributing

Contributions are welcome! Please see:

- **[Contributing Guide](https://talmolab.github.io/lablink/contributing/)** - How to contribute
- **[Developer Guide (CLAUDE.md)](../../CLAUDE.md)** - Developer overview

---

## 📝 License

BSD-3-Clause License. See [LICENSE](https://github.com/talmolab/lablink/blob/main/LICENSE) for details.

---

## 🔗 Links

- **Container Registry**: https://github.com/talmolab/lablink/pkgs/container/lablink-client-base-image
- **Source Package**: [lablink-client-service](../lablink-client-service/)
- **Documentation**: https://talmolab.github.io/lablink/
- **Repository**: https://github.com/talmolab/lablink
- **Issues**: https://github.com/talmolab/lablink/issues

---

**Questions?** Check the [FAQ](https://talmolab.github.io/lablink/faq/) or open an [issue](https://github.com/talmolab/lablink/issues).
