terraform {
  backend "s3" {
    bucket         = "tf-state-bucket"
    key            = "lablink/terraform.tfstate"
    region         = "us-west-2"
    dynamodb_table = "lock-table"
    encrypt        = true
  }
}
