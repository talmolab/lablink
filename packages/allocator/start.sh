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

# Set listen_addresses = '*'
echo "Configuring PostgreSQL to listen on all addresses..."
su postgres -c "psql -d postgres -c \"ALTER SYSTEM SET listen_addresses = '*';\""

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

# Foreground nginx; this keeps the container alive.
echo "Starting nginx on :5000..."
exec nginx -g 'daemon off;'
