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

output "vm_public_ips" {
  value       = [for instance in aws_instance.lablink_vm : instance.public_ip]
  description = "Public IPs of the created VM instances"
}

output "lablink_private_key_pem" {
  description = "Private key used to access EC2 instances"
  value       = tls_private_key.lablink_key.private_key_pem
  sensitive   = true
}

resource "aws_security_group" "lablink_sg_" {
  name        = "lablink_sg_"
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
  ami                    = "ami-00c257e12d6828491" # Ubuntu 20.04 for us-west-2
  instance_type          = var.machine_type
  vpc_security_group_ids = [aws_security_group.lablink_sg_.id]
  key_name               = aws_key_pair.lablink_key_pair.key_name

  root_block_device {
    volume_size = 30
    volume_type = "gp2"
  }

  user_data = <<-EOF
              #!/bin/bash
              apt update -y
              apt upgrade -y

              apt install -y build-essential dkms curl

              apt install -y nvidia-driver-515

              apt install -y docker.io
              systemctl start docker
              systemctl enable docker

              curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
              && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list \
              && sudo apt-get update -y

              sudo apt-get install -y nvidia-container-toolkit

              sudo nvidia-ctk runtime configure --runtime=docker

              systemctl restart docker

              nvidia-smi || echo "nvidia-smi failed, GPU may not be present"

              docker pull ${var.image_name}
              if [ $? -ne 0 ]; then
                  echo "Docker image pull failed!" >&2
                  exit 1
              else
                  echo "Docker image pulled successfully."
              fi

              export TUTORIAL_REPO_TO_CLONE=${var.repository}

              if [ -z "$TUTORIAL_REPO_TO_CLONE" ]; then
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
