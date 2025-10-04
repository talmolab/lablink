# Backend configuration for TEST environment
# Bucket name will be read from config/config.yaml by init-terraform.sh
key            = "test/terraform.tfstate"
region         = "us-west-2"
dynamodb_table = "lock-table"
encrypt        = true
