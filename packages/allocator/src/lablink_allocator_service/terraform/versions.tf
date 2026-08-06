terraform {
  # Floor is 1.9, not 1.6: below the 1.8.0 line the S3 backend can corrupt
  # state on a retried upload rather than fail cleanly, because an
  # aws-sdk-go-v2 bug leaves the PutObject body non-seekable
  # (hashicorp/terraform#34528). Let terraform refuse rather than risk it.
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.25"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.1"
    }
  }
}
