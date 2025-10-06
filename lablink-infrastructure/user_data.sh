#!/bin/bash
set -e

# Install Docker
apt-get update
apt-get install -y docker.io debian-keyring debian-archive-keyring apt-transport-https curl
systemctl start docker
systemctl enable docker

# Install Caddy for SSL termination
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# Create config directory and file in /etc/lablink-allocator in EC2 instance
mkdir -p /etc/lablink-allocator
cat <<EOF > /etc/lablink-allocator/config.yaml
${CONFIG_CONTENT}
EOF

# Start allocator container on port 5000 (Caddy will proxy to it)
IMAGE="ghcr.io/talmolab/lablink-allocator-image:${ALLOCATOR_IMAGE_TAG}"
docker pull $IMAGE
docker run -d -p 127.0.0.1:5000:5000 \
  --mount type=bind,src=/etc/lablink-allocator,dst=/config,ro \
  -e ENVIRONMENT=${RESOURCE_SUFFIX} \
  -e ALLOCATOR_PUBLIC_IP=${ALLOCATOR_PUBLIC_IP} \
  -e ALLOCATOR_KEY_NAME=${ALLOCATOR_KEY_NAME} \
  -e CLOUD_INIT_LOG_GROUP=${CLOUD_INIT_LOG_GROUP} \
  $IMAGE

# Configure Caddy for SSL termination with Let's Encrypt
# If SSL_STAGING is true, serve HTTP only (no SSL, unlimited testing)
# If SSL_STAGING is false, use Let's Encrypt production server (HTTPS with trusted certs, rate limited)
if [ "${SSL_STAGING}" = "true" ]; then
  cat <<EOF > /etc/caddy/Caddyfile
# Staging mode: HTTP only (no SSL certificates)
http://${DOMAIN_NAME} {
    reverse_proxy localhost:5000
}
EOF
else
  cat <<EOF > /etc/caddy/Caddyfile
# Production mode: HTTPS with Let's Encrypt
${DOMAIN_NAME} {
    reverse_proxy localhost:5000
}
EOF
fi

# Restart Caddy to apply configuration
systemctl restart caddy
