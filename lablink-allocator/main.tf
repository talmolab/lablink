variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

provider "aws" {
  region = "us-west-2"
}

# Get the current AWS account ID
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "s3_backend_doc" {
  # List the bucket (optionally scope with prefix condition)
  statement {
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::tf-state-lablink-allocator-bucket"]

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
      "arn:aws:s3:::tf-state-lablink-allocator-bucket/${var.resource_suffix}/*"
    ]
  }
}


# Zip the Lambda function code
# To package the Lambda function into a zip file
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lablink-allocator-service/lambda_function.py"
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
  ami                  = "ami-0e096562a04af2d8b"
  instance_type        = local.allocator_instance_type
  security_groups      = [aws_security_group.allow_http.name]
  key_name             = aws_key_pair.lablink_key_pair.key_name
  iam_instance_profile = aws_iam_instance_profile.allocator_instance_profile.name

  user_data = templatefile("${path.module}/user_data.sh", {
    ALLOCATOR_IMAGE_TAG  = var.allocator_image_tag
    RESOURCE_SUFFIX      = var.resource_suffix
    ALLOCATOR_PUBLIC_IP  = data.aws_eip.lablink_allocator_ip.public_ip
    ALLOCATOR_KEY_NAME   = aws_key_pair.lablink_key_pair.key_name
    CLOUD_INIT_LOG_GROUP = aws_cloudwatch_log_group.client_vm_logs.name
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
  allocator_instance_type = "t3.large"
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
