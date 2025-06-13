terraform {
  backend "s3" {}
}
# The backend configuration is intentionally left empty.
# It will be populated by the `terraform init` command.
# This allows the backend to be configured dynamically based on the environment.
