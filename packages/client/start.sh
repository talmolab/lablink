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

# Touched once a status later than 'initializing' has been reported, so the
# background retrier below stops instead of racing a newer state back to a
# stale value.
STATUS_SUPERSEDED_FILE="${STATUS_SUPERSEDED_FILE:-/tmp/lablink-status-superseded}"
STATUS_RETRY_INTERVAL="${STATUS_RETRY_INTERVAL_SECONDS:-15}"
STATUS_RETRY_MAX_ATTEMPTS="${STATUS_RETRY_MAX_ATTEMPTS:-40}"
# Per-run state: clear any sentinel a previous run of this container left
# behind. `docker restart` (or the `unless-stopped` policy after a crash)
# re-runs this script against the SAME filesystem, so /tmp is not empty — and
# a stale sentinel would make the retrier below exit immediately on every
# subsequent boot, silently disabling it exactly where it is needed most.
rm -f "$STATUS_SUPERSEDED_FILE"

# Helper to POST VM status to the allocator. Mirrors the send_status
# pattern in user_data.sh. Returns curl's exit status so callers can react
# to a permanent failure; it does not abort the container on its own.
send_status() {
  local status="$1"
  echo ">> Reporting status='$status' to allocator..."
  # --retry-all-errors covers DNS-not-ready ("Could not resolve host") and
  # connection-not-ready ("Connection timed out") alike — both observed for
  # mesh-overlay clients, whose Tailscale route (especially over a DERP
  # relay fallback) isn't actually usable for a few seconds after
  # `tailscale up` returns. Without a retry here, this call's failure is
  # permanent: nothing else in this script ever re-sets `status`, and
  # assign_vm requires status='running', so a client that loses this race
  # can never be handed to a student despite being otherwise healthy.
  curl -sS -X POST "$ALLOCATOR_URL/api/vm-status" \
    -H "Authorization: Bearer $CLIENT_SECRET" \
    -H "Content-Type: application/json" \
    -d "{\"hostname\":\"$VM_NAME\",\"status\":\"$status\"}" \
    --max-time 5 --retry 5 --retry-delay 2 --retry-all-errors
}

# Join the Tailscale overlay when this client was registered with an
# overlay hostname (mesh-overlay connectivity — MeshOverlayClientConnectivity
# on the allocator side). Gated purely on TAILSCALE_AUTHKEY's presence;
# lan_direct/allocator_proxied clients never set it, so this is a no-op
# for every existing deployment.
#
# This runs FIRST, ahead of every allocator call and ahead of the custom
# startup script, because on a mesh-overlay deployment the tailnet may be
# the only route to the allocator at all — every pre-join POST would fail
# outright, not merely race. Joining first also costs far less than it
# saves: a join is seconds, while the startup script can run for minutes
# (and is retried), and a container killed mid-script previously never
# joined the overlay at all.
if [ -n "$TAILSCALE_AUTHKEY" ]; then
  echo "Starting tailscaled..."
  sudo tailscaled >/tmp/tailscaled.log 2>&1 &
  # Wait for tailscaled's local socket to come up before calling `tailscale up` —
  # `tailscale status` exits 0 once the daemon is reachable, whether or not
  # it's logged in yet, so this loop is purely "wait for the socket", not
  # "wait for join".
  for i in $(seq 1 30); do
    sudo tailscale status >/dev/null 2>&1 && break
    sleep 0.5
  done
  echo "Joining Tailscale as $OVERLAY_HOSTNAME..."
  sudo tailscale up --authkey="$TAILSCALE_AUTHKEY" --hostname="$OVERLAY_HOSTNAME"
  if [ $? -ne 0 ]; then
    echo "Failed to join Tailscale overlay" >&2
    touch "$STATUS_SUPERSEDED_FILE"
    send_status "error" || echo ">> WARNING: failed to report status=error"
    exit 1
  fi

  # Tailscale assigns the node's name and it is NOT necessarily the one we
  # asked for: when an existing (possibly offline) node from a prior
  # registration still holds "$OVERLAY_HOSTNAME", MagicDNS appends a numeric
  # suffix -- lablink-client-local-gpu-1 becomes lablink-client-local-gpu-1-1
  # -- and `tailscale up` STILL EXITS 0, so nothing above notices. The
  # allocator dials the name it recorded at registration, so an unreconciled
  # rename black-holes every allocator -> client call and the client is
  # marked Unhealthy forever, while its own logs look perfectly healthy
  # (lablink#404). Read the real name back from the daemon and report it.
  # Same readback the allocator already does for its own node via
  # `tailscale funnel status` (see the CLI's _funnel_status_url).
  #
  # python3 rather than jq: the venv sourced at the top of this script
  # guarantees python3, jq is not installed in this image. DNSName is
  # fully-qualified with a trailing dot ("name.tailnet.ts.net."), and the
  # allocator stores the bare first label and appends the tailnet itself.
  ACTUAL_OVERLAY_HOSTNAME=$(sudo tailscale status --json 2>/dev/null \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].split(".")[0])' \
    2>/dev/null)

  if [ -z "$ACTUAL_OVERLAY_HOSTNAME" ]; then
    echo ">> WARNING: could not read assigned Tailscale hostname back;" \
         "allocator keeps the requested name '$OVERLAY_HOSTNAME'"
  else
    if [ "$ACTUAL_OVERLAY_HOSTNAME" != "$OVERLAY_HOSTNAME" ]; then
      echo ">> NOTE: Tailscale renamed this node:" \
           "requested '$OVERLAY_HOSTNAME', assigned" \
           "'$ACTUAL_OVERLAY_HOSTNAME' (a prior node still holds the" \
           "requested name). Reporting the assigned name to the allocator."
    else
      echo "Joined Tailscale as $ACTUAL_OVERLAY_HOSTNAME (name as requested)."
    fi

    # Reported unconditionally, not only on mismatch, so a row left stale by
    # a previous life of this container is repaired too. Idempotent server-side.
    report_overlay_hostname() {
      curl -sS -X POST "$ALLOCATOR_URL/api/overlay-hostname" \
        -H "Authorization: Bearer $CLIENT_SECRET" \
        -H "Content-Type: application/json" \
        -d "{\"hostname\":\"$VM_NAME\",\"overlay_hostname\":\"$ACTUAL_OVERLAY_HOSTNAME\"}" \
        --max-time 5 --retry 5 --retry-delay 2 --retry-all-errors
    }

    # Keep retrying in the background if the immediate attempt's budget is
    # exhausted. The tailnet route (especially over a DERP relay fallback)
    # isn't reliably usable for a few seconds after `tailscale up` returns,
    # and losing this report permanently strands the allocator on the old
    # name -- the exact failure this whole block exists to prevent. Mirrors
    # the status retrier below.
    if ! report_overlay_hostname; then
      echo ">> WARNING: failed to report overlay hostname; retrying in background"
      (
        for _ in $(seq 1 "$STATUS_RETRY_MAX_ATTEMPTS"); do
          sleep "$STATUS_RETRY_INTERVAL"
          report_overlay_hostname && exit 0
        done
        echo ">> WARNING: gave up reporting overlay hostname" \
             "'$ACTUAL_OVERLAY_HOSTNAME'; the allocator may be dialing a" \
             "dead node -- see lablink#404"
      ) &
    fi
  fi
fi

# Reverse-tunnel connectivity: dial OUT to the allocator and hold one
# WebSocket open, asking it to expose this container's KasmVNC (:6080) and
# agent (:7070) on the loopback alias it assigned us. Gated on CONNECTIVITY
# rather than on a secret's presence: an absent or misspelled value must be a
# loud failure, not a silent no-tunnel.
#
# Unlike the tailscale join this does NOT need to run first -- the tunnel is
# inbound-only (allocator -> client) and this container reaches the
# allocator's HTTP API directly regardless. It does need to be up before a
# session is assigned, hence ahead of the custom startup script.
if [ "$CONNECTIVITY" = "reverse_tunnel" ]; then
  # Report status=error and stop. Used by every pre-launch failure below;
  # tunnel_fail() further down is this plus killing the running tunnel.
  tunnel_abort() {
    echo "$1" >&2
    touch "$STATUS_SUPERSEDED_FILE"
    send_status "error" || echo ">> WARNING: failed to report status=error"
    exit 1
  }

  for v in TUNNEL_URL TUNNEL_PATH_PREFIX TUNNEL_BIND_ADDR CLIENT_SECRET; do
    # ${!v} indirect expansion, not eval -- this script is #!/bin/bash.
    if [ -z "${!v}" ]; then
      tunnel_abort "CONNECTIVITY=reverse_tunnel but $v is unset"
    fi
  done

  # Preflight: can this container reach the allocator at all? The tunnel dials
  # the host in TUNNEL_URL, so if ordinary HTTPS to that host fails, the tunnel
  # cannot come up either -- and wstunnel's output will NOT say so. On a
  # connect-level failure (a name resolving to an unroutable address, no route,
  # a blocked port) it logs only "Opening TCP connection" per retry, at INFO,
  # with no error line for the checks below to match. Observed live 2026-07-31:
  # a client whose DNS resolved the allocator to a tailnet address it had no
  # route to printed "Tunnel process running" and carried on, exactly the
  # reports-healthy-while-unreachable failure this block exists to prevent.
  # So probe positively here rather than inferring health from the absence of
  # a failure line. Retries because a just-started allocator can need a moment.
  #
  # Deliberately NO -f: this asks "can I reach that host at all", not "is the
  # allocator ready". Any HTTP answer -- including the 503 the readiness
  # endpoint returns while THIS client's own tunnel is still unattached --
  # proves reachability. Gating on 2xx deadlocked startup (observed live
  # 2026-07-31): the client waited for a green health check that could only go
  # green once the client's tunnel was up, which this check was blocking.
  #
  # Deliberately -k, same reason: this must not be stricter than the tunnel it
  # gates. wstunnel v10.6.2's --tls-verify-certificate help reads "Disabled by
  # default. The client will happily connect to any server with self-signed
  # certificate." and this branch sets no such flag -- so without -k a
  # self-signed or staging cert aborts a client whose tunnel connects fine.
  TUNNEL_PROBE_URL="$(printf '%s' "$TUNNEL_URL" \
    | sed -e 's|^wss://|https://|' -e 's|^ws://|http://|')/api/health"
  TUNNEL_REACHABLE=""
  for attempt in 1 2 3 4 5; do
    if curl -sk --max-time 5 -o /dev/null "$TUNNEL_PROBE_URL"; then
      TUNNEL_REACHABLE=yes
      break
    else
      # $? must be read here, inside the else: after `fi` it is the *if
      # statement's* status, which is 0 when the condition failed and no else
      # ran. curl's code is the diagnosis: 6 = DNS, 7 = no route / refused,
      # 28 = timeout, 35/60 = TLS. Without it this line names a symptom only.
      probe_rc=$?
      echo "allocator not reachable yet at $TUNNEL_PROBE_URL (attempt $attempt/5, curl exit $probe_rc)"
    fi
    sleep 3
  done
  if [ -z "$TUNNEL_REACHABLE" ]; then
    # A TLS failure that survives -k isn't trust, so don't send them to DNS.
    case "$probe_rc" in
      35|60)
        tunnel_abort "TLS handshake with the allocator at $TUNNEL_PROBE_URL failed (curl exit $probe_rc) -- the tunnel cannot come up. Not a trust problem (nothing here verifies certs): check TUNNEL_URL's scheme and port."
        ;;
      *)
        tunnel_abort "cannot reach the allocator at $TUNNEL_PROBE_URL (curl exit $probe_rc) -- the tunnel cannot come up. Check DNS and routing from inside this container (curl 6 = DNS, 7 = no route / refused, 28 = timeout)."
        ;;
    esac
  fi

  echo "Opening tunnel to $TUNNEL_URL..."
  # Tee to a file as well as the log stream: the liveness check below has to
  # READ this output, because a rejected upgrade does not kill the process.
  TUNNEL_LOG=/tmp/lablink-tunnel-client.log
  # Per-run state, same reason as STATUS_SUPERSEDED_FILE above: `docker
  # restart` re-runs this script against the SAME filesystem, and the tee
  # below is append-only. Without truncating here, a 401/403 logged on ANY
  # earlier boot (e.g. the allocator's DB not yet ready) would survive to
  # kill an already-healthy tunnel on every later boot -- permanently and
  # silently, since the detection below only ever checks this file.
  : > "$TUNNEL_LOG"
  # Process substitution, NOT a `| sed ... &` pipeline: after a pipeline $!
  # is the PID of the last stage (sed), which stays alive whether or not the
  # tunnel did, making the liveness check below vacuous.
  # -P is mandatory: without it the client ignores the URL's path entirely
  # and requests /v1/events, which no tunnel location matches (measured).
  wstunnel client \
    -P "$TUNNEL_PATH_PREFIX" \
    -H "Authorization: Bearer $CLIENT_SECRET" \
    -R tcp://$TUNNEL_BIND_ADDR:6080:127.0.0.1:6080 \
    -R tcp://$TUNNEL_BIND_ADDR:7070:127.0.0.1:7070 \
    "$TUNNEL_URL" > >(sed -u 's/^/[tunnel] /' | tee -a "$TUNNEL_LOG" >&5) 2>&1 &
  TUNNEL_PID=$!

  # Kills the tunnel and reports status=error. Shared by every failure
  # branch below so each one stays a one-liner.
  tunnel_fail() {
    kill "$TUNNEL_PID" 2>/dev/null
    tunnel_abort "$1"
  }

  # Two fatal conditions, checked now and again after the grace window:
  #  - process died (bad binary, bad flag)
  #  - 401/403. wstunnel does NOT exit on a rejected handshake -- it logs
  #    "Invalid status code: NNN" and RETRIES FOREVER, so a kill -0 check
  #    alone would report healthy while the client is unreachable, the exact
  #    failure this feature has shipped three times. Neither can be fixed by
  #    retrying, so they are fatal immediately rather than folded into the
  #    grace window, which exists for errors that CAN self-heal.
  tunnel_check_fatal() {
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
      tunnel_fail "tunnel process exited -- see [tunnel] output above"
    fi
    if grep -qE "Invalid status code: 40[13]" "$TUNNEL_LOG"; then
      tunnel_fail "tunnel handshake rejected (401/403) by the allocator -- see [tunnel] output"
    fi
  }
  tunnel_count_failures() {
    grep -cE "Invalid status code|failed to do websocket handshake|cannot connect to remote server" "$TUNNEL_LOG"
  }

  sleep 5
  tunnel_check_fatal

  # Any OTHER non-101 upgrade response (e.g. a 503 while the allocator's
  # proxy is still warming up) may be transient: wstunnel's own backoff can
  # succeed on the very next attempt, inside the window we just waited out.
  # A point-in-time grep can't tell a permanent failure from one that already
  # recovered, so ask whether failures are STILL accumulating -- snapshot the
  # count, wait a short second window, fail only if it grew.
  # ponytail: fixed 3s window -- if wstunnel's backoff ever exceeds this
  # between attempts, a persistently-failing non-401 tunnel could take an
  # extra cycle to be caught. Widen this (or read wstunnel's own backoff
  # config) if that's ever observed in practice.
  FAILURES=$(tunnel_count_failures)
  if [ "$FAILURES" -gt 0 ]; then
    sleep 3
    tunnel_check_fatal
    if [ "$(tunnel_count_failures)" -gt "$FAILURES" ]; then
      tunnel_fail "tunnel handshake still failing after the grace window -- see [tunnel] output"
    fi
  fi

  echo "Tunnel process running (pid $TUNNEL_PID)"
fi

# Report 'initializing' as soon as the overlay (if any) is up. On cold
# reboot this is redundant with user_data.sh's earlier post, but on warm
# reboot user_data.sh's guard may exit before reaching its send_status —
# this call guarantees the transition rebooting → initializing → running
# regardless of which path brought the container up.
#
# If the immediate attempt exhausts its 10s budget, keep retrying in the
# background rather than giving up: the container's outbound network can be
# unusable for the first few seconds of its life (observed on Docker
# Desktop/WSL2, where a freshly created container's first connects fail
# while the host's NAT path settles). Without this, one lost 10s window
# leaves the allocator staring at a stale status for the entire duration of
# the custom startup script — which can run for minutes.
if ! send_status "initializing"; then
  echo ">> WARNING: failed to report status=initializing; retrying in background"
  (
    for _ in $(seq 1 "$STATUS_RETRY_MAX_ATTEMPTS"); do
      sleep "$STATUS_RETRY_INTERVAL"
      # A later status already won; anything we post now would be stale.
      [ -f "$STATUS_SUPERSEDED_FILE" ] && exit 0
      send_status "initializing" && exit 0
    done
    echo ">> WARNING: gave up reporting status=initializing"
  ) &
fi

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

# Run the custom startup script if it exists and is non-empty, retrying
# with exponential backoff on failure — startup scripts frequently call
# `uv`/pip, which is prone to transient PyPI timeouts when many VMs boot
# in parallel (see lablink#376). Retry re-runs the WHOLE script, so it
# must be safe to run more than once (e.g. `uv tool install` already is).
if [ -f "/docker_scripts/custom-startup.sh" ] && [ -s "/docker_scripts/custom-startup.sh" ]; then
  sudo chmod +x /docker_scripts/custom-startup.sh

  MAX_ATTEMPTS="${STARTUP_MAX_ATTEMPTS:-1}"
  [ "$MAX_ATTEMPTS" -lt 1 ] 2>/dev/null && MAX_ATTEMPTS=1
  BASE_DELAY="${STARTUP_BASE_DELAY_SECONDS:-0}"

  # success_check travels base64-encoded end-to-end (both the AWS and
  # manual/BYO paths) because it's a free-text shell command that could
  # contain characters ($, %) that break Terraform's templatefile()
  # interpolation in user_data.sh — same reason the script content
  # itself is base64-encoded.
  SUCCESS_CHECK=""
  if [ -n "${STARTUP_SUCCESS_CHECK_B64:-}" ]; then
    SUCCESS_CHECK=$(printf '%s' "$STARTUP_SUCCESS_CHECK_B64" | base64 -d 2>/dev/null || true)
  fi

  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    echo "Running custom startup script (attempt $attempt/$MAX_ATTEMPTS)..."
    bash /docker_scripts/custom-startup.sh 2>&1
    rc=$?

    if [ $rc -eq 0 ] && [ -n "$SUCCESS_CHECK" ]; then
      echo "Verifying success with: $SUCCESS_CHECK"
      bash -c "$SUCCESS_CHECK" 2>&1
      rc=$?
      [ $rc -ne 0 ] && echo "Success check failed (exit $rc)"
    fi

    [ $rc -eq 0 ] && break

    if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
      DELAY=$((BASE_DELAY * (2 ** (attempt - 1))))
      JITTER=$((RANDOM % (DELAY + 1)))
      SLEEP=$((DELAY + JITTER))
      echo "Startup script failed (exit $rc); retrying in ${SLEEP}s..."
      sleep "$SLEEP"
    fi
  done

  if [ $rc -ne 0 ]; then
    echo "Warning: custom startup script did not succeed after $MAX_ATTEMPTS attempt(s) (exit $rc)"
    if [ "${STARTUP_ON_ERROR}" = "fail" ]; then
      touch "$STATUS_SUPERSEDED_FILE"
      send_status "error" || echo ">> WARNING: failed to report status=error"
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

# Generate the XFCE configuration before the session launches. See
# desktop-config.sh for why this is a separate script and why it writes the
# xfconf XML store directly instead of calling xfconf-query.
/home/client/desktop-config.sh

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

# Pre-create the X11 and ICE socket directories. This container runs as the
# non-root `client` user, so when Xvnc and libICE start they cannot create
# these themselves and X.Org's trans_mkdir logs, at boot on every VM:
#   [kasmvnc]  _XSERVTransmkdir: ERROR: euid != 0,directory /tmp/.X11-unix ...
#   [xstartup] _IceTransmkdir: ERROR: euid != 0,directory /tmp/.ICE-unix ...
# It is benign -- Xvnc serves over the websocket port and local X clients
# reach DISPLAY :1 over TCP -- but the lines carry the literal word ERROR,
# so an errors-only log view shows nothing else on a healthy VM. Creating
# the dirs root:root with the sticky bit (the standard /tmp/.X11-unix state)
# makes trans_mkdir accept them silently. sudo is available to this user
# (see the tailscaled launch above). Also lets the X1-socket wait below
# succeed instead of spinning for its full timeout.
sudo mkdir -p /tmp/.X11-unix /tmp/.ICE-unix
sudo chmod 1777 /tmp/.X11-unix /tmp/.ICE-unix

# Inert, retained pending a separate cleanup. kasmvnc.yaml is read only by
# the kasmvncserver Perl wrapper, which we bypass to exec Xvnc directly
# (see the launch comment below) -- Xkasmvnc never opens the file. So these
# cert paths are never read, this keypair is never used, and the unreadable
# root:ssl-cert 0640 snakeoil key it was written to work around cannot be
# reached in the first place. We run on the binary's compiled-in defaults.
# Anything that must actually take effect belongs on the Xvnc argv.
if [ ! -s /home/client/.vnc/kasmvnc.pem ]; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout /home/client/.vnc/kasmvnc.key \
    -out /home/client/.vnc/kasmvnc.pem \
    -subj "/CN=lablink-client" -days 3650 \
    > /dev/null 2>&1
  chmod 600 /home/client/.vnc/kasmvnc.key
fi

# Same never-read consumer as the keypair above: this file only means
# something to the Perl wrapper. Kept so that a future switch back to the
# wrapper is not a rediscovery exercise. Do NOT add encoder settings here
# -- they would be silently ignored. They go on the Xvnc argv below.
cat > /home/client/.vnc/kasmvnc.yaml <<'KASMYAML'
network:
  protocol: http
  ssl:
    require_ssl: false
    pem_certificate: /home/client/.vnc/kasmvnc.pem
    pem_key: /home/client/.vnc/kasmvnc.key
logging:
  log_writer_name: all
  log_dest: logfile
  level: 100
KASMYAML

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
#
# The three encoder flags are the desktop-responsiveness tuning. They are on
# the argv rather than in kasmvnc.yaml *because* of the wrapper bypass above:
# that file is parsed only by the wrapper, so an `encoding:` block there
# never reaches this process. Stock KasmVNC never gets cheaper while the
# screen moves -- it holds near-maximum quality through a full-screen redraw
# and falls behind, which participants perceive as choppiness.
#   -DynamicQualityMin 4  stock 7. The 7-8 band is pinned near the top, and
#       KasmVNC varies quality within it by how fast the screen is CHANGING,
#       not by network feedback, so the floor is what buys smooth motion. It
#       returns to 8 once the screen is static. -DynamicQualityMax is left
#       at its compiled default of 8.
#   -VideoTime 2          stock 5. A drag or scroll otherwise spends five
#       seconds in per-rect JPEG/WebP before video mode engages. The matching
#       exit threshold is 3s and is deliberately left alone.
#   -DetectScrolling 1    ships off. Sends a cheap region shift instead of
#       re-encoding the scrolled region.
# Keep Xvnc's GLX init on mesa, away from the host NVIDIA driver's EGL stack.
#
# When the container toolkit is asked for graphics capabilities it bind-mounts
# the host driver's libEGL_nvidia.so.0 and libnvidia-egl-gbm.so.1 in, plus
# 10_nvidia.json and 15_nvidia_gbm.json. libEGL then loads them during
# GlxExtensionInit. Those libraries come from the HOST driver while libdrm.so.2
# comes from this image, and on 24.04 that version skew makes Xvnc abort with a
# double free inside drmFreeDevices ("munmap_chunk(): invalid pointer"), taking
# the desktop down before xfce4-session can start.
#
# Verified on a GPU VM: identical argv, control aborts with signal 6, this
# runs clean. The bind-mounted json files cannot be moved aside ("Device or
# resource busy"), so the loader is pointed away from them instead.
#
# Scoped to this process on purpose -- it does NOT leak into xstartup, the
# desktop session, or SLEAP, which keep the full driver stack and CUDA. The
# desktop is software-rendered anyway (compositing off, no hw3d), so GLX
# resolves through mesa swrast either way and nothing is lost.
mkdir -p /home/client/.config/egl-none
stdbuf -oL -eL env \
    __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json \
    __EGL_EXTERNAL_PLATFORM_CONFIG_DIRS=/home/client/.config/egl-none \
    Xvnc :1 \
    -auth /home/client/.Xauthority \
    -desktop kasmvnc \
    -httpd /usr/share/kasmvnc/www \
    -rfbport 5901 \
    -interface "${KASMVNC_LISTEN:-0.0.0.0}" \
    -websocketPort 6080 \
    -localhost 0 \
    "${AUTH_ARGS[@]}" \
    -AlwaysShared 1 \
    -DynamicQualityMin 4 \
    -VideoTime 2 \
    -DetectScrolling 1 \
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

# Flip VM status to 'running' now that client services are launching. Mark
# 'initializing' superseded first so a background retrier that is still
# mid-sleep exits instead of posting the older status after this one lands.
touch "$STATUS_SUPERSEDED_FILE"
send_status "running" || echo ">> WARNING: failed to report status=running (continuing)"

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
    # DISPLAY=:1 is required for the active-window sampler — xdotool
    # talks to the X server on that display (same one xterm/xstartup
    # above are pinned to). Without it xdotool returns nothing and the
    # bucket falls through to "other", leaving seconds_in_subject_software
    # stuck at 0 even when SLEAP is the focused window.
    LABLINK_MONITORING_CONFIG="$MONITORING_CFG_PATH" DISPLAY=:1 lablink-monitoring \
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
