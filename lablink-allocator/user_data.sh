#!/bin/bash

# Create config directory and file
mkdir -p /etc/lablink-allocator
cat <<EOF > /etc/lablink-allocator/config.yaml
${CONFIG_CONTENT}
EOF

IMAGE="ghcr.io/talmolab/lablink-allocator-image:${ALLOCATOR_IMAGE_TAG}"
docker pull $IMAGE
docker run -d -p 80:5000 \
  --mount type=bind,src=/etc/lablink-allocator,dst=/config,ro \
  -e ENVIRONMENT=${RESOURCE_SUFFIX} \
  -e ALLOCATOR_PUBLIC_IP=${ALLOCATOR_PUBLIC_IP} \
  -e ALLOCATOR_KEY_NAME=${ALLOCATOR_KEY_NAME} \
  -e CLOUD_INIT_LOG_GROUP=${CLOUD_INIT_LOG_GROUP} \
  $IMAGE
