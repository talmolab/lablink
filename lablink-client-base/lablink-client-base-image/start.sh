#!/bin/bash

echo "Running subscribe script..."

echo "ALLOCATOR_HOST: $ALLOCATOR_HOST"
echo "TUTORIAL_REPO_TO_CLONE: $TUTORIAL_REPO_TO_CLONE"
echo "SUBJECT_SOFTWARE: $SUBJECT_SOFTWARE"

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

# Create logs directory if it doesn't exist
mkdir -p /home/client/logs

# Activate the conda environment and run the subscribe script
/home/client/miniforge3/bin/conda run -n base subscribe allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SUBJECT_SOFTWARE >> /home/client/logs/subscribe.log 2>&1 &

# Wait for the subscribe script to start
sleep 5

# Run update_inuse_status
/home/client/miniforge3/bin/conda run -n base update_inuse_status allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SUBJECT_SOFTWARE >> /home/client/logs/update_inuse_status.log 2>&1 &

# Wait for the subscribe script to start
sleep 5

# Run GPU health check
/home/client/miniforge3/bin/conda run -n base check_gpu allocator.host=$ALLOCATOR_HOST allocator.port=80 >> /home/client/logs/gpu_health.log 2>&1 &

# Keep the container alive
tail -f /dev/null