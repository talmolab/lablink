#!/bin/bash
export PYTHONUNBUFFERED=1

# Start
CONTAINER_START_TIME=$(date +%s)

# --- Chronological logging setup ---------------------------------------
# Save the container's PID-1 stdout on fd 5 BEFORE we redirect fd 1 to a
# tagger. Every top-level line written by this script flows through the
# `[start]` sed and reaches the container's stdout via fd 5. Backgrounded
# services are launched with their own `... | sed ... >&5 &` pipeline, so
# the inner sed writes directly to fd 5 and bypasses the [start] tagger
# (otherwise lines would be double-tagged as "[start] [agent] ...").
exec 5>&1
exec > >(sed -u 's/^/[start] /' >&5) 2>&1
# -----------------------------------------------------------------------

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
    -H "Authorization: Bearer $CLIENT_SECRET" \
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

# Pick the KasmVNC auth scheme based on how the browser will reach us:
#   * allocator_proxied (AWS / default): allocator nginx attaches HTTP
#     Basic Auth server-side. We use KasmVNC's username-based file
#     (.kasmpasswd), -SecurityTypes None at the RFB layer, and the
#     bundled HTTP BasicAuth as the only auth gate.
#   * lan_direct (manual/BYO): the student browser opens the WS
#     straight to ws://<lan_ip>:6080. Modern browsers refuse to attach
#     Basic Auth headers to WebSocket upgrades (URL userinfo is dropped
#     at the URL-parser level), so HTTP BasicAuth here is unreachable.
#     We instead disable BasicAuth and run RFB-level VncAuth; the
#     bundled noVNC sends ?password=<pw> through its in-band VNC auth
#     handshake. VncAuth uses single DES — adequate for a per-session
#     rotated credential, and the only browser-compatible scheme
#     KasmVNC v1.4 supports without TLS plumbing on the client.
CONNECTIVITY="${CONNECTIVITY:-allocator_proxied}"

if [ "$CONNECTIVITY" = "lan_direct" ]; then
  # Xvnc refuses to start without a usable -PasswordFile under
  # -SecurityTypes VncAuth. Seed an 8-byte RFB-format blob; the agent's
  # POST /api/session/start rotates it before any student connects.
  mkdir -p /home/client/.vnc
  SEED_PW=$(openssl rand -base64 6 | head -c 8)
  SEED_PW="$SEED_PW" python3 - <<'PY' > /home/client/.vnc/passwd
import os, sys
from lablink_client_service.agent.kasmvnc import _vncauth_blob
sys.stdout.buffer.write(_vncauth_blob(os.environ["SEED_PW"]))
PY
  chmod 600 /home/client/.vnc/passwd
  unset SEED_PW
  AUTH_ARGS=(-DisableBasicAuth -SecurityTypes VncAuth
             -PasswordFile /home/client/.vnc/passwd)
else
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
  AUTH_ARGS=(-SecurityTypes None
             -PasswordFile /home/client/.vnc/passwd
             -KasmPasswordFile /home/client/.kasmpasswd)
fi

# Start KasmVNC by invoking Xvnc directly. We do NOT use the
# kasmvncserver Perl wrapper because:
#   1. It hardcodes -rfbauth ~/.vnc/passwd, dragging RFB-layer VncAuth(2)
#      back in on top of our -SecurityTypes None.
#   2. Even when -noreset is in argv, this Xvnc build still emits
#      "VNC extension does not support -reset, terminating instead"
#      when the desktop environment unwinds — the -noreset flag alone
#      is insufficient. The only reliable way to keep the X server up
#      is to ensure at least one X client is always connected (see the
#      xterm pin below).
# -interface 0.0.0.0 binds all interfaces; SG ingress (allocator SG only)
# is the network-layer firewall.
stdbuf -oL -eL Xvnc :1 \
    -auth /home/client/.Xauthority \
    -desktop kasmvnc \
    -httpd /usr/share/kasmvnc/www \
    -rfbport 5901 \
    -interface "${KASMVNC_LISTEN:-0.0.0.0}" \
    -websocketPort 6080 \
    -localhost 0 \
    "${AUTH_ARGS[@]}" \
    -AlwaysShared 1 \
    -noreset \
    2>&1 | sed -u 's/^/[kasmvnc] /' >&5 &

# Wait for the X socket so subsequent clients can connect.
for i in $(seq 1 30); do
  [ -e /tmp/.X11-unix/X1 ] && break
  sleep 0.5
done

# Pin a permanent X client to the display BEFORE starting xfce4.
# xterm -iconic holds an X connection without showing a window. When
# xfce4 components fall apart (e.g. xfce4-panel losing its dbus name
# because of the no-system-dbus container env), this client keeps the
# "last client exited" path from firing — which is what was tearing
# Xvnc down ~11 seconds after start despite -noreset being set.
stdbuf -oL -eL env DISPLAY=:1 xterm -iconic -geometry 1x1+0+0 \
    2>&1 | sed -u 's/^/[xterm-pin] /' >&5 &

# Launch xfce4 against the now-live display.
stdbuf -oL -eL env DISPLAY=:1 /home/client/.vnc/xstartup \
    2>&1 | sed -u 's/^/[xstartup] /' >&5 &

# Start the client agent (:7070) — receives per-session password rotations
# from the allocator. Bearer-authenticated via REGISTER_TOKEN env var.
agent 2>&1 | sed -u 's/^/[agent] /' >&5 &

# Flip VM status to 'running' now that client services are launching.
send_status "running"

# Existing health/heartbeat/in-use workers
update_inuse_status \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SUBJECT_SOFTWARE \
  2>&1 | sed -u 's/^/[update_inuse_status] /' >&5 &

check_gpu \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 \
  2>&1 | sed -u 's/^/[check_gpu] /' >&5 &

heartbeat \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 \
  2>&1 | sed -u 's/^/[heartbeat] /' >&5 &

# Tier 1 monitoring agent — launch only when the allocator shipped a
# monitoring block (in REGISTER_RESPONSE) with enabled=true. The agent
# reads its config from $LABLINK_MONITORING_CONFIG; we materialize that
# file here from the registration response, injecting runtime fields
# (allocator URL, hostname, client_secret, client.software for the
# dynamic subject_window_patterns fallback) that the allocator can't
# know at register time. Heredoc-driven Python avoids the JSON-quoting
# hell of `python3 -c '...'`.
MONITORING_CFG_PATH="/tmp/lablink-monitoring.json"
if [ -n "${REGISTER_RESPONSE:-}" ]; then
  REGISTER_RESPONSE="$REGISTER_RESPONSE" \
  ALLOCATOR_URL="${ALLOCATOR_URL:-}" \
  VM_NAME="${VM_NAME:-}" \
  CLIENT_SECRET="${CLIENT_SECRET:-}" \
  SUBJECT_SOFTWARE="${SUBJECT_SOFTWARE:-}" \
  python3 - <<'PYEOF' > "$MONITORING_CFG_PATH" || true
import json, os, sys
try:
    resp = json.loads(os.environ.get("REGISTER_RESPONSE", "") or "{}")
except json.JSONDecodeError:
    resp = {}
m = dict(resp.get("monitoring") or {})
# Inject runtime fields the pusher and subject-pattern fallback need.
m["allocator_url"] = os.environ.get("ALLOCATOR_URL", "")
m["hostname"] = os.environ.get("VM_NAME", "")
m["client_secret"] = os.environ.get("CLIENT_SECRET", "")
m["client_software"] = os.environ.get("SUBJECT_SOFTWARE", "")
sys.stdout.write(json.dumps(m))
PYEOF

  # Launch the agent only if the allocator opted us in. Guard against
  # missing/malformed config: a bad parse must not abort start.sh.
  if python3 -c "import json,sys; d=json.load(open('$MONITORING_CFG_PATH')); sys.exit(0 if d.get('enabled') else 1)" 2>/dev/null; then
    echo ">> Launching Tier 1 monitoring agent (LABLINK_MONITORING_CONFIG=$MONITORING_CFG_PATH)"
    LABLINK_MONITORING_CONFIG="$MONITORING_CFG_PATH" lablink-monitoring \
      2>&1 | sed -u 's/^/[monitoring] /' >&5 &
  else
    echo ">> Tier 1 monitoring disabled (allocator opted out); skipping agent launch."
  fi
else
  echo ">> REGISTER_RESPONSE not set; skipping Tier 1 monitoring agent launch."
fi

# End time
CONTAINER_END_TIME=$(date +%s)
CONTAINER_DURATION=$((CONTAINER_END_TIME - CONTAINER_START_TIME))

# Send container startup completion to allocator
curl -X POST "$ALLOCATOR_URL/api/vm-metrics/$VM_NAME" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $CLIENT_SECRET" \
  -d "{
    \"container_start\": $CONTAINER_START_TIME,
    \"container_end\": $CONTAINER_END_TIME,
    \"container_startup_duration_seconds\": $CONTAINER_DURATION
  }" --max-time 5 || true

# Keep the container alive while any backgrounded service is running.
# On `docker stop` (SIGTERM) or Ctrl-C (SIGINT), disarm the trap first
# (so the re-delivered SIGTERM doesn't re-enter and spin), then `kill 0`
# the whole process group to terminate every backgrounded service
# cleanly within docker's grace period.
trap 'trap - TERM INT; kill 0' TERM INT
wait
