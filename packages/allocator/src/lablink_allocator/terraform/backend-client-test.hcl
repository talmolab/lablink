# Backend config for client VM terraform state (test environment)
# Bucket name will be passed via -backend-config="bucket=..." at runtime
key            = "test/client/terraform.tfstate"
region         = "us-west-2"
dynamodb_table = "lock-table"
encrypt        = true