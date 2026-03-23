# Backend configuration for DEV environment
# Uses local state file for rapid development and testing
# No S3 bucket or DynamoDB table required
# State stored in: ./terraform.tfstate
#
# Usage (Local):
#   ../scripts/init-terraform.sh dev
#   terraform plan -var="resource_suffix=dev"
#   terraform apply -var="resource_suffix=dev"
#
# Usage (Manual):
#   terraform init -backend-config=backend-dev.hcl
#   terraform plan -var="resource_suffix=dev"
#   terraform apply -var="resource_suffix=dev"
#
# Usage (GitHub Actions):
#   NOT AVAILABLE - Local development only
#
# Note: Not suitable for team collaboration or CI/CD
# Resource naming: All resources suffixed with -dev (e.g., lablink-eip-dev)