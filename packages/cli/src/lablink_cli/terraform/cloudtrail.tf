# S3 bucket for CloudTrail logs
resource "aws_s3_bucket" "cloudtrail_logs" {
  bucket        = "lablink-cloudtrail-${var.resource_suffix}-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = {
    Name        = "lablink-cloudtrail-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# S3 bucket encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail_encryption" {
  bucket = aws_s3_bucket.cloudtrail_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 bucket policy for CloudTrail
resource "aws_s3_bucket_policy" "cloudtrail_policy" {
  bucket = aws_s3_bucket.cloudtrail_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSCloudTrailAclCheck"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.cloudtrail_logs.arn
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.cloudtrail_logs.arn}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl" = "bucket-owner-full-control"
          }
        }
      }
    ]
  })
}

# CloudWatch Log Group for CloudTrail
resource "aws_cloudwatch_log_group" "cloudtrail_logs" {
  name              = "lablink-cloudtrail-${var.resource_suffix}"
  retention_in_days = try(local.config_file.monitoring.cloudtrail.retention_days, 90)
}

# IAM role for CloudTrail to write to CloudWatch
resource "aws_iam_role" "cloudtrail_cloudwatch_role" {
  name = "lablink_cloudtrail_cloudwatch_${var.resource_suffix}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "cloudtrail.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

# IAM policy for CloudTrail CloudWatch access
resource "aws_iam_role_policy" "cloudtrail_cloudwatch_policy" {
  name = "lablink_cloudtrail_cloudwatch_policy_${var.resource_suffix}"
  role = aws_iam_role.cloudtrail_cloudwatch_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.cloudtrail_logs.arn}:*"
      }
    ]
  })
}

# CloudTrail
resource "aws_cloudtrail" "lablink_trail" {
  name                          = "lablink-trail-${var.resource_suffix}"
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  include_global_service_events = true
  is_multi_region_trail         = true
  enable_log_file_validation    = true

  cloud_watch_logs_group_arn = "${aws_cloudwatch_log_group.cloudtrail_logs.arn}:*"
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cloudwatch_role.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true
  }

  depends_on = [
    aws_s3_bucket_policy.cloudtrail_policy,
    aws_cloudwatch_log_group.cloudtrail_logs,
    aws_iam_role_policy.cloudtrail_cloudwatch_policy
  ]

  tags = {
    Name        = "lablink-trail-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}