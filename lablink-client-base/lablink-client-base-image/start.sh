#!/bin/bash

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
    exit 1
  else
    echo "Successfully cloned repository $TUTORIAL_REPO_TO_CLONE"
  fi
else
  echo "TUTORIAL_REPO_TO_CLONE not set. Skipping clone step."
fi

# Create a logs directory
mkdir -p /var/log/lablink

# Run subscribe in background, but preserve stdout + stderr to docker logs and file
/home/client/miniforge3/bin/conda run -n base subscribe \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 logging.group_name=$CLOUD_INIT_LOG_GROUP \
  2>&1 | tee /var/log/lablink/subscribe.log &

# Run update_inuse_status
/home/client/miniforge3/bin/conda run -n base update_inuse_status \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SUBJECT_SOFTWARE logging.group_name=$CLOUD_INIT_LOG_GROUP \
  2>&1 | tee /var/log/lablink/update_inuse_status.log &

# Run GPU health check
/home/client/miniforge3/bin/conda run -n base check_gpu \
  allocator.host=$ALLOCATOR_HOST allocator.port=80 logging.group_name=$CLOUD_INIT_LOG_GROUP \
  2>&1 | tee /var/log/lablink/check_gpu.log &

# Keep container alive
tail -f /var/log/lablink/*.log