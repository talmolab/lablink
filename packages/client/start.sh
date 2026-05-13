#!/bin/bash
export PYTHONUNBUFFERED=1

# Start
CONTAINER_START_TIME=$(date +%s)

# Activate virtual environment
source /home/client/.venv/bin/activate

echo "ALLOCATOR_HOST: $ALLOCATOR_HOST"
echo "TUTORIAL_REPO_TO_CLONE: $TUTORIAL_REPO_TO_CLONE"
echo "SUBJECT_SOFTWARE: $SUBJECT_SOFTWARE"
echo "CLOUD_INIT_LOG_GROUP: $CLOUD_INIT_LOG_GROUP"

# Helper to POST VM status to the allocator. Mirrors the send_status
# pattern in user_data.sh. Best-effort — a failed POST does not abort
# the container, since the allocator's stale-initializing timer will
# eventually trigger a reboot if we never reach "running".
send_status() {
  local status="$1"
  echo ">> Reporting status='$status' to allocator..."
  curl -sS -X POST "$ALLOCATOR_URL/api/vm-status" \
    -H "Authorization: Bearer $API_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"hostname\":\"$VM_NAME\",\"status\":\"$status\"}" \
    --max-time 5 \
    || echo ">> WARNING: failed to report status=$status (continuing)"
}

# Report 'initializing' as soon as the container's start.sh begins. On cold
# reboot this is redundant with user_data.sh's earlier post, but on warm
# reboot user_data.sh's guard may exit before reaching its send_status —
# this call guarantees the transition rebooting → initializing → running
# regardless of which path brought the container up.
send_status "initializing"

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

# Run the custom startup script if it exists and is non-empty
if [ -f "/docker_scripts/custom-startup.sh" ] && [ -s "/docker_scripts/custom-startup.sh" ]; then
  echo "Running custom startup script..."
  sudo chmod +x /docker_scripts/custom-startup.sh

  bash /docker_scripts/custom-startup.sh 2>&1
  rc=$?

  if [ $rc -ne 0 ]; then
    echo "Warning: custom startup script exited with code $rc"
    if [ "${STARTUP_ON_ERROR}" = "fail" ]; then
      send_status "error"
      exit $rc
    fi
  fi
else
  echo "No custom startup script found. Skipping."
fi

# Create a logs directory
LOG_DIR="/home/client/logs"
mkdir -p "$LOG_DIR"

# kasmvncserver wraps xauth, which expects ~/.Xauthority to exist; missing
# file aborts the launch silently. Touch an empty one as the client user.
touch /home/client/.Xauthority
chmod 600 /home/client/.Xauthority

# Seed an initial KasmVNC user. kasmvncserver refuses to start without
# at least one user with write access (otherwise it prompts interactively
# and hangs in our non-tty container). The path MUST be ~/.kasmpasswd —
# this is the default of `server.advanced.kasm_password_file` in
# kasmvncserver and is checked by the wrapper at startup.
#
# The allocator's POST /api/session/start (handled by the agent on
# :7070) rotates this password before any student connects; the random
# seed here just satisfies the "has a user with write access" check.
SEED_PW=$(openssl rand -base64 24 | tr -d '\n')
echo -e "${SEED_PW}\n${SEED_PW}" \
  | kasmvncpasswd -u kasm_user -rwo /home/client/.kasmpasswd
chmod 600 /home/client/.kasmpasswd
unset SEED_PW

# Start KasmVNC server. -interface 0.0.0.0 binds all interfaces so the
# allocator-proxied WebSocket can reach it. SG ingress (only from the
# allocator SG) is the network-layer firewall.
kasmvncserver :1 -interface "${KASMVNC_LISTEN:-0.0.0.0}" \
              -listen 6080 \
              -localhost no \
              2>&1 | tee "$LOG_DIR/kasmvnc.log" &

# Start the client agent (:7070) — receives per-session password rotations
# from the allocator. Bearer-authenticated via REGISTER_TOKEN env var.
agent 2>&1 | tee "$LOG_DIR/agent.log" &

# Flip VM status to 'running' now that client services are launching.
send_status "running"

# Existing health/heartbeat/in-use workers
update_inuse_status \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SUBJECT_SOFTWARE \
  2>&1 | tee "$LOG_DIR/update_inuse_status.log" &

check_gpu \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 \
  2>&1 | tee "$LOG_DIR/check_gpu.log" &

heartbeat \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 \
  2>&1 | tee "$LOG_DIR/heartbeat.log" &

touch "$LOG_DIR/placeholder.log"

# End time
CONTAINER_END_TIME=$(date +%s)
CONTAINER_DURATION=$((CONTAINER_END_TIME - CONTAINER_START_TIME))

# Send container startup completion to allocator
curl -X POST "$ALLOCATOR_URL/api/vm-metrics/$VM_NAME" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d "{
    \"container_start\": $CONTAINER_START_TIME,
    \"container_end\": $CONTAINER_END_TIME,
    \"container_startup_duration_seconds\": $CONTAINER_DURATION
  }" --max-time 5 || true

# Keep container alive
tail -F "$LOG_DIR/kasmvnc.log" "$LOG_DIR/agent.log" "$LOG_DIR/update_inuse_status.log" "$LOG_DIR/check_gpu.log" "$LOG_DIR/heartbeat.log" "$LOG_DIR/placeholder.log"
