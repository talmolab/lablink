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

# Pre-seed the xstartup script kasmvncserver invokes after Xkasmvnc is up.
# We use `xfce4-session` (not the `startxfce4` wrapper) because the wrapper
# tries to spawn its own Xorg, which fails in a container with no GPU node
# (Fatal: no screens found). xfce4-session attaches to the existing DISPLAY
# instead. dbus-launch is required so the XFCE bits that need dbus work.
mkdir -p /home/client/.vnc
{
  echo '#!/bin/sh'
  echo 'unset SESSION_MANAGER'
  echo 'unset DBUS_SESSION_BUS_ADDRESS'
  echo 'exec dbus-launch --exit-with-session xfce4-session'
} > /home/client/.vnc/xstartup
chmod +x /home/client/.vnc/xstartup

# Skip kasmvncserver's interactive desktop-environment picker. The wrapper
# runs /usr/lib/kasmvncserver/select-de.sh unless this sentinel exists; in
# a non-tty container, select-de.sh has no stdin and aborts the launch.
touch /home/client/.vnc/.de-was-selected

# kasmvncserver tries to open `network.ssl.pem_certificate` and `pem_key`
# at startup regardless of `require_ssl`. The wrapper's defaults point at
# /etc/ssl/private/ssl-cert-snakeoil.key, which the `client` user can't
# read (root:ssl-cert 0640). Generate a fresh per-VM keypair under ~/.vnc/
# and override the config to point at it. nginx terminates TLS at the
# allocator, so we just need *some* valid keypair here; we never serve
# it on the public path.
if [ ! -s /home/client/.vnc/kasmvnc.pem ]; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout /home/client/.vnc/kasmvnc.key \
    -out /home/client/.vnc/kasmvnc.pem \
    -subj "/CN=lablink-client" -days 3650 \
    > /dev/null 2>&1
  chmod 600 /home/client/.vnc/kasmvnc.key
fi

# Write the per-user kasmvnc.yaml that overrides the system-default cert
# paths and disables SSL enforcement on the listener. nginx upstream is
# plain ws:// because TLS is terminated one layer up at the allocator.
{
  echo 'network:'
  echo '  protocol: http'
  echo '  ssl:'
  echo '    require_ssl: false'
  echo '    pem_certificate: /home/client/.vnc/kasmvnc.pem'
  echo '    pem_key: /home/client/.vnc/kasmvnc.key'
  echo 'logging:'
  echo '  log_writer_name: all'
  echo '  log_dest: logfile'
  echo '  level: 100'
} > /home/client/.vnc/kasmvnc.yaml

# Seed an initial KasmVNC user. kasmvncserver refuses to start without
# at least one user with write access (otherwise it prompts interactively
# and hangs in our non-tty container). The path MUST be ~/.kasmpasswd —
# this is the default of `server.advanced.kasm_password_file` in
# kasmvncserver and is checked by the wrapper at startup.
#
# The allocator's POST /api/session/start (handled by the agent on
# :7070) rotates this password before any student connects; the random
# seed here just satisfies the "has a user with write access" check.
#
# Remove any pre-existing file first: `kasmvncpasswd -rwo` against an
# existing same-username row only updates the password column on some
# builds, leaving the permission column at whatever it was previously
# (we observed empty perms persisting across boots otherwise).
rm -f /home/client/.kasmpasswd
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
