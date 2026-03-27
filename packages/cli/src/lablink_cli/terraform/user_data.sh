#!/bin/bash
set -e

export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a

# Install Docker
apt-get update
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl

# Ensure Docker is running
systemctl start docker
systemctl enable docker

# Conditionally install Caddy (only for letsencrypt and cloudflare SSL providers)
if [ "${INSTALL_CADDY}" = "true" ]; then
  echo ">> Installing Caddy for SSL termination (provider: ${SSL_PROVIDER})"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
else
  echo ">> Skipping Caddy installation (provider: ${SSL_PROVIDER})"
fi

# Create config directory and file in /etc/lablink-allocator in EC2 instance
mkdir -p /etc/lablink-allocator
cat <<EOF > /etc/lablink-allocator/config.yaml
${CONFIG_CONTENT}
EOF

# Create startup script file in /etc/lablink-allocator in EC2 instance if enabled
# Use base64 decoding to preserve $ variables in the script (bash would expand them otherwise)
if [ "${STARTUP_ENABLED}" = "true" ] && [ -n "${CLIENT_STARTUP_SCRIPT_B64}" ]; then
  echo ">> Custom startup: enabled; decoding and writing script"
  echo '${CLIENT_STARTUP_SCRIPT_B64}' | base64 -d > /etc/lablink-allocator/custom-startup.sh
  chmod +x /etc/lablink-allocator/custom-startup.sh
  echo ">> Custom startup script written successfully"
else
  echo ">> Custom startup: disabled or empty script; skipping"
fi

# Start allocator container
# Port binding depends on SSL provider:
# - letsencrypt/cloudflare: 127.0.0.1:5000 (Caddy proxies)
# - acm: 0.0.0.0:5000 (ALB proxies)
# - none: 0.0.0.0:5000 (direct access)
IMAGE="ghcr.io/talmolab/lablink-allocator-image:${ALLOCATOR_IMAGE_TAG}"
docker pull "$IMAGE"

if [ "${INSTALL_CADDY}" = "true" ]; then
  PORT_BINDING="127.0.0.1:5000:5000"
else
  PORT_BINDING="0.0.0.0:5000:5000"
fi

docker run -d -p "$PORT_BINDING" \
  --mount type=bind,src=/etc/lablink-allocator,dst=/config,ro \
  -e ENVIRONMENT=${RESOURCE_SUFFIX} \
  -e ALLOCATOR_PUBLIC_IP=${ALLOCATOR_PUBLIC_IP} \
  -e ALLOCATOR_KEY_NAME=${ALLOCATOR_KEY_NAME} \
  -e CLOUD_INIT_LOG_GROUP=${LOG_GROUP} \
  -e ALLOCATOR_FQDN=${ALLOCATOR_FQDN} \
  "$IMAGE"

# Configure Caddy for SSL termination or HTTP reverse proxy
if [ "${INSTALL_CADDY}" = "true" ]; then
  echo ">> Configuring Caddy for SSL provider: ${SSL_PROVIDER}"

  if [ "${SSL_PROVIDER}" = "letsencrypt" ]; then
    cat <<EOF > /etc/caddy/Caddyfile
# Let's Encrypt SSL with automatic HTTPS
{
    email ${SSL_EMAIL}
}

${DOMAIN_NAME} {
    reverse_proxy localhost:5000
}
EOF
  elif [ "${SSL_PROVIDER}" = "cloudflare" ]; then
    cat <<EOF > /etc/caddy/Caddyfile
# CloudFlare DNS + SSL (managed in CloudFlare)
# Caddy serves HTTP, CloudFlare proxies with SSL
http://${DOMAIN_NAME} {
    reverse_proxy localhost:5000
}
EOF
  fi

  # Restart Caddy to apply configuration
  systemctl restart caddy
  echo ">> Caddy configured and started"
elif [ "${SSL_PROVIDER}" = "none" ]; then
  echo ">> Installing Caddy for HTTP reverse proxy (port 80 -> 5000)"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy

  # Configure Caddy for simple HTTP reverse proxy on port 80
  cat <<EOF > /etc/caddy/Caddyfile
# Simple HTTP reverse proxy (no SSL)
:80 {
    reverse_proxy localhost:5000
}
EOF

  systemctl restart caddy
  echo ">> Caddy configured for HTTP reverse proxy"
else
  echo ">> No Caddy configuration needed (provider: ${SSL_PROVIDER})"
fi

echo ">> LabLink allocator deployment complete"
echo ">> Allocator URL: ${ALLOCATOR_FQDN}"