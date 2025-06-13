provider "aws" {
  region     = "us-west-2"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
  token      = var.aws_session_token
}

# -----------------------------
# VARIABLES
# -----------------------------

variable "aws_access_key" {
  description = "AWS Access Key"
  type        = string
  sensitive   = true
}

variable "aws_secret_key" {
  description = "AWS Secret Key"
  type        = string
  sensitive   = true
}

variable "aws_session_token" {
  description = "AWS Session Token"
  type        = string
  sensitive   = true
}

variable "allocator_ip" {
  description = "IP address of the allocator server"
  type        = string
  sensitive   = true
}

variable "image_name" {
  description = "Docker image to run in the client VM"
  type        = string
}

variable "repository" {
  description = "Optional GitHub repository to clone inside the container"
  type        = string
}

variable "client_ami_id" {
  type        = string
  description = "AMI ID for the client VM"
}


output "lablink_private_key_pem" {
  description = "Private key used to access EC2 instances"
  value       = tls_private_key.lablink_key.private_key_pem
  sensitive   = true
}

variable "key_name" {
  description = "Name of pre-existing EC2 key pair to enable SSH access"
  type        = string
}

variable "machine_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t2.medium"
}

variable "instance_count" {
  description = "Number of client VMs to launch"
  type        = number
  default     = 1
}

variable "resource_suffix" {
  description = "Suffix to append to resource names"
  type        = string
  default     = "client"
}

# -----------------------------
# SECURITY GROUP
# -----------------------------

resource "aws_security_group" "lablink_client_sg" {
  name        = "lablink_sg_${var.resource_suffix}"
  description = "Allow SSH and HTTP"

  ingress {
    description = "Allow SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Allow HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# -----------------------------
# EC2 INSTANCES
# -----------------------------

resource "aws_instance" "lablink_vm" {
  count                  = var.instance_count
  ami                    = var.client_ami_id
  instance_type          = var.machine_type
  key_name               = var.key_name
  vpc_security_group_ids = [aws_security_group.lablink_client_sg.id]

  root_block_device {
    volume_size = 40
    volume_type = "gp3"
  }

  user_data = <<-EOF
              #!/bin/bash

              docker pull ${var.image_name} || (echo "Docker pull failed" && exit 1)

              export TUTORIAL_REPO_TO_CLONE="${var.repository}"

              if [ -z "$TUTORIAL_REPO_TO_CLONE" ] || [ "$TUTORIAL_REPO_TO_CLONE" = "None" ]; then
                echo "Starting container without repo..."
                docker run -dit --gpus all -e ALLOCATOR_HOST=${var.allocator_ip} ${var.image_name}
              else
                echo "Starting container with repo: $TUTORIAL_REPO_TO_CLONE"
                docker run -dit --gpus all -e ALLOCATOR_HOST=${var.allocator_ip} -e TUTORIAL_REPO_TO_CLONE=${var.repository} ${var.image_name}
              fi
              EOF

  tags = {
    Name = "lablink-vm-${count.index + 1}"
  }
}

# -----------------------------
# OUTPUTS
# -----------------------------

output "vm_instance_ids" {
  description = "EC2 instance IDs"
  value       = aws_instance.lablink_vm[*].id
}

output "vm_public_ips" {
  description = "Public IPs of EC2 instances"
  value       = aws_instance.lablink_vm[*].public_ip
}

output "ssh_commands" {
  description = "SSH commands to access each instance"
  value = [
    for ip in aws_instance.lablink_vm[*].public_ip :
    "ssh -i ~/.ssh/${var.key_name}.pem ubuntu@${ip}"
  ]
}
