#!/bin/bash

export POSTGRES_HOST_AUTH_METHOD=trust


pg_ctlcluster 17 main restart

# Wait for PostgreSQL to be ready
until pg_isready -U postgres; do
    echo "Waiting for PostgreSQL to start..."
    sleep 2
done

# Activate venv
source /app/.venv/bin/activate

# Generate the init.sql script
echo "Generating init.sql..."
cd /app
generate-init-sql

# Run the init.sql script as the postgres superuser
echo "Running init.sql..."
until pg_isready -U postgres; do sleep 1; done
su postgres -c "psql -d postgres -f /app/init.sql"

# Set listen_addresses = '*' and raise max_connections.
# max_connections must stay above database.py's POOL_MAX_SIZE (200) with
# headroom for autovacuum workers, replication, and admin sessions.
echo "Configuring PostgreSQL to listen on all addresses..."
su postgres -c "psql -d postgres -c \"ALTER SYSTEM SET listen_addresses = '*';\""
su postgres -c "psql -d postgres -c \"ALTER SYSTEM SET max_connections = 300;\""

pg_ctlcluster 17 main restart

# Check if the psql command was successful
if [ $? -eq 0 ]; then
    echo "init.sql executed successfully."
else
    echo "Error executing init.sql."
    exit 1  # Exit if there was an error
fi

# Wait for the new user and database to be ready
until pg_isready -U lablink -d lablink_db; do
    echo "Waiting for lablink_db to be ready..."
    sleep 2
done

CONFIG_DIR="${CONFIG_DIR:-/config}"
CONFIG_NAME="${CONFIG_NAME:-config.yaml}"
mkdir -p "$CONFIG_DIR"

# Seed only if needed
if [ ! -f "$CONFIG_DIR/$CONFIG_NAME" ]; then
  if [ -z "$(ls -A "$CONFIG_DIR" 2>/dev/null || true)" ]; then
    echo "[allocator] Seeding defaults into $CONFIG_DIR ..."
    rsync -a /app/config.defaults/ "$CONFIG_DIR"/
  else
    echo "[allocator] Warning: $CONFIG_DIR/$CONFIG_NAME not found; using whatever exists in \"$CONFIG_DIR\""
  fi
fi

echo "[allocator] Using config: $CONFIG_DIR/$CONFIG_NAME"

# Which connectivity mode this deployment runs. Read from the mounted config
# rather than an env var: the reverse-tunnel mode deliberately adds nothing to
# the compose stack (no env, no port), so the config file is the only source.
# Empty on any failure -- a missing/unparseable config means the tunnel server
# simply does not start, and Flask's own config loading will report the real
# problem.
# Must read the same "$CONFIG_DIR/$CONFIG_NAME" echoed above, never a
# hardcoded /config/config.yaml: both are overridable env knobs, and if this
# read and Flask disagree the tunnel server never starts while Flask still
# reports reverse_tunnel -- /api/health then 503s forever.
CONNECTIVITY_MODE=$(python3 -c "import sys, yaml; print((yaml.safe_load(open(sys.argv[1])) or {}).get('manual', {}).get('connectivity', ''))" "$CONFIG_DIR/$CONFIG_NAME" 2>/dev/null || echo "")

# Reverse-tunnel connectivity: run the shared tunnel server clients attach
# to. Bound to loopback only -- nginx is the sole way in, so the WebSocket
# upgrade always passes through auth_request. Gated on the configured mode so
# lan_direct/mesh_overlay deployments never start it.
if [ "$CONNECTIVITY_MODE" = "reverse_tunnel" ]; then
  echo "Starting tunnel server on 127.0.0.1:8080..."
  mkdir -p /tmp/lablink-tunnel && chmod 700 /tmp/lablink-tunnel
  # Seed an empty document: wstunnel will not start if --restrict-config
  # points at a missing file, and the first client registers later.
  [ -f /tmp/lablink-tunnel/restrictions.yaml ] || \
    printf 'restrictions:\n' > /tmp/lablink-tunnel/restrictions.yaml
  chmod 600 /tmp/lablink-tunnel/restrictions.yaml
  wstunnel server ws://127.0.0.1:8080 \
    --restrict-config /tmp/lablink-tunnel/restrictions.yaml \
    --remote-to-local-server-idle-timeout 20s &
fi

# Start Flask in the background (binds 127.0.0.1:8000).
echo "Starting Flask app on 127.0.0.1:8000..."
lablink-allocator &
FLASK_PID=$!

# Wait for Flask's health endpoint to respond before starting nginx.
# Cap at ~30s of waiting; if Flask isn't up by then something is wrong.
echo "Waiting for Flask to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "Flask is ready."
    break
  fi
  if ! kill -0 "$FLASK_PID" 2>/dev/null; then
    echo "Flask process exited before becoming ready." >&2
    exit 1
  fi
  sleep 1
done

# Validate nginx config; refuse to start if broken.
nginx -t

# Cloudflare Tunnel exposure: connect Cloudflare's edge to this container's
# own nginx (:5000, the port the admin enters as the tunnel's public-hostname
# service URL). The tunnel's ingress config lives in Cloudflare, not here, so
# there is nothing to render locally and nothing to persist -- cloudflared
# pulls it on every start. Gated on the mode so lan_direct/tailscale_funnel
# deployments never start a connector.
if [ "$PARTICIPANT_EXPOSURE" = "cloudflare_tunnel" ]; then
  if [ -z "$CLOUDFLARE_TUNNEL_TOKEN" ]; then
    echo "participant_exposure is 'cloudflare_tunnel' but CLOUDFLARE_TUNNEL_TOKEN is empty." >&2
    echo "Re-run: lablink deploy --cloudflare-tunnel-token <token>" >&2
    exit 1
  fi
  # The origin is configured in Cloudflare, not here; logging it keeps the
  # docs' "type http://localhost:5000" instruction traceable to the code.
  echo "Starting Cloudflare Tunnel connector (expected origin: http://localhost:5000)..."
  # Backgrounded: nginx must reach the exec below to keep the container
  # alive. cloudflared dials Cloudflare first and retries the origin, so
  # starting a second or two before nginx listens is fine.
  cloudflared tunnel --no-autoupdate run --token "$CLOUDFLARE_TUNNEL_TOKEN" &
fi

# Foreground nginx; this keeps the container alive.
echo "Starting nginx on :5000..."
exec nginx -g 'daemon off;'
