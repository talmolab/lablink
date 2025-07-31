provider "aws" {
  region = "us-west-2"
}

# Security Group for the Client VM
resource "aws_security_group" "lablink_sg_" {
  name        = "lablink_client_${var.resource_suffix}"
  description = "Allow SSH and Docker ports"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # You can restrict to your IP
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Get the current AWS account ID
data "aws_caller_identity" "current" {}

# IAM Role for CloudWatch Agent
resource "aws_iam_role" "cloud_watch_agent_role" {
  name = "lablink_cloud_watch_agent_role_${var.resource_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

# Policy to allow CloudWatch agent to write logs
resource "aws_iam_policy_attachment" "cloudwatch_agent_policy" {
  name       = "lablink_cloudwatch_agent_policy_attachment_${var.resource_suffix}"
  roles      = [aws_iam_role.cloud_watch_agent_role.name]
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Instance profile for EC2 instances
resource "aws_iam_instance_profile" "lablink_instance_profile" {
  name = "lablink_client_instance_profile_${var.resource_suffix}"
  role = aws_iam_role.cloud_watch_agent_role.name
}

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
      API_ENDPOINT = "http://${var.allocator_ip}/api/vm-logs"
    }
  }
}

# Permission to invoke the Lambda function from CloudWatch
resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.log_processor.function_name
  principal     = "logs.amazonaws.com"
  source_arn    = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:${var.cloud_init_output_log_group}:*"
}

# Subscription filter to send CloudWatch logs to Lambda
resource "aws_cloudwatch_log_subscription_filter" "lambda_subscription" {
  name            = "lablink_lambda_subscription_${var.resource_suffix}"
  filter_pattern  = ""
  destination_arn = aws_lambda_function.log_processor.arn
  log_group_name  = var.cloud_init_output_log_group
  depends_on      = [aws_lambda_permission.allow_cloudwatch]
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_exec" {
  name = "lablink_lambda_exec_${var.resource_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Attach basic execution role to Lambda
resource "aws_iam_role_policy_attachment" "lambda_logs_policy" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${aws_lambda_function.log_processor.function_name}"
  retention_in_days = 14
}

# Zip the Lambda function code
# To package the Lambda function into a zip file
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/lambda_function.py"
  output_path = "${path.module}/lambda_package.zip"
}

# EC2 Instance for the LabLink Client
resource "aws_instance" "lablink_vm" {
  count                  = var.instance_count
  ami                    = var.client_ami_id
  instance_type          = var.machine_type
  vpc_security_group_ids = [aws_security_group.lablink_sg_.id]
  key_name               = aws_key_pair.lablink_key_pair.key_name
  iam_instance_profile   = aws_iam_instance_profile.lablink_instance_profile.name
  root_block_device {
    volume_size = 80
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh", {
    allocator_ip                = var.allocator_ip
    repository                  = var.repository
    resource_suffix             = var.resource_suffix
    image_name                  = var.image_name
    count_index                 = count.index + 1
    subject_software            = var.subject_software
    gpu_support                 = var.gpu_support
    cloud_init_output_log_group = var.cloud_init_output_log_group
  })

  tags = {
    Name = "lablink-vm-${var.resource_suffix}-${count.index + 1}"
  }
}

# TLS Private Key for SSH access
resource "tls_private_key" "lablink_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# AWS Key Pair for SSH access
resource "aws_key_pair" "lablink_key_pair" {
  key_name   = "lablink_key_pair_client_${var.resource_suffix}"
  public_key = tls_private_key.lablink_key.public_key_openssh
}
