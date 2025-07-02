#!/bin/bash

echo "Running subscribe script..."

echo "ALLOCATOR_HOST: $ALLOCATOR_HOST"
echo "TUTORIAL_REPO_TO_CLONE: $TUTORIAL_REPO_TO_CLONE"

# Clone the tutorial repository if specified
if [ -n "$TUTORIAL_REPO_TO_CLONE" ]; then
  mkdir -p /home/client/Desktop
  cd /home/client/Desktop
  echo "Cloning repository $TUTORIAL_REPO_TO_CLONE..."
  sudo -u client git clone "$TUTORIAL_REPO_TO_CLONE"
  if [$? -ne 0]; then
    echo "Failed to clone repository $TUTORIAL_REPO_TO_CLONE"
    exit 1
  else
    echo "Successfully cloned repository $TUTORIAL_REPO_TO_CLONE"
  fi
else
  echo "TUTORIAL_REPO_TO_CLONE not set. Skipping clone step."
fi

# Activate the conda environment and run the subscribe script
/home/client/miniforge3/bin/conda run -n base subscribe allocator.host=$ALLOCATOR_HOST allocator.port=80 client.software=$SOFTWARE_SUBJECT

# Keep the container alive
tail -f /dev/null