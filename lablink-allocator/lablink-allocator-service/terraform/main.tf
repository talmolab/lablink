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

resource "aws_instance" "lablink_vm" {
  count                  = var.instance_count
  ami                    = "ami-00c257e12d6828491" # Ubuntu 20.04 for us-west-2
  instance_type          = var.machine_type
  vpc_security_group_ids = [aws_security_group.lablink_sg_.id]
  key_name               = "sleap-lablink" # Replace with your EC2 key pair

  root_block_device {
    volume_size = 30
    volume_type = "gp2"
  }

  user_data = <<-EOF
              #!/bin/bash
              apt update -y
              apt install -y docker.io
              systemctl start docker
              systemctl enable docker
              docker pull ghcr.io/talmolab/lablink-client-base-image:latest
              if [ $? -ne 0 ]; then
                  echo "Docker image pull failed!" >&2
                  exit 1
              else
                  echo "Docker image pulled successfully."
              fi

              echo ${var.allocator_ip}

              docker run -dit -e ALLOCATOR_HOST=${var.allocator_ip} ghcr.io/talmolab/lablink-client-base-image:latest
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
