#!/bin/bash
export PYTHONUNBUFFERED=1

# Start
CONTAINER_START_TIME=$(date +%s)

# Activate virtual environment
source /home/client/.venv/bin/activate

echo "Running subscribe script..."

echo "ALLOCATOR_HOST: $ALLOCATOR_HOST"
echo "TUTORIAL_REPO_TO_CLONE: $TUTORIAL_REPO_TO_CLONE"
echo "SUBJECT_SOFTWARE: $SUBJECT_SOFTWARE"
echo "CLOUD_INIT_LOG_GROUP: $CLOUD_INIT_LOG_GROUP"

# Clone the tutorial repository if specified
if [ -n "$TUTORIAL_REPO_TO_CLONE" ]; then
  mkdir -p /home/client/Desktop
  cd /home/client/Desktop
  echo "Cloning repository $TUTORIAL_REPO_TO_CLONE..."
  sudo -u client git clone "$TUTORIAL_REPO_TO_CLONE"
  if [ $? -ne 0 ]; then
    echo "Failed to clone repository $TUTORIAL_REPO_TO_CLONE"
  else
    echo "Successfully cloned repository $TUTORIAL_REPO_TO_CLONE"
  fi
else
  echo "TUTORIAL_REPO_TO_CLONE not set. Skipping clone step."
fi

# Run the custom startup script if it exists
if [ -f "/docker_scripts/custom-startup.sh" ]; then
  echo "Running custom startup script..."
  sudo chmod +x /docker_scripts/custom-startup.sh
  bash /docker_scripts/custom-startup.sh
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "Warning: custom startup script exited with code $rc"
    if [ "${STARTUP_ON_ERROR}" = "fail" ]; then
      exit $rc
    fi
  fi
else
  echo "No custom startup script found. Skipping."
fi

# Create a logs directory
LOG_DIR="/home/client/logs"
mkdir -p "$LOG_DIR"

# Run subscribe in background, but preserve stdout + stderr to docker logs and file
# Services read ALLOCATOR_URL from environment if set (HTTPS support), otherwise use allocator.host
subscribe \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 \
  2>&1 | tee "$LOG_DIR/subscribe.log" &

# Run update_inuse_status
update_inuse_status \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SUBJECT_SOFTWARE \
  2>&1 | tee "$LOG_DIR/update_inuse_status.log" &

# Run GPU health check
check_gpu \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 \
  2>&1 | tee "$LOG_DIR/check_gpu.log" &

touch "$LOG_DIR/placeholder.log"

# End time
CONTAINER_END_TIME=$(date +%s)
CONTAINER_DURATION=$((CONTAINER_END_TIME - CONTAINER_START_TIME))

# Send container startup completion to allocator
# The ALLOCATOR_URL variable includes the protocol (http/https), so it can be used directly.
curl -X POST "$ALLOCATOR_URL/api/vm-metrics/$VM_NAME" \
  -H "Content-Type: application/json" \
  -d "{
    \"container_start_time\": $CONTAINER_START_TIME,
    \"container_end_time\": $CONTAINER_END_TIME,
    \"container_startup_duration_seconds\": $CONTAINER_DURATION
  }" --max-time 5 || true

# Keep container alive
tail -F "$LOG_DIR/subscribe.log" "$LOG_DIR/update_inuse_status.log" "$LOG_DIR/check_gpu.log" "$LOG_DIR/placeholder.log"