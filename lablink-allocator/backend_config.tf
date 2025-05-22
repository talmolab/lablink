terraform {
  backend "s3" {
    bucket         = "tf-state-lablink-allocator-bucket"
    key            = "terraform.tfstate"
    region         = "us-west-2"
    dynamodb_table = "lock-table"
    encrypt        = true
  }
}
