terraform {
  # Floor is 1.10, not 1.9: below that the S3 backend can corrupt state on a
  # retried upload rather than fail cleanly, because an aws-sdk-go-v2 bug
  # leaves the PutObject body non-seekable (aws/aws-sdk-go-v2#2485).
  #
  # Do NOT carry the old Terraform 1.9.0 floor across by number. The fix was
  # a pure SDK bump, and OpenTofu pinned aws-sdk-go-v2 v1.23.2 from 1.6.0
  # through 1.9.x — older than the v1.24.0 the bug was reported against.
  # OpenTofu 1.10.0 is the first release carrying the fix. Keep this in step
  # with MIN_OPENTOFU_VERSION in the CLI's commands/doctor.py.
  required_version = ">= 1.10.0, < 2.0.0"
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
