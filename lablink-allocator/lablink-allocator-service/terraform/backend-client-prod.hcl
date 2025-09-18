bucket         = "tf-state-lablink-allocator-bucket"
key            = "prod/client/terraform.tfstate"
region         = "us-west-2"
dynamodb_table = "lock-table"
encrypt        = true