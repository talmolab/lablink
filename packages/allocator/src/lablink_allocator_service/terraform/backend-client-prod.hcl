# Backend config for client VM terraform state (prod environment)
# Bucket name will be passed via -backend-config="bucket=..." at runtime
key            = "prod/client/terraform.tfstate"
dynamodb_table = "lock-table"
encrypt        = true