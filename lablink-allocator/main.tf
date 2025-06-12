variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

provider "aws" {
  region = "us-west-2"
}

data "aws_route53_zone" "sleap_ai" {
  name         = "sleap.ai"
  private_zone = false
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

resource "aws_instance" "lablink_allocator_server" {
  ami             = "ami-0e096562a04af2d8b"
  instance_type   = "t2.micro"
  security_groups = [aws_security_group.allow_http.name]
  key_name        = aws_key_pair.lablink_key_pair.key_name

  user_data = <<-EOF
              #!/bin/bash
              docker pull ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
              docker run -d -p 80:5000 \
                -e ALLOCATOR_PUBLIC_IP=${aws_eip.lablink_allocator_ip.public_ip} \
                -e ALLOCATOR_KEY_NAME=${aws_key_pair.lablink_key_pair.key_name} \
                ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
              EOF

  tags = {
    Name        = "lablink_allocator_server_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

resource "aws_eip" "lablink_allocator_ip" {
  tags = {
    Name = "lablink_allocator_ip_${var.resource_suffix}"
  }
}

# Determine the correct subdomain name
locals {
  fqdn = var.resource_suffix == "prod" ? "lablink-assign.sleap.ai" : "lablink-assign-${var.resource_suffix}.sleap.ai"
}

# Associate Elastic IP with EC2 instance
resource "aws_eip_association" "lablink_allocator_ip_assoc" {
  instance_id   = aws_instance.lablink_allocator_server.id
  allocation_id = aws_eip.lablink_allocator_ip.id
}

# Create a single DNS record for the appropriate environment
resource "aws_route53_record" "lablink_allocator_dns" {
  zone_id = data.aws_route53_zone.sleap_ai.zone_id
  name    = local.fqdn
  type    = "A"
  ttl     = 300
  records = [aws_eip.lablink_allocator_ip.public_ip]
}

# Output the EC2 public IP
output "ec2_public_ip" {
  value = aws_eip.lablink_allocator_ip.public_ip
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

# Output the Route 53 domain name used
output "allocator_fqdn" {
  value       = aws_route53_record.lablink_allocator_dns.fqdn
  description = "The Route 53 record for the LabLink Allocator service"
}

output "allocator_dns_metadata" {
  value = {
    fqdn        = aws_route53_record.lablink_allocator_dns.fqdn
    environment = var.resource_suffix
    project     = "lablink"
    purpose     = "allocator"
    managed_by  = "terraform"
  }
}

# Terraform configuration for deploying the LabLink Allocator service in AWS.
#
# This setup provisions:
# - An EC2 instance configured with Docker to run the LabLink Allocator container.
# - An Elastic IP (EIP) to provide a stable public IP address.
# - A security group allowing HTTP (port 80) and SSH (port 22) access.
# - A Route 53 DNS record pointing to the EIP for easy access via a subdomain.
#
# The container is pulled from GitHub Container Registry and exposed on port 5000.
# It is accessible externally via the EC2 instance's public IP.
#
# The configuration is environment-aware, using the `resource_suffix` variable
# to differentiate resource names and DNS subdomains (e.g., `prod`, `dev`, `test`).
#
# If `resource_suffix` is "prod", the domain `lablink-assign.sleap.ai` is created.
# For other environments, the domain `lablink-assign-{resource_suffix}.sleap.ai` is used.
#
# The `hosted_zone_id` variable specifies the Route 53 hosted zone for the `sleap.ai` domain.
#
# Outputs include the EC2 public IP, SSH key name, private key (sensitive),
# and the allocator's DNS record for convenience.
