# Backend config for client VM terraform state (ci-test environment)
# Bucket name will be passed via -backend-config="bucket=..." at runtime
key            = "ci-test/client/terraform.tfstate"
dynamodb_table = "lock-table"
encrypt        = true