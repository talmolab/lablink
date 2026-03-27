#!/bin/bash
# LabLink Client VM Startup Script
# This script runs inside the client container after it starts.
# Use it to install packages, clone repos, or configure the environment.
#
# Available environment variables:
#   $SUBJECT_SOFTWARE  - Software name (e.g., "sleap")
#   $TUTORIAL_REPO_TO_CLONE - Git repository URL (if configured)
#   $VM_NAME - Name of this VM instance
#
# Exit codes:
#   0 = success (VM marked as "running")
#   non-zero = failure (behavior depends on startup_on_error config)

echo ">> Running custom startup script..."

# Example: Install additional Python packages
# pip install numpy pandas matplotlib

# Example: Download sample data
# wget -q https://example.com/sample-data.zip -O /tmp/data.zip
# unzip -q /tmp/data.zip -d /home/user/data/

echo ">> Custom startup script complete."
