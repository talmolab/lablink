#!/bin/bash
set -euo pipefail

echo ">> Configuration:"
echo "  - Allocator IP: ${allocator_ip}"
echo "  - Resource Suffix: ${resource_suffix}"
echo "  - Count Index: ${count_index}"
echo "  - Subject Software: ${subject_software}"
echo "  - Image Name: ${image_name}"
echo "  - Machine Type GPU Support: ${gpu_support}"
echo "  - GitHub Repository: ${repository}"

VM_NAME="lablink-vm-${fresource_suffix}-${count.index + 1}"
ALLOCATOR_IP="${allocator_ip}"
STATUS_ENDPOINT="http://$ALLOCATOR_IP/api/vm-status/"

# Function to send status updates
send_status() {
    local status="$1"
    curl -s -X POST "$STATUS_ENDPOINT" \
        -H "Content-Type: application/json" \
        -d "{\"hostname\": \"$VM_NAME\", \"status\": \"$status\"}" --max-time 5 || true
}

# Send initial status
send_status "initializing"

echo ">> Installing CloudWatch agent…"

wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm

if ! sudo rpm -U ./amazon-cloudwatch-agent.rpm; then
    echo "CloudWatch agent installation failed!" >&2
    exit 1
fi

echo ">> CloudWatch agent installed."

echo ">> Configuring CloudWatch agent…"

cat >/opt/aws/amazon-cloudwatch-agent/bin/config.json <<'EOF'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/cloud-init-output.log",
            "log_group_name": "cloud-init-output",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%b %d %H:%M:%S"
          }
        ]
      }
    }
  }
}
EOF
echo ">> CloudWatch agent configuration complete."

echo ">> Starting CloudWatch agent…"
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/bin/config.json -s

echo ">> CloudWatch agent started."

echo ">> Checking GPU Support…"

if command -v nvidia-smi >/dev/null 2>&1; then
    AMI_GPU_SUPPORT=true
    echo ">> AMI GPU support detected. Checking NVIDIA drivers…"
else
    AMI_GPU_SUPPORT=false
    echo ">> AMI GPU support not detected."
fi

if [ "$AMI_GPU_SUPPORT" = ${gpu_support} ] && [ ${gpu_support} = true ]; then
    HAS_GPU=true
    echo ">> GPU support matches configuration."
else
    HAS_GPU=false
    echo ">> GPU support mismatch! Expected: ${gpu_support}, Detected: $AMI_GPU_SUPPORT\nWarning: Using CPU to launch containers."
fi

if [ "$HAS_GPU" = true ]; then
    echo ">> Switching Docker to cgroupfs for NVIDIA runtime…"
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

    until docker info >/dev/null 2>&1; do
        sleep 1
    done

    echo ">> Docker restarted with cgroupfs."

    nvidia-smi -pm 1 || true
else
    echo ">> No GPU support detected. Continuing without GPU features."
fi

echo ">> Pulling application image ${image_name}…"
if ! docker pull "${image_name}"; then
    echo "Docker image pull failed!" >&2
    exit 1
fi
echo ">> Image pulled."

DOCKER_GPU_ARGS=""
if [ "$HAS_GPU" = true ]; then
    DOCKER_GPU_ARGS="--runtime=nvidia --gpus all"
fi

echo ">> Starting container..."
if docker run -dit $DOCKER_GPU_ARGS \
    -e ALLOCATOR_HOST="${allocator_ip}" \
    -e TUTORIAL_REPO_TO_CLONE="${repository}" \
    -e VM_NAME="lablink-vm-${resource_suffix}-${count_index}" \
    -e SUBJECT_SOFTWARE="${subject_software}" \
    "${image_name}"; then
    send_status "running"
else
    echo "Container launch failed!"
    send_status "failed"
    exit 1
fi

echo ">> Container launched."
