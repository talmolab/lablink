#!/bin/bash
set -Eeuo pipefail

# Start time
CLOUD_INIT_START_TIME=$(date +%s)

echo ">> Configuration:"
echo "  - Allocator IP: ${allocator_ip}"
echo "  - Resource Prefix: ${resource_prefix}"
echo "  - Count Index: ${count_index}"
echo "  - Subject Software: ${subject_software}"
echo "  - Image Name: ${image_name}"
echo "  - Machine Type GPU Support: ${gpu_support}"
echo "  - GitHub Repository: ${repository}"
echo "  - Log Group: ${cloud_init_output_log_group}"

VM_NAME="${resource_prefix}-vm-${count_index}"
ALLOCATOR_IP="${allocator_ip}"
ALLOCATOR_URL="${allocator_url}"
API_TOKEN="${api_token}"
STATUS_ENDPOINT="$ALLOCATOR_URL/api/vm-status"
LOG_GROUP="${cloud_init_output_log_group}"
CLOUD_INIT_LOG="/var/log/cloud-init-output.log"

# Function to send status updates
send_status() {
    local status="$1"
    curl -s -X POST "$STATUS_ENDPOINT" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_TOKEN" \
        -d "{\"hostname\": \"$VM_NAME\", \"status\": \"$status\"}" --max-time 5 || true
}

# Trap any command failure and report error status immediately
trap 'send_status "error"' ERR

# Send initial status
send_status "initializing"

# --- Install log shipper and start tailing cloud-init log early ---
cat > /usr/local/bin/log_shipper.sh <<'SHIPPER_EOF'
${log_shipper_sh}
SHIPPER_EOF
chmod +x /usr/local/bin/log_shipper.sh

echo ">> Starting log shipper for cloud-init log..."
nohup /usr/local/bin/log_shipper.sh "$CLOUD_INIT_LOG" "$ALLOCATOR_URL" "$VM_NAME" "$LOG_GROUP" \
    >> /var/log/log_shipper.log 2>&1 &
LOG_SHIPPER_CLOUD_INIT_PID=$!
echo ">> Log shipper started (PID: $LOG_SHIPPER_CLOUD_INIT_PID)"

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

    DOCKER_WAIT=0
    until docker info >/dev/null 2>&1; do
        sleep 1
        DOCKER_WAIT=$((DOCKER_WAIT + 1))
        if [ "$DOCKER_WAIT" -ge 60 ]; then
            echo "Docker failed to start within 60 seconds!" >&2
            send_status "error"
            exit 1
        fi
    done

    echo ">> Docker restarted with cgroupfs."

    nvidia-smi -pm 1 || true
else
    echo ">> No GPU support detected. Continuing without GPU features."
fi

echo ">> Pulling application image ${image_name}…"
if ! docker pull "${image_name}"; then
    echo "Docker image pull failed!" >&2
    send_status "error"
    exit 1
fi
echo ">> Image pulled."

DOCKER_GPU_ARGS=""
if [ "$HAS_GPU" = true ]; then
    DOCKER_GPU_ARGS="--runtime=nvidia --gpus all"
fi

echo "> Creating config directory…"
sudo mkdir -p /etc/config

# Decode base64-encoded startup script to preserve $ and other special characters
echo ">> DEBUG: startup_content_b64 is_empty=${startup_content_b64 == "" ? "true" : "false"}, length=${length(startup_content_b64)}"
%{ if startup_content_b64 != "" ~}
echo ">> DEBUG: Writing custom startup script (base64 length: ${length(startup_content_b64)})"
echo '${startup_content_b64}' | base64 -d > /etc/config/custom-startup.sh
%{ else ~}
echo ">> DEBUG: No custom startup script provided, creating empty file"
touch /etc/config/custom-startup.sh
%{ endif ~}
chmod +x /etc/config/custom-startup.sh


# Stop and remove any existing containers (idempotent for re-runs)
EXISTING=$(docker ps -aq 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo ">> Stopping existing containers for clean re-run..."
    docker stop $EXISTING 2>/dev/null || true
    docker rm $EXISTING 2>/dev/null || true
fi

echo ">> Starting container..."
if docker run -dit $DOCKER_GPU_ARGS \
    --mount type=bind,src=/etc/config,dst=/docker_scripts/,ro \
    -e ALLOCATOR_HOST="${allocator_ip}" \
    -e ALLOCATOR_URL="${allocator_url}" \
    -e TUTORIAL_REPO_TO_CLONE="${repository}" \
    -e VM_NAME="${resource_prefix}-vm-${count_index}" \
    -e SUBJECT_SOFTWARE="${subject_software}" \
    -e STARTUP_ON_ERROR="${startup_on_error}" \
    -e API_TOKEN="${api_token}" \
    --network host \
    "${image_name}"; then
    send_status "running"
else
    echo "Container launch failed!"
    send_status "error"
    exit 1
fi

# Start log shipper for Docker container json-log
CONTAINER_ID=$(docker ps -q --latest 2>/dev/null || true)
if [ -n "$CONTAINER_ID" ]; then
    DOCKER_LOG_PATH=$(docker inspect --format='{{.LogPath}}' "$CONTAINER_ID" 2>/dev/null || true)
    if [ -n "$DOCKER_LOG_PATH" ] && [ -f "$DOCKER_LOG_PATH" ]; then
        echo ">> Starting log shipper for Docker container log ($DOCKER_LOG_PATH)..."
        nohup /usr/local/bin/log_shipper.sh "$DOCKER_LOG_PATH" "$ALLOCATOR_URL" "$VM_NAME" "$LOG_GROUP" --docker-json \
            >> /var/log/log_shipper.log 2>&1 &
        echo ">> Docker log shipper started (PID: $!)"
    else
        echo ">> WARNING: Could not find Docker json-log path for container $CONTAINER_ID"
    fi
else
    echo ">> WARNING: No running container found for Docker log shipping"
fi

# End time
CLOUD_INIT_END=$(date +%s)
CLOUD_INIT_DURATION=$((CLOUD_INIT_END - CLOUD_INIT_START_TIME))

# Send timing data to allocator with retry logic
MAX_ATTEMPTS=5
for i in {1..5}; do
    echo ">> $(date -Is) Sending cloud-init timing data to allocator (attempt $i/$MAX_ATTEMPTS)…"
    echo "    - Start Time: $CLOUD_INIT_START_TIME"
    echo "    - End Time: $CLOUD_INIT_END"
    echo "    - Duration (seconds): $CLOUD_INIT_DURATION"

    # Capture HTTP status code
    HTTP_CODE=$(curl -s -w "%%{http_code}" -o /tmp/metrics_response.txt \
        -X POST "$ALLOCATOR_URL/api/vm-metrics/$VM_NAME" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $API_TOKEN" \
        -d "{
            \"cloud_init_start\": $CLOUD_INIT_START_TIME,
            \"cloud_init_end\": $CLOUD_INIT_END,
            \"cloud_init_duration_seconds\": $CLOUD_INIT_DURATION
        }" --max-time 15 2>/dev/null || echo "000")

    # Check if successful (HTTP 2xx)
    if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
        echo ">> $(date -Is) Metrics sent successfully (HTTP $HTTP_CODE)"
        break
    else
        echo ">> $(date -Is) Metrics send failed (HTTP $HTTP_CODE)"

        # If this was the last attempt, give up
        if [ $i -eq $MAX_ATTEMPTS ]; then
            echo ">> $(date -Is) WARNING: Failed to send metrics after $MAX_ATTEMPTS attempts"
            break
        fi

        # Exponential backoff with jitter
        BASE_DELAY=$((2 ** (i - 1)))
        JITTER=$((RANDOM % BASE_DELAY + 1))
        DELAY=$((BASE_DELAY + JITTER))

        echo ">> $(date -Is) Retrying in $${DELAY}s..."
        sleep $DELAY
    fi
done

echo ">> $(date -Is) Container launched successfully."
