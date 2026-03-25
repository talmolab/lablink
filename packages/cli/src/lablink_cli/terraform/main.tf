variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

# Read configuration from YAML file
locals {
  config_file = yamldecode(file("${path.module}/config/config.yaml"))

  # DNS configuration from config.yaml
  dns_enabled           = try(local.config_file.dns.enabled, false)
  dns_terraform_managed = try(local.config_file.dns.terraform_managed, true) # default true for backwards compatibility
  dns_domain            = try(local.config_file.dns.domain, "")
  dns_zone_id           = try(local.config_file.dns.zone_id, "")

  # EIP configuration from config.yaml
  eip_strategy = try(local.config_file.eip.strategy, "dynamic")
  eip_tag_name = try(local.config_file.eip.tag_name, "lablink-eip")

  # SSL configuration from config.yaml
  ssl_provider        = try(local.config_file.ssl.provider, "none")
  ssl_email           = try(local.config_file.ssl.email, "")
  ssl_certificate_arn = try(local.config_file.ssl.certificate_arn, "")

  # Allocator configuration from config.yaml
  allocator_image_tag = try(local.config_file.allocator.image_tag, "linux-amd64-latest-test")

  # Custom Startup Script
  startup_enabled  = try(local.config_file.startup_script.enabled, false)
  startup_path     = try(local.config_file.startup_script.path, "config/custom-startup.sh")
  startup_on_error = try(local.config_file.startup_script.on_error, "continue")

  startup_script_content = (
    local.startup_enabled && local.startup_path != "" ? (
      fileexists("${path.module}/${local.startup_path}") ?
      file("${path.module}/${local.startup_path}") : ""
    ) : ""
  )

  # Base64 encode startup script to preserve $ and other special characters
  # This prevents bash from expanding variables when user_data.sh runs
  startup_script_b64 = local.startup_script_content != "" ? base64encode(local.startup_script_content) : ""

  # Bucket name from config.yaml for S3 backend
  bucket_name = try(local.config_file.bucket_name, "tf-state-lablink-allocator-bucket")
}

provider "aws" {
  region = "us-west-2"
}

# Get the current AWS account ID
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "s3_backend_doc" {
  statement {
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${local.bucket_name}"]
  }

  # Read/Write/Delete objects under the prefix
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "arn:aws:s3:::${local.bucket_name}/${var.resource_suffix}/*"
    ]
  }

  # DynamoDB permissions for Terraform state locking
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem"
    ]
    resources = [
      "arn:aws:dynamodb:us-west-2:${data.aws_caller_identity.current.account_id}:table/lock-table"
    ]
  }
}

data "aws_iam_policy_document" "ec2_vm_management_doc" {
  # EC2 permissions for VM lifecycle management
  statement {
    effect = "Allow"
    actions = [
      "ec2:RunInstances",
      "ec2:TerminateInstances",
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceStatus",
      "ec2:CreateTags",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeKeyPairs",
      "ec2:CreateSecurityGroup",
      "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:CreateKeyPair",
      "ec2:DeleteKeyPair",
      "ec2:ImportKeyPair",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeImages",
      "ec2:DescribeTags",
      "ec2:DescribeVolumes",
      "ec2:DescribeInstanceAttribute",
    ]
    resources = ["*"]
  }

  # IAM permissions for creating VM roles
  statement {
    effect = "Allow"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:TagInstanceProfile",
      "iam:UntagInstanceProfile",
      "iam:AddRoleToInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:GetInstanceProfile"
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*-lablink-client-*-vm-role",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*-lablink-client-*-instance-profile"
    ]
  }

  # Allow passing the VM role to created EC2 instances
  statement {
    effect = "Allow"
    actions = [
      "iam:PassRole"
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*-lablink-client-*-vm-role"
    ]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ec2.amazonaws.com"]
    }
  }
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

  tags = {
    Name        = "lablink-key-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

resource "aws_security_group" "allow_http" {
  name = "allow_http_https_${var.resource_suffix}"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow direct access to allocator service"
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
    Name        = "allow_http_https_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

resource "aws_instance" "lablink_allocator_server" {
  ami                  = "ami-0bd08c9d4aa9f0bc6" # Ubuntu 24.04 with Docker pre-installed
  instance_type        = local.allocator_instance_type
  security_groups      = [aws_security_group.allow_http.name]
  key_name             = aws_key_pair.lablink_key_pair.key_name
  iam_instance_profile = aws_iam_instance_profile.allocator_instance_profile.name

  user_data = templatefile("${path.module}/user_data.sh", {
    ALLOCATOR_IMAGE_TAG       = local.allocator_image_tag
    RESOURCE_SUFFIX           = var.resource_suffix
    ALLOCATOR_PUBLIC_IP       = local.eip_public_ip
    ALLOCATOR_KEY_NAME        = aws_key_pair.lablink_key_pair.key_name
    LOG_GROUP                 = "lablink-cloud-init-${var.resource_suffix}"
    CONFIG_CONTENT            = file("${path.module}/config/config.yaml")
    CLIENT_STARTUP_SCRIPT_B64 = local.startup_script_b64
    STARTUP_ENABLED           = local.startup_enabled
    ALLOCATOR_FQDN            = local.allocator_fqdn
    INSTALL_CADDY             = local.install_caddy
    SSL_PROVIDER              = local.ssl_provider
    SSL_EMAIL                 = local.ssl_email
    DOMAIN_NAME               = local.install_caddy ? local.dns_domain : ""
  })

  tags = {
    Name        = "lablink_allocator_server_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# EIP Lookup (for persistent strategy - reuse existing tagged EIP)
data "aws_eip" "existing" {
  count = local.eip_strategy == "persistent" ? 1 : 0

  tags = {
    Name        = "${local.eip_tag_name}-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# EIP Creation (for dynamic strategy - create new EIP each deployment)
resource "aws_eip" "new" {
  count  = local.eip_strategy == "dynamic" ? 1 : 0
  domain = "vpc"

  tags = {
    Name        = "${local.eip_tag_name}-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Determine which EIP to use based on strategy
locals {
  eip_allocation_id = local.eip_strategy == "persistent" ? data.aws_eip.existing[0].id : aws_eip.new[0].id
  eip_public_ip     = local.eip_strategy == "persistent" ? data.aws_eip.existing[0].public_ip : aws_eip.new[0].public_ip
}

# Extract base zone name from full domain for zone lookup
# For "test.lablink.sleap.ai" → find zone for "lablink.sleap.ai." or "sleap.ai."
locals {
  # Split domain by dots and progressively check parent zones
  domain_parts = split(".", local.dns_domain)
  # For sub-subdomains, try parent domains (e.g., test.lablink.sleap.ai → lablink.sleap.ai)
  # IMPORTANT: This only removes the first subdomain part. If the parent zone doesn't exist
  # (e.g., you specify test.lablink.sleap.ai but only sleap.ai zone exists), lookup will fail.
  # In that case, either create the intermediate zone or provide zone_id explicitly in config.
  dns_zone_name = local.dns_enabled && local.dns_domain != "" && length(local.domain_parts) > 2 ? join(".", slice(local.domain_parts, 1, length(local.domain_parts))) : local.dns_domain
}

# DNS Zone Lookup (if using existing zone)
# AWS Route53 zone lookup finds the hosted zone that contains dns.domain
# For dns.domain="test.lablink.sleap.ai", it will look for zone "lablink.sleap.ai." or "sleap.ai."
# Skip lookup if zone_id is already provided in config (avoids lookup errors)
# NOTE: AWS Route53 data source automatically handles trailing dots - both "example.com"
# and "example.com." will match the zone. No need to append trailing dot explicitly.
data "aws_route53_zone" "existing" {
  count        = local.dns_enabled && local.dns_zone_id == "" ? 1 : 0
  name         = local.dns_zone_name
  private_zone = false

  tags = {
    Name        = "lablink-zone-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Compute FQDN, allocator URL, and other derived values
locals {
  # FQDN is the dns.domain directly (no pattern logic)
  fqdn = local.dns_enabled ? local.dns_domain : local.eip_public_ip

  # Zone ID from either config or lookup (priority: config > lookup)
  # Use a placeholder value when DNS is disabled to avoid Terraform validation errors
  zone_id = local.dns_enabled ? (
    local.dns_zone_id != "" ? local.dns_zone_id : data.aws_route53_zone.existing[0].zone_id
  ) : "Z0000000000000000000"

  # Compute full allocator URL with protocol
  # If DNS + SSL: https://{domain}
  # If DNS without SSL: http://{domain}
  # If no DNS: http://{ip}
  allocator_fqdn = local.dns_enabled && contains(["letsencrypt", "cloudflare", "acm"], local.ssl_provider) ? "https://${local.dns_domain}" : (
    local.dns_enabled ? "http://${local.dns_domain}" : "http://${local.eip_public_ip}"
  )

  # Conditional Caddy installation (only for letsencrypt and cloudflare)
  install_caddy = contains(["letsencrypt", "cloudflare"], local.ssl_provider)

  # Conditional ALB creation (only for ACM)
  create_alb = local.ssl_provider == "acm"

  allocator_instance_type = "t3.large"
}

# DNS A Record for the allocator
# Only created when terraform_managed is true
# If terraform_managed is false, you must manually create the A record in Route53
# Points to EIP for direct EC2 access, or ALB for ACM SSL termination
resource "aws_route53_record" "lablink_a_record" {
  count   = local.dns_enabled && local.dns_terraform_managed && !local.create_alb ? 1 : 0
  zone_id = local.zone_id
  name    = local.dns_domain
  type    = "A"
  ttl     = 300
  records = [local.eip_public_ip]

  lifecycle {
    # Prevent accidental deletion in production
    prevent_destroy = false # Set to true for production environments
  }
}

# Associate Elastic IP with EC2 instance
resource "aws_eip_association" "lablink_allocator_ip_assoc" {
  instance_id   = aws_instance.lablink_allocator_server.id
  allocation_id = local.eip_allocation_id
}

resource "aws_iam_policy" "s3_backend_policy" {
  name   = "lablink_s3_backend_${var.resource_suffix}"
  policy = data.aws_iam_policy_document.s3_backend_doc.json

  tags = {
    Name        = "lablink_s3_backend_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

resource "aws_iam_policy" "ec2_vm_management_policy" {
  name   = "lablink_ec2_vm_management_${var.resource_suffix}"
  policy = data.aws_iam_policy_document.ec2_vm_management_doc.json

  tags = {
    Name        = "lablink_ec2_vm_management_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

resource "aws_iam_role" "instance_role" {
  name = "lablink_instance_role_${var.resource_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "ec2.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name        = "lablink_instance_role_${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

resource "aws_iam_role_policy_attachment" "attach_ec2_management" {
  role       = aws_iam_role.instance_role.name
  policy_arn = aws_iam_policy.ec2_vm_management_policy.arn
}

resource "aws_iam_role_policy_attachment" "attach_s3_backend" {
  role       = aws_iam_role.instance_role.name
  policy_arn = aws_iam_policy.s3_backend_policy.arn
}

resource "aws_iam_instance_profile" "allocator_instance_profile" {
  name = "lablink_instance_profile_${var.resource_suffix}"
  role = aws_iam_role.instance_role.name

  tags = {
    Environment = var.resource_suffix
  }
}

# Output the EC2 public IP
output "ec2_public_ip" {
  value = local.eip_public_ip
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
  value       = local.allocator_fqdn
  description = "The full URL (with protocol) to access the allocator service"
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
# - The EIP is manually mapped to either `lablink.example.com` (for prod) or
#   `{resource_suffix}.lablink.example.com` (for dev, test, etc.).
# Note: EIPs must be pre-allocated and tagged as "lablink-eip-prod", "lablink-eip-dev", etc.
#
# The container is pulled from GitHub Container Registry and exposed on port 5000,
# which is made externally accessible via port 80 on the EC2 instance.
#
# The configuration is environment-aware, using the `resource_suffix` variable
# to differentiate resource names and subdomains (e.g., `prod`, `dev`, `test`).
#
# Outputs include the EC2 public IP, SSH key name, and the generated private key (marked sensitive).
