provider "aws" {
  region     = "us-west-2"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
  token      = var.aws_session_token
}

variable "instance_count" {
  type    = number
  default = 1
}

variable "aws_access_key" {
  type        = string
  description = "AWS Access Key"
  sensitive   = true
}

variable "aws_secret_key" {
  type        = string
  description = "AWS Secret Key"
  sensitive   = true
}

variable "aws_session_token" {
  type        = string
  description = "AWS Session Token"
  sensitive   = true
}

variable "allocator_ip" {
  type        = string
  description = "IP address of the allocator server"
  sensitive   = true
}

variable "machine_type" {
  type        = string
  description = "Type of the machine to be created"
  default     = "t2.medium"
}

variable "image_name" {
  type        = string
  description = "VM Image Name to be used as client base image"
}

variable "repository" {
  type        = string
  description = "GitHub repository URL for the Data Repository"
}

variable "client_ami_id" {
  type        = string
  description = "AMI ID for the client VM"
}

output "vm_public_ips" {
  value       = [for instance in aws_instance.lablink_vm : instance.public_ip]
  description = "Public IPs of the created VM instances"
}

output "lablink_private_key_pem" {
  description = "Private key used to access EC2 instances"
  value       = tls_private_key.lablink_key.private_key_pem
  sensitive   = true
}

variable "key_name" {
  type        = string
  description = "EC2 key name to use for instances"
}

variable "resource_suffix" {
  type        = string
  default     = "client"
  description = "Suffix to ensure uniqueness"
}

resource "aws_security_group" "lablink_sg_" {
  name        = "lablink_sg_${var.resource_suffix}"
  description = "Allow SSH and Docker ports"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # You can restrict to your IP
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "tls_private_key" "lablink_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "lablink_key_pair" {
  key_name   = "lablink_key_pair_client"
  public_key = tls_private_key.lablink_key.public_key_openssh
}

resource "aws_instance" "lablink_vm" {
  count                  = var.instance_count
  ami                    = var.client_ami_id
  instance_type          = var.machine_type
  vpc_security_group_ids = [aws_security_group.lablink_sg_.id]
  key_name               = var.key_name

  root_block_device {
    volume_size = 40
    volume_type = "gp3"
  }

  user_data = <<-EOF
              #!/bin/bash

              docker pull ${var.image_name}

              export TUTORIAL_REPO_TO_CLONE=${var.repository}

              if [ -z "$TUTORIAL_REPO_TO_CLONE" ] ||  [ "$TUTORIAL_REPO_TO_CLONE" = "None" ]; then
                  echo "No repository specified, starting container without cloning."
                  docker run -dit --gpus all -e ALLOCATOR_HOST=${var.allocator_ip} ${var.image_name}
              else
                  echo "Cloning repository: $TUTORIAL_REPO_TO_CLONE"
                  docker run -dit --gpus all -e ALLOCATOR_HOST=${var.allocator_ip} -e TUTORIAL_REPO_TO_CLONE=${var.repository} ${var.image_name}
              fi

              if [ $? -ne 0 ]; then
                  echo "Docker run failed!" >&2
                  exit 1
              else
                  echo "Docker container started."
              fi
              EOF

  tags = {
    Name = "lablink-vm-${count.index + 1}"
  }
}
