# Backend configuration for TEST environment
# Uses S3 backend for shared state management
# State stored in: s3://<bucket_name>/test/terraform.tfstate
#
# Usage (Local):
#   ../scripts/init-terraform.sh test  # Reads bucket from config/config.yaml
#   terraform plan -var="resource_suffix=test"
#   terraform apply -var="resource_suffix=test"
#
# Usage (Manual):
#   terraform init -backend-config=backend-test.hcl -backend-config="bucket=YOUR-BUCKET"
#   terraform plan -var="resource_suffix=test"
#   terraform apply -var="resource_suffix=test"
#
# Usage (GitHub Actions):
#   Workflow: Deploy LabLink Infrastructure
#   Choose environment: test
#
# Resource naming: All resources suffixed with -test (e.g., lablink-eip-test)
key            = "test/terraform.tfstate"
dynamodb_table = "lock-table"
encrypt        = true
