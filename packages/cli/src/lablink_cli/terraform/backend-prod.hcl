# Backend configuration for PROD environment
# Uses S3 backend for shared state management
# State stored in: s3://<bucket_name>/prod/terraform.tfstate
#
# Usage (Local):
#   ../scripts/init-terraform.sh prod  # Reads bucket from config/config.yaml
#   terraform plan -var="resource_suffix=prod"
#   terraform apply -var="resource_suffix=prod"
#
# Usage (Manual):
#   terraform init -backend-config=backend-prod.hcl -backend-config="bucket=YOUR-BUCKET"
#   terraform plan -var="resource_suffix=prod"
#   terraform apply -var="resource_suffix=prod"
#
# Usage (GitHub Actions):
#   Workflow: Deploy LabLink Infrastructure
#   Choose environment: prod
#
# Resource naming: All resources suffixed with -prod (e.g., lablink-eip-prod)
key            = "prod/terraform.tfstate"
dynamodb_table = "lock-table"
encrypt        = true
