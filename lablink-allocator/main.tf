variable "resource_suffix" {
  description = "Suffix to append to all resources"
  type        = string
  default     = "prod"
}


provider "aws" {
  region = "us-west-2" # Change this to your preferred region
}

resource "aws_security_group" "allow_http" {
  name = "allows-80-22"

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
}

resource "aws_instance" "lablink_allocator_server" {
  ami             = "ami-0e096562a04af2d8b"
  instance_type   = "t2.micro"
  security_groups = [aws_security_group.allow_http.name]
  key_name        = "sleap-lablink" # Replace with your EC2 key pair

  user_data = <<-EOF
              #!/bin/bash
              docker pull ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
              docker run -d -p 80:5000 ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
              EOF

  tags = {
    Name = "lablink_allocator_server"
  }
}

resource "aws_eip" "lablink_allocator_ip" {}

resource "aws_eip_association" "lablink_allocator_ip_assoc" {
  instance_id   = aws_instance.lablink_allocator_server.id
  allocation_id = aws_eip.lablink_allocator_ip.id
}

output "ec2_public_ip" {
  value = aws_eip.lablink_allocator_ip.public_ip
}

