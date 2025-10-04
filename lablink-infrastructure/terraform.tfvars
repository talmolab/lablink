# Terraform Variables for LabLink Infrastructure
# Copy and customize for your deployment

# DNS Configuration
# Set to your domain name or leave empty to disable DNS
dns_name = ""  # e.g., "example.com" for DNS-based access

# Config Path (relative to this terraform directory)
# This config will be read and passed to the Docker container
config_path = "config/config.yaml"

# Note: Additional configuration like machine type, AMI, etc.
# should be set in config/config.yaml, not here
