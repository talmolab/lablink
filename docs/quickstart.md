# Quickstart

## Prerequisites

- AWS CLI configured ([guide](prerequisites.md#2-aws-cli))
- Terraform installed ([guide](prerequisites.md#3-terraform))
- Docker running ([guide](prerequisites.md#4-docker))

## Test locally

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink
docker pull ghcr.io/talmolab/lablink-allocator-image:latest
docker run -d -p 5000:5000 ghcr.io/talmolab/lablink-allocator-image:latest
```

Access at http://localhost:5000

!!! tip "Default credentials"
    Username: `admin` / Password: `IwanttoSLEAP`

## Deploy to AWS

```bash
cd lablink-allocator
terraform init
terraform apply -var="resource_suffix=dev" -var="allocator_image_tag=linux-amd64-latest-test"
```

Save SSH key:

```bash
terraform output -raw private_key_pem > ~/lablink-dev-key.pem
chmod 600 ~/lablink-dev-key.pem
```

Access:

```bash
# Get IP
terraform output ec2_public_ip

# SSH access
ssh -i ~/lablink-dev-key.pem ubuntu@<ec2_public_ip>

# Web interface
http://<ec2_public_ip>:80
```

## Create VMs

Web UI:
1. Admin → Create Instances
2. Enter count
3. Submit

API:
```bash
curl -X POST http://<allocator_ip>:80/request_vm \
  -d "email=your@email.com" \
  -d "crd_command=your_command"
```

## Cleanup

```bash
terraform destroy -var="resource_suffix=dev"
```

!!! warning
    EC2 instances incur costs. Destroy test resources when done.

## Next steps

- [Configuration](configuration.md) - Customize settings
- [Adapting](adapting.md) - Use your Docker images
- [Deployment](deployment.md) - Production setup
- [Troubleshooting](troubleshooting.md) - Common issues