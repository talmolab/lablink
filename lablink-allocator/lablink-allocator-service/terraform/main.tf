provider "aws" {
  region = "us-west-2"
}

variable "instance_count" {
  type    = number
  default = 1
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

variable "resource_suffix" {
  type        = string
  default     = "client"
  description = "Suffix to ensure uniqueness"
}

variable "subject_software" {
  type        = string
  default     = "sleap"
  description = "Software subject for the client VM"
}

variable "gpu_support" {
  type        = bool
  description = "Whether the instance machine type supports GPU"
}

resource "aws_security_group" "lablink_sg_" {
  name        = "lablink_client_${var.resource_suffix}"
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
}

# IAM Instance Profile for CloudWatch Agent
resource "aws_iam_instance_profile" "cloudwatch_agent_profile" {
  name = "cloudwatch-agent-profile"
  role = "ec2-cloudwatch-agent-role"
}

# EC2 Instance for LabLink Client
resource "aws_instance" "lablink_vm" {
  count                  = var.instance_count
  ami                    = var.client_ami_id
  instance_type          = var.machine_type
  vpc_security_group_ids = [aws_security_group.lablink_sg_.id]
  key_name               = aws_key_pair.lablink_key_pair.key_name
  iam_instance_profile   = aws_iam_instance_profile.cloudwatch_agent_profile.name
  root_block_device {
    volume_size = 80
    volume_type = "gp3"
  }

  ########################
  # cgroupfs-enabled user_data
  ########################
  user_data = <<-EOF
              #!/bin/bash
              set -euo pipefail

              VM_NAME="lablink-vm-${var.resource_suffix}-${count.index + 1}"
              ALLOCATOR_IP="${var.allocator_ip}"
              STATUS_ENDPOINT="http://$ALLOCATOR_IP/api/vm-status/"

              apt-get update && apt-get install -y amazon-cloudwatch-agent

              mkdir -p /var/log/lablink
              echo ">> Setting up CloudWatch agent…"
              cat <<EOCWCONFIG > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
              {
                "logs": {
                  "logs_collected": {
                    "files": {
                      "collect_list": [
                        {
                          "file_path": "/var/log/cloud-init-output.log",
                          "log_group_name": "/lablink/cloud-init",
                          "log_stream_name": "${VM_NAME}-cloudinit"
                        },
                        {
                          "file_path": "/var/log/lablink/startup.log",
                          "log_group_name": "/lablink/docker",
                          "log_stream_name": "${VM_NAME}-startup"
                        }
                      ]
                    }
                  }
                }
              }
              EOCWCONFIG

              /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json -s

              VM_NAME="lablink-vm-${var.resource_suffix}-${count.index + 1}"
              ALLOCATOR_IP="${var.allocator_ip}"
              STATUS_ENDPOINT="http://$ALLOCATOR_IP/api/vm-status/"

              # Function to send status updates
              send_status() {
                  local status="$1"

                  curl -s -X POST "$STATUS_ENDPOINT" \
                      -H "Content-Type: application/json" \
                      -d "{\"hostname\": \"$VM_NAME\", \"status\": \"$status\"}" --max-time 5 || true
              }

              # Initial status update
              send_status "initializing"

              # Install CloudWatch agent
              echo ">> Installing CloudWatch agent..."
              wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
              rpm -U ./amazon-cloudwatch-agent.rpm

              # Create CloudWatch agent configuration
              cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json <<'CWCONFIG'
              {
                "logs": {
                  "logs_collected": {
                    "files": {
                      "collect_list": [
                        {
                          "file_path": "/var/log/cloud-init-output.log",
                          "log_group_name": "lablink-vm-logs",
                          "log_stream_name": "lablink-vm-${var.resource_suffix}-${count.index + 1}",
                          "timezone": "UTC"
                        }
                      ]
                    }
                  }
                }
              }
              CWCONFIG

              # Start CloudWatch agent
              /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
                  -a fetch-config \
                  -m ec2 \
                  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
                  -s

              echo ">> CloudWatch agent configured and started."

              echo ">> Switching Docker to cgroupfs…"
              cat >/etc/docker/daemon.json <<'JSON'
              {
                "default-runtime": "nvidia",
                "runtimes": {
                  "nvidia": {
                    "path": "nvidia-container-runtime",
                    "runtimeArgs": []
                  }
                },
                "exec-opts": ["native.cgroupdriver=cgroupfs"]
              }
              JSON

              systemctl restart docker

              # Wait until Docker is ready again
              until docker info >/dev/null 2>&1; do
                  sleep 1
              done
              echo ">> Docker restarted with cgroupfs."

              # Optional: keep GPU awake
              nvidia-smi -pm 1 || true

              echo ">> Pulling application image ${var.image_name}…"
              if ! docker pull ${var.image_name}; then
                  echo "Docker image pull failed!" >&2
                  send_status "failed"
                  exit 1
              fi
              echo ">> Image pulled."

              export TUTORIAL_REPO_TO_CLONE=${var.repository}

              if [ -z "$TUTORIAL_REPO_TO_CLONE" ]; then
                  echo ">> No repo specified; starting container without cloning."
                  if docker run -dit --runtime=nvidia --gpus all \
                      -e ALLOCATOR_HOST=${var.allocator_ip} \
                      -e SUBJECT_SOFTWARE=${var.subject_software} \
                      -e VM_NAME="lablink-vm-${var.resource_suffix}-${count.index + 1}" \
                      ${var.image_name}; then
                      send_status "running"
                  else
                      echo ">> Container start failed!"
                      send_status "failed"
                      exit 1
                  fi
              else
                  echo ">> Cloning repo and starting container."
                  if docker run -dit --runtime=nvidia --gpus all \
                      -e ALLOCATOR_HOST=${var.allocator_ip} \
                      -e TUTORIAL_REPO_TO_CLONE=${var.repository} \
                      -e SUBJECT_SOFTWARE=${var.subject_software} \
                      -e VM_NAME="lablink-vm-${var.resource_suffix}-${count.index + 1}" \
                      ${var.image_name}; then
                      send_status "running"
                  else
                      echo ">> Container start failed!"
                      send_status "failed"
                      exit 1
                  fi
              fi

              echo ">> Container launched."

              curl -s -X POST "http://${var.allocator_ip}/api/logs" \
                  -H "Content-Type: application/json" \
                  -d "{\"hostname\": \"lablink-vm-${var.resource_suffix}-${count.index + 1}\", \"log_lines\": \"$(tail -n 200 /var/log/cloud-init-output.log | base64 | tr -d '\n')\"}"

              echo ">> Log sent to allocator."
              EOF

  tags = {
    Name = "lablink-vm-${var.resource_suffix}-${count.index + 1}"
  }
}

# TLS Private Key for LabLink Client
resource "tls_private_key" "lablink_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

# Key Pair for LabLink Client
resource "aws_key_pair" "lablink_key_pair" {
  key_name   = "lablink_key_pair_client_${var.resource_suffix}"
  public_key = tls_private_key.lablink_key.public_key_openssh
}

# CloudWatch Log Group for VM Logs
resource "aws_cloudwatch_log_group" "lablink_client_vm_logs" {
  name              = "lablink-client-vm-logs-${var.resource_suffix}"
  retention_in_days = 14

  tags = {
    Environment = "LabLink"
    Application = "LabLink Client VM"
  }
}

# Outputs
output "vm_instance_ids" {
  description = "List of EC2 instance IDs created"
  value       = aws_instance.lablink_vm[*].id
}

output "vm_public_ips" {
  description = "List of public IPs assigned to the VMs"
  value       = aws_instance.lablink_vm[*].public_ip
}

output "lablink_private_key_pem" {
  description = "Private key used to access EC2 instances"
  value       = tls_private_key.lablink_key.private_key_pem
  sensitive   = true
}
