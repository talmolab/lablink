# Adapting LabLink for Your Research Software

This guide walks you through customizing LabLink for your own research software, beyond the default SLEAP configuration.

## Overview

LabLink is designed to be **software-agnostic**. While it ships with SLEAP as the default research software, you can adapt it for any computational workflow that can run in Docker.

## Adaptation Checklist

- [ ] Create custom Docker image with your software
- [ ] Configure Git repository (if needed)
- [ ] Update LabLink configuration
- [ ] Test locally
- [ ] Deploy to AWS

## Step-by-Step Guide

### Step 1: Create Your Docker Image

Your Docker image should contain:

1. Base OS (Ubuntu, Debian, etc.)
2. Your research software and dependencies
3. LabLink client service (optional, for health monitoring)

#### Option A: Extend LabLink Client Base

Build on top of the existing LabLink client image:

**`Dockerfile`**:
```dockerfile
FROM ghcr.io/talmolab/lablink-client-base-image:latest

# Install your software
RUN apt-get update && apt-get install -y \
    your-dependencies \
    && rm -rf /var/lib/apt/lists/*

# Install your Python package
COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

# Copy your code
COPY your_software/ /app/your_software/

# Set entrypoint
CMD ["python", "/app/your_software/main.py"]
```

#### Option B: Build from Scratch

Create a completely custom image:

**`Dockerfile`**:
```dockerfile
FROM ubuntu:20.04

# Install basic dependencies
RUN apt-get update && apt-get install -y \
    python3.9 \
    python3-pip \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install your research software
RUN pip3 install your-research-package

# Optional: Include LabLink client for monitoring
COPY --from=ghcr.io/talmolab/lablink-client-base-image:latest \
    /app/lablink-client-service \
    /app/lablink-client-service

# Your startup script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

#### Build and Push

```bash
# Build your image
docker build -t ghcr.io/your-org/your-research-image:latest .

# Test locally
docker run -it ghcr.io/your-org/your-research-image:latest

# Push to registry
docker login ghcr.io
docker push ghcr.io/your-org/your-research-image:latest
```

!!! tip "GitHub Container Registry"
    Use GitHub Container Registry (ghcr.io) for free image hosting. See [GitHub Packages](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

### Step 2: Prepare Your Code Repository

If your research code lives in a Git repository, LabLink can automatically clone it onto each VM.

**Requirements**:
- Public repository (or configure SSH keys for private)
- Code that can run non-interactively
- Dependencies installable via package manager

**Example Repository Structure**:
```
your-research-repo/
├── README.md
├── requirements.txt
├── setup.py (or pyproject.toml)
├── your_package/
│   ├── __init__.py
│   ├── main.py
│   └── analysis.py
├── configs/
│   └── default_config.yaml
└── scripts/
    └── run_analysis.sh
```

**Entrypoint**: Ensure your code has a clear entrypoint (script, main function, etc.)

### Step 3: Update LabLink Configuration

Edit the allocator configuration to use your custom image and repository.

**`lablink-allocator/lablink-allocator-service/conf/config.yaml`**:

```yaml
machine:
  machine_type: "g4dn.xlarge"  # Choose appropriate instance type
  image: "ghcr.io/your-org/your-research-image:latest"
  ami_id: "ami-067cc81f948e50e06"  # Ubuntu 20.04 + Docker (us-west-2)
  repository: "https://github.com/your-org/your-research-code.git"
  software: "your-software-name"

# ... rest of config
```

**Key Fields**:

- **`image`**: Your Docker image from Step 1
- **`repository`**: Your Git repository (or empty string if none)
- **`software`**: Identifier for your software (used by client service)
- **`machine_type`**: EC2 instance type appropriate for your workload

### Step 4: Test Locally

Before deploying to AWS, test your setup locally.

#### Run Your Docker Image

```bash
docker run -d \
  --name test-client \
  -e ALLOCATOR_HOST=localhost \
  -e ALLOCATOR_PORT=5000 \
  ghcr.io/your-org/your-research-image:latest
```

#### Check Logs

```bash
docker logs test-client
```

Verify:
- Image starts without errors
- Dependencies are available
- Your code runs as expected

#### Test Full Stack

Run both allocator and your client locally:

```bash
# Terminal 1: Start allocator
docker run -d -p 5000:5000 --name allocator \
  ghcr.io/talmolab/lablink-allocator-image:latest

# Terminal 2: Start your client
docker run -d --name client \
  -e ALLOCATOR_HOST=host.docker.internal \
  -e ALLOCATOR_PORT=5000 \
  ghcr.io/your-org/your-research-image:latest

# Check allocator web UI
open http://localhost:5000
```

### Step 5: Deploy to AWS

Once local testing succeeds, deploy to AWS.

#### Update Configuration

Commit your configuration changes:

```bash
git add lablink-allocator/lablink-allocator-service/conf/config.yaml
git commit -m "Configure LabLink for [your software]"
git push
```

#### Deploy via Terraform

```bash
cd lablink-allocator

terraform init

terraform apply \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=linux-amd64-latest-test"
```

#### Verify Deployment

1. Get allocator IP:
   ```bash
   terraform output ec2_public_ip
   ```

2. Access web interface: `http://<ec2_ip>:80`

3. Create client VMs via admin interface

4. Monitor VM creation and status

## Advanced Customization

### Custom AMI

For faster VM startup, create a custom AMI with your software pre-installed:

```bash
# Launch base instance
aws ec2 run-instances --image-id ami-067cc81f948e50e06 ...

# SSH in and install your software
ssh -i key.pem ubuntu@<instance-ip>
sudo apt-get update
# ... install your software

# Create AMI
aws ec2 create-image \
  --instance-id i-xxxxx \
  --name "your-software-ami" \
  --description "Custom AMI with your software"

# Use in config.yaml
machine:
  ami_id: "ami-your-custom-ami"
```

Benefits:
- Faster VM startup
- Pre-installed dependencies
- Consistent environment

### Environment-Specific Configurations

Create separate configs for different workloads:

**`conf/config-cpu.yaml`**:
```yaml
machine:
  machine_type: "c5.2xlarge"  # CPU-optimized
  image: "ghcr.io/your-org/your-research-image-cpu:latest"
  software: "your-software-cpu"
```

**`conf/config-gpu.yaml`**:
```yaml
machine:
  machine_type: "p3.2xlarge"  # GPU-optimized
  image: "ghcr.io/your-org/your-research-image-gpu:latest"
  software: "your-software-gpu"
```

Use with:
```bash
python main.py --config-name=config-gpu
```

### Multi-Software Support

Support multiple research software packages in one deployment:

```yaml
# Use software identifier to select behavior
machine:
  software: "multi"  # Or pass dynamically

# Client code checks software identifier:
# if config.client.software == "sleap":
#     run_sleap()
# elif config.client.software == "your_tool":
#     run_your_tool()
```

### Private Docker Registries

Use private registries (Docker Hub, ECR):

1. Store registry credentials in AWS Secrets Manager
2. Update user data script to authenticate:
   ```bash
   aws ecr get-login-password --region us-west-2 | \
     docker login --username AWS --password-stdin <account>.dkr.ecr.us-west-2.amazonaws.com
   ```
3. Reference private image:
   ```yaml
   image: "<account>.dkr.ecr.us-west-2.amazonaws.com/your-image:latest"
   ```

### Custom Health Checks

Implement software-specific health monitoring:

**`your_health_check.py`**:
```python
import requests

def check_health():
    """Check if your software is healthy."""
    # Example: Check GPU availability
    try:
        import torch
        assert torch.cuda.is_available()
    except:
        return False

    # Example: Check disk space
    import shutil
    _, _, free = shutil.disk_usage("/")
    if free < 10 * 1024**3:  # Less than 10GB
        return False

    return True

def report_to_allocator(status):
    """Report status to allocator."""
    requests.post(
        f"http://{ALLOCATOR_HOST}:{ALLOCATOR_PORT}/health",
        json={"status": "healthy" if status else "unhealthy"}
    )
```

## Example: Adapting for PyTorch Training

Complete example for a PyTorch training workflow.

### Dockerfile

```dockerfile
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu20.04

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3.9 python3-pip git \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch
RUN pip3 install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu118

# Install your training code dependencies
COPY requirements.txt /app/
RUN pip3 install -r /app/requirements.txt

# Copy training scripts
COPY train.py /app/
COPY utils/ /app/utils/

WORKDIR /app
CMD ["python3", "train.py"]
```

### Configuration

```yaml
machine:
  machine_type: "g5.2xlarge"  # A10G GPU
  image: "ghcr.io/your-org/pytorch-training:latest"
  repository: "https://github.com/your-org/training-data.git"
  software: "pytorch-training"
  ami_id: "ami-067cc81f948e50e06"
```

### Training Script

**`train.py`**:
```python
import torch
import sys

def main():
    # Check GPU
    if not torch.cuda.is_available():
        print("ERROR: No GPU available")
        sys.exit(1)

    print(f"Using GPU: {torch.cuda.get_device_name(0)}")

    # Your training code here
    model = YourModel().cuda()
    optimizer = torch.optim.Adam(model.parameters())

    # Training loop
    for epoch in range(100):
        train_epoch(model, optimizer)
        print(f"Epoch {epoch} complete")

if __name__ == "__main__":
    main()
```

## Troubleshooting

### Image Won't Start

**Check**:
```bash
docker logs <container>
```

**Common issues**:
- Missing dependencies
- Incorrect entrypoint
- Permission errors

### Repository Clone Fails

**Check**:
- Repository URL is correct
- Repository is public (or SSH keys configured)
- Network connectivity from VM

### Software Not Found

**Check**:
- Software installed in Docker image
- PATH environment variable set correctly
- Dependencies installed

### Performance Issues

**Check**:
- Instance type appropriate for workload
- GPU drivers installed (for GPU instances)
- Sufficient disk space

## Best Practices

1. **Test locally first**: Always test Docker images locally before AWS deployment
2. **Pin versions**: Use specific tags (`v1.0.0`) not `:latest` in production
3. **Minimize image size**: Remove unnecessary dependencies
4. **Document requirements**: Clear README for your custom setup
5. **Version your images**: Tag images with version numbers
6. **Use multi-stage builds**: Reduce final image size
7. **Cache dependencies**: Layer Dockerfile for faster builds

## Next Steps

- **[Deployment](deployment.md)**: Deploy your customized setup
- **[Workflows](workflows.md)**: Set up CI/CD for your images
- **[Configuration](configuration.md)**: Fine-tune your settings
- **[FAQ](faq.md)**: Common customization questions

## Need Help?

- Check [Troubleshooting](troubleshooting.md) for common issues
- Review [example configurations](https://github.com/talmolab/lablink/tree/main/examples) (if available)
- Open an [issue on GitHub](https://github.com/talmolab/lablink/issues)