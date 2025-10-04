variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

variable "config_path" {
  description = "Path to the allocator config file"
  type        = string
  default     = "config/config.yaml"
}

# Read configuration from YAML file
locals {
  config_file = yamldecode(file("${path.module}/${var.config_path}"))

  # DNS configuration from config.yaml
  dns_enabled          = try(local.config_file.dns.enabled, false)
  dns_domain           = try(local.config_file.dns.domain, "")
  dns_app_name         = try(local.config_file.dns.app_name, "lablink")
  dns_pattern          = try(local.config_file.dns.pattern, "auto")
  dns_custom_subdomain = try(local.config_file.dns.custom_subdomain, "")
  dns_create_zone      = try(local.config_file.dns.create_zone, false)

  # EIP configuration from config.yaml
  eip_strategy = try(local.config_file.eip.strategy, "dynamic")
  eip_tag_name = try(local.config_file.eip.tag_name, "lablink-eip")

  # SSL configuration from config.yaml
  ssl_provider = try(local.config_file.ssl.provider, "letsencrypt")
  ssl_email    = try(local.config_file.ssl.email, "")

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

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.resource_suffix}/*"]
    }
  }

  # Read/Write/Delete objects under the prefix
  statement {
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "arn:aws:s3:::${local.bucket_name}/${var.resource_suffix}/*"
    ]
  }
}


# Zip the Lambda function code
# To package the Lambda function into a zip file
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda_function.py"
  output_path = "${path.module}/lambda_package.zip"
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
    Name = "allow_http_https_${var.resource_suffix}"
  }
}

variable "allocator_image_tag" {
  description = "Docker image tag for the lablink allocator"
  type        = string
  default     = "linux-amd64-latest-test"
}

resource "aws_instance" "lablink_allocator_server" {
  ami                  = "ami-0e096562a04af2d8b"
  instance_type        = local.allocator_instance_type
  security_groups      = [aws_security_group.allow_http.name]
  key_name             = aws_key_pair.lablink_key_pair.key_name
  iam_instance_profile = aws_iam_instance_profile.allocator_instance_profile.name

  user_data = templatefile("${path.module}/user_data.sh", {
    ALLOCATOR_IMAGE_TAG  = var.allocator_image_tag
    RESOURCE_SUFFIX      = var.resource_suffix
    ALLOCATOR_PUBLIC_IP  = local.eip_public_ip
    ALLOCATOR_KEY_NAME   = aws_key_pair.lablink_key_pair.key_name
    CLOUD_INIT_LOG_GROUP = aws_cloudwatch_log_group.client_vm_logs.name
    CONFIG_CONTENT       = file("${path.module}/${var.config_path}")
    DOMAIN_NAME          = local.fqdn
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
    Name        = "lablink-eip-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Determine which EIP to use based on strategy
locals {
  eip_allocation_id = local.eip_strategy == "persistent" ? data.aws_eip.existing[0].id : aws_eip.new[0].id
  eip_public_ip     = local.eip_strategy == "persistent" ? data.aws_eip.existing[0].public_ip : aws_eip.new[0].public_ip
}

# DNS Zone Lookup (if using existing zone)
data "aws_route53_zone" "existing" {
  count        = local.dns_enabled && !local.dns_create_zone ? 1 : 0
  name         = "${local.dns_domain}."
  private_zone = false
}

# DNS Zone Creation (if creating new zone)
resource "aws_route53_zone" "new" {
  count = local.dns_enabled && local.dns_create_zone ? 1 : 0
  name  = local.dns_domain

  tags = {
    Name        = "lablink-zone-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Generate FQDN based on environment and DNS settings from config.yaml
locals {
  # Subdomain pattern: auto generates prod.lablink or test.lablink, custom uses custom_subdomain
  subdomain = local.dns_pattern == "custom" ? local.dns_custom_subdomain : (
    var.resource_suffix == "prod" ? local.dns_app_name : "${var.resource_suffix}.${local.dns_app_name}"
  )

  # Full domain name
  fqdn = local.dns_enabled ? "${local.subdomain}.${local.dns_domain}" : "N/A"

  # Zone ID from either lookup or creation
  zone_id = local.dns_enabled ? (
    local.dns_create_zone ? aws_route53_zone.new[0].zone_id : data.aws_route53_zone.existing[0].zone_id
  ) : ""

  allocator_instance_type = "t3.large"
}

# DNS A Record for the allocator
resource "aws_route53_record" "lablink_a_record" {
  count   = local.dns_enabled ? 1 : 0
  zone_id = local.zone_id
  name    = local.fqdn
  type    = "A"
  ttl     = 300
  records = [local.eip_public_ip]
}

# Associate Elastic IP with EC2 instance
resource "aws_eip_association" "lablink_allocator_ip_assoc" {
  instance_id   = aws_instance.lablink_allocator_server.id
  allocation_id = local.eip_allocation_id
}

# CloudWatch Log Groups for Client VMs
resource "aws_cloudwatch_log_group" "client_vm_logs" {
  name              = "lablink-cloud-init-${var.resource_suffix}"
  retention_in_days = 30
}

# CloudWatch Log Group for Lambda logs
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/lablink_log_processor_${var.resource_suffix}"
  retention_in_days = 14
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_exec" {
  name = "lablink_lambda_exec_${var.resource_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      },
    ]
  })
}


resource "aws_iam_policy" "s3_backend_policy" {
  name   = "lablink_s3_backend_${var.resource_suffix}"
  policy = data.aws_iam_policy_document.s3_backend_doc.json
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
}

resource "aws_iam_role_policy_attachment" "attach_s3_backend" {
  role       = aws_iam_role.instance_role.name
  policy_arn = aws_iam_policy.s3_backend_policy.arn
}

resource "aws_iam_instance_profile" "allocator_instance_profile" {
  name = "lablink_instance_profile_${var.resource_suffix}"
  role = aws_iam_role.instance_role.name
}

# Subscription filter to send CloudWatch logs to Lambda
resource "aws_cloudwatch_log_subscription_filter" "lambda_subscription" {
  name            = "lablink_lambda_subscription_${var.resource_suffix}"
  filter_pattern  = ""
  destination_arn = aws_lambda_function.log_processor.arn
  log_group_name  = aws_cloudwatch_log_group.client_vm_logs.name
  depends_on      = [aws_lambda_permission.allow_cloudwatch]
}

# Lambda function for processing logs
# Lambda Function to process logs
resource "aws_lambda_function" "log_processor" {
  function_name    = "lablink_log_processor_${var.resource_suffix}"
  role             = aws_iam_role.lambda_exec.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.11"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 10
  depends_on       = [aws_cloudwatch_log_group.lambda_logs]
  environment {
    variables = {
      API_ENDPOINT = "${local.fqdn}/api/vm-logs"
    }
  }
}

# Permission to invoke the Lambda function from CloudWatch
resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.log_processor.function_name
  principal     = "logs.amazonaws.com"
  source_arn    = "arn:aws:logs:us-west-2:${data.aws_caller_identity.current.account_id}:log-group:${aws_cloudwatch_log_group.client_vm_logs.name}:*"
}

# Attach basic execution role to Lambda
resource "aws_iam_role_policy_attachment" "lambda_logs_policy" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
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
