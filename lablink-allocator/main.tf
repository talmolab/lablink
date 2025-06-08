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
    from_port   = 5000
    to_port     = 5000
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
  ami             = "ami-00c257e12d6828491" # us-west-2 ubuntu id
  instance_type   = "t2.micro"
  security_groups = [aws_security_group.allow_http.name]
  key_name        = "sleap-lablink" # Replace with your EC2 key pair

  user_data = <<-EOF
              #!/bin/bash
              apt update -y
              apt install -y docker.io
              systemctl start docker
              systemctl enable docker
              docker login ghcr.io -u USERNAME -p GITHUB_TOKEN
              docker pull ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
              docker run -d -p 80:5000 ghcr.io/talmolab/lablink-allocator-image:linux-amd64-test
              EOF

  tags = {
    Name = "lablink_allocator_server"
  }
}

output "ec2_public_ip" {
  value = aws_instance.lablink_allocator_server.public_ip
}

