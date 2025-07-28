variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

provider "aws" {
  region = "us-west-2"
}

# Generate a new private key
resource "tls_private_key" "lablink_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# Register the public key with AWS
resource "aws_key_pair" "lablink_key_pair" {
  key_name   = "lablink-key-${var.resource_suffix}"
  public_key = tls_private_key.lablink_key.public_key_openssh
}

resource "aws_security_group" "allow_http" {
  name = "allow_http_${var.resource_suffix}"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "allow_http_${var.resource_suffix}"
  }
}

variable "allocator_image_tag" {
  description = "Docker image tag for the lablink allocator"
  type        = string
  default     = "linux-amd64-latest-test"
}

resource "aws_instance" "lablink_allocator_server" {
  ami             = "ami-0e096562a04af2d8b"
  instance_type   = local.allocator_instance_type
  security_groups = [aws_security_group.allow_http.name]
  key_name        = aws_key_pair.lablink_key_pair.key_name

  user_data = templatefile("${path.module}/user_data.sh", {
    ALLOCATOR_IMAGE_TAG = var.allocator_image_tag
    RESOURCE_SUFFIX     = var.resource_suffix
    ALLOCATOR_PUBLIC_IP = data.aws_eip.lablink_allocator_ip.public_ip
    ALLOCATOR_KEY_NAME  = aws_key_pair.lablink_key_pair.key_name
  })

  tags = {
    Name        = "lablink_allocator_server_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

data "aws_eip" "lablink_allocator_ip" {
  filter {
    name   = "tag:Name"
    values = ["lablink-eip-${var.resource_suffix}"]
  }
}


# Associate Elastic IP with EC2 instance
resource "aws_eip_association" "lablink_allocator_ip_assoc" {
  instance_id   = aws_instance.lablink_allocator_server.id
  allocation_id = data.aws_eip.lablink_allocator_ip.id
}

# Define the FQDN based on the resource suffix
# Use larger instance type for production
locals {
  fqdn                    = var.resource_suffix == "prod" ? "lablink.sleap.ai" : "${var.resource_suffix}.lablink.sleap.ai"
  allocator_instance_type = var.resource_suffix == "prod" ? "t3.large" : "t2.micro"
}


# Output the EC2 public IP
output "ec2_public_ip" {
  value = data.aws_eip.lablink_allocator_ip.public_ip
}

# Output the EC2 key name
output "ec2_key_name" {
  value       = aws_key_pair.lablink_key_pair.key_name
  description = "The name of the EC2 key used for the allocator"
}

# Output the private key PEM (sensitive)
output "private_key_pem" {
  value     = tls_private_key.lablink_key.private_key_pem
  sensitive = true
}

# Output the FQDN for the allocator
output "allocator_fqdn" {
  value       = local.fqdn
  description = "The subdomain associated with the allocator EIP"
}

output "allocator_instance_type" {
  value       = local.allocator_instance_type
  description = "Instance type used for the allocator server"
}


# Terraform configuration for deploying the LabLink Allocator service in AWS.
#
# This setup provisions:
# - An EC2 instance configured with Docker to run the LabLink Allocator container.
# - A pre-allocated Elastic IP (EIP), looked up by tag, to provide a stable public IP address.
# - A security group allowing inbound HTTP (port 80) and SSH (port 22) traffic.
# - An association between the EC2 instance and the fixed EIP.
#
# DNS records are managed manually in Route 53.
# - The EIP is manually mapped to either `lablink.sleap.ai` (for prod) or
#   `{resource_suffix}.lablink.sleap.ai` (for dev, test, etc.).
# Note: EIPs must be pre-allocated and tagged as "lablink-eip-prod", "lablink-eip-dev", etc.
#
# The container is pulled from GitHub Container Registry and exposed on port 5000,
# which is made externally accessible via port 80 on the EC2 instance.
#
# The configuration is environment-aware, using the `resource_suffix` variable
# to differentiate resource names and subdomains (e.g., `prod`, `dev`, `test`).
#
# Outputs include the EC2 public IP, SSH key name, and the generated private key (marked sensitive).
