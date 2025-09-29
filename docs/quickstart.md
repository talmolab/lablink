# Quickstart

Get LabLink up and running quickly with this streamlined guide.

## Prerequisites Checklist

Before starting, ensure you have:

- [x] AWS CLI configured (see [Prerequisites](prerequisites.md#2-aws-cli))
- [x] Terraform installed (see [Prerequisites](prerequisites.md#3-terraform))
- [x] Docker running (see [Prerequisites](prerequisites.md#4-docker))
- [x] AWS account with necessary permissions

## Quick Setup (5 minutes)

### 1. Clone the Repository

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink
```

### 2. Test Allocator Locally

Pull and run the allocator image:

```bash
docker pull ghcr.io/talmolab/lablink-allocator-image:latest
docker run -d -p 5000:5000 ghcr.io/talmolab/lablink-allocator-image:latest
```

Access the web interface at [http://localhost:5000](http://localhost:5000)

!!! tip "Default Credentials"
    - Username: `admin`
    - Password: `IwanttoSLEAP`

    Change these in production! See [Security](security.md#change-default-passwords).

### 3. Deploy to AWS (Dev Environment)

Navigate to the allocator directory:

```bash
cd lablink-allocator
```

Initialize Terraform:

```bash
terraform init
```

Plan the deployment:

```bash
terraform plan -var="resource_suffix=dev" -var="allocator_image_tag=linux-amd64-latest-test"
```

Apply the deployment:

```bash
terraform apply -var="resource_suffix=dev" -var="allocator_image_tag=linux-amd64-latest-test"
```

Terraform will:

- Create a security group (ports 22 and 80)
- Generate an SSH key pair
- Launch an EC2 instance with the allocator
- Output the public IP and FQDN

### 4. Access Your Deployed Allocator

Get the outputs:

```bash
terraform output allocator_fqdn
terraform output ec2_public_ip
```

Save the SSH key:

```bash
terraform output -raw private_key_pem > ~/lablink-dev-key.pem
chmod 600 ~/lablink-dev-key.pem
```

SSH into the instance:

```bash
ssh -i ~/lablink-dev-key.pem ubuntu@$(terraform output -raw ec2_public_ip)
```

Access the web interface:

```
http://<ec2_public_ip>:80
```

### 5. Request a Client VM

From the allocator web interface:

1. Navigate to **Admin** → **Create Instances**
2. Enter number of VMs to create
3. Submit

Or use the API:

```bash
curl -X POST http://<allocator_ip>:80/request_vm \
  -d "email=your@email.com" \
  -d "crd_command=your_command"
```

## What's Next?

Now that you have LabLink running:

- **[Configuration](configuration.md)**: Customize for your research software
- **[Adapting LabLink](adapting.md)**: Use your own Docker images and repositories
- **[Deployment](deployment.md)**: Set up production deployment with GitHub Actions
- **[AWS Setup](aws-setup.md)**: Configure production-ready AWS infrastructure

## Cleanup

When you're done testing:

```bash
cd lablink-allocator
terraform destroy -var="resource_suffix=dev"
```

!!! warning "Cost Awareness"
    EC2 instances incur costs while running. Always destroy test resources when done. See [Cost Estimation](cost-estimation.md) for details.

## Troubleshooting Quick Fixes

### Docker Permission Error
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### PostgreSQL Not Accessible
The allocator PostgreSQL server may need a restart after first boot:

```bash
ssh -i ~/lablink-dev-key.pem ubuntu@<ec2_public_ip>
sudo docker ps
sudo docker exec -it <container_name> bash
/etc/init.d/postgresql restart
```

For more issues, see [Troubleshooting](troubleshooting.md).