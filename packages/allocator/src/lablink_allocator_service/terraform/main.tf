provider "aws" {
  region = var.region
}

resource "time_static" "start" {
  count = var.instance_count
}

# Security Group for the Client VM
resource "aws_security_group" "lablink_sg" {
  name        = "${var.resource_prefix}-sg"
  description = "Allow SSH and Docker ports"

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

  tags = merge(local.common_tags, {
    Name = "${var.resource_prefix}-sg"
  })
}

# IAM Role for CloudWatch Agent
resource "aws_iam_role" "cloud_watch_agent_role" {
  name = "${var.resource_prefix}-cloudwatch-role"

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

  tags = merge(local.common_tags, {
    Name = "${var.resource_prefix}-cloudwatch-role"
  })
}

# Policy to allow CloudWatch agent to write logs
resource "aws_iam_policy_attachment" "cloudwatch_agent_policy" {
  name       = "${var.resource_prefix}-cloudwatch-policy"
  roles      = [aws_iam_role.cloud_watch_agent_role.name]
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

# Policy to allow SSM agent for remote command execution (reboot fallback)
resource "aws_iam_policy_attachment" "ssm_managed_policy" {
  name       = "${var.resource_prefix}-ssm-policy"
  roles      = [aws_iam_role.cloud_watch_agent_role.name]
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Instance profile for EC2 instances
resource "aws_iam_instance_profile" "lablink_instance_profile" {
  name = "${var.resource_prefix}-instance-profile"
  role = aws_iam_role.cloud_watch_agent_role.name

  tags = merge(local.common_tags, {
    Name = "${var.resource_prefix}-instance-profile"
  })
}

# EC2 Instance for the LabLink Client
resource "aws_instance" "lablink_vm" {
  count                  = var.instance_count
  ami                    = var.client_ami_id
  instance_type          = var.machine_type
  vpc_security_group_ids = [aws_security_group.lablink_sg.id]
  key_name               = aws_key_pair.lablink_key_pair.key_name
  iam_instance_profile   = aws_iam_instance_profile.lablink_instance_profile.name
  root_block_device {
    volume_size = 80
    volume_type = "gp3"
  }

  user_data = base64encode(join("\n", [
    "Content-Type: multipart/mixed; boundary=\"BOUNDARY\"",
    "MIME-Version: 1.0",
    "",
    "--BOUNDARY",
    "Content-Type: text/cloud-config; charset=\"us-ascii\"",
    "MIME-Version: 1.0",
    "",
    "# Run user_data on every boot so stop/start reboots re-execute it",
    "#cloud-config",
    "cloud_final_modules:",
    "  - [scripts-user, always]",
    "",
    "--BOUNDARY",
    "Content-Type: text/x-shellscript; charset=\"us-ascii\"",
    "MIME-Version: 1.0",
    "",
    templatefile("${path.module}/user_data.sh", {
      allocator_ip                = var.allocator_ip
      allocator_url               = var.allocator_url
      repository                  = var.repository
      resource_prefix             = var.resource_prefix
      image_name                  = var.image_name
      count_index                 = count.index + 1
      subject_software            = var.subject_software
      gpu_support                 = var.gpu_support
      cloud_init_output_log_group = var.cloud_init_output_log_group
      region                      = var.region
      startup_content_b64         = local.startup_content_b64
      startup_on_error            = var.startup_on_error
    }),
    "--BOUNDARY--",
  ]))

  tags = merge(local.common_tags, {
    Name = "${var.resource_prefix}-vm-${count.index + 1}"
  })
}

# TLS Private Key for SSH access
resource "tls_private_key" "lablink_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# AWS Key Pair for SSH access
resource "aws_key_pair" "lablink_key_pair" {
  key_name   = "${var.resource_prefix}-keypair"
  public_key = tls_private_key.lablink_key.public_key_openssh
  tags = merge(local.common_tags, {
    Name = "${var.resource_prefix}-keypair"
  })
}

resource "time_static" "end" {
  count      = var.instance_count
  depends_on = [aws_instance.lablink_vm]
}

locals {
  common_tags = {
    ResourcePrefix = var.resource_prefix
    ManagedBy      = "terraform"
  }

  per_instance_seconds = [
    for i in range(var.instance_count) :
    tonumber(time_static.end[i].unix) - tonumber(time_static.start[i].unix)
  ]

  per_instance_hms = [
    for s in local.per_instance_seconds :
    format(
      "%02dh:%02dm:%02ds",
      floor(s / 3600),
      floor((s % 3600) / 60),
      s % 60
    )
  ]

  per_instance_end_time = [
    for t in time_static.end :
    t.rfc3339
  ]

  per_instance_start_time = [
    for t in time_static.start :
    t.rfc3339
  ]

  avg_seconds = length(local.per_instance_seconds) > 0 ? floor(sum(local.per_instance_seconds) / length(local.per_instance_seconds)) : 0

  max_seconds = length(local.per_instance_seconds) > 0 ? max(local.per_instance_seconds...) : 0

  min_seconds = length(local.per_instance_seconds) > 0 ? min(local.per_instance_seconds...) : 0

  # Base64 encode startup script to avoid Terraform templatefile() interpolation issues
  # This preserves $, %, and other special characters in user scripts
  startup_content_raw = fileexists(var.custom_startup_script_path) ? file(var.custom_startup_script_path) : ""
  startup_content_b64 = local.startup_content_raw != "" ? base64encode(local.startup_content_raw) : ""
}
