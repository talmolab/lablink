# Terraform Variables for LabLink Infrastructure
# Copy and customize for your deployment

# Config Path (relative to this terraform directory)
# This config will be read and passed to the Docker container
# DNS, bucket, and other settings are configured in this file
config_path = "config/config.yaml"

# Note: All configuration including DNS, machine type, AMI, bucket name, etc.
# should be set in config/config.yaml, not here.
# This keeps configuration in a single source of truth.
