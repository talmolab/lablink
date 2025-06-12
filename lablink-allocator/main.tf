variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}

provider "aws" {
  region = "us-west-2"
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

resource "aws_eip_association" "lablink_allocator_ip_assoc" {
  instance_id   = aws_instance.lablink_allocator_server.id
  allocation_id = aws_eip.lablink_allocator_ip.id
}

output "ec2_public_ip" {
  value = aws_eip.lablink_allocator_ip.public_ip
}

output "private_key_pem" {
  value     = tls_private_key.lablink_key.private_key_pem
  sensitive = true
}

output "ec2_key_name" {
  value       = aws_key_pair.lablink_key_pair.key_name
  description = "The name of the EC2 key used for the allocator"
}