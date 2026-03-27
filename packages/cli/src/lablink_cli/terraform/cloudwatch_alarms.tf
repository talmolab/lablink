# SNS Topic for Admin Alerts
resource "aws_sns_topic" "admin_alerts" {
  name = "${var.deployment_name}-alerts-topic-${var.environment}"

  tags = merge(local.common_tags, {
    Name = "${var.deployment_name}-alerts-topic-${var.environment}"
  })
}

# SNS Email Subscription
resource "aws_sns_topic_subscription" "admin_email" {
  count     = try(local.config_file.monitoring.enabled, false) ? 1 : 0
  topic_arn = aws_sns_topic.admin_alerts.arn
  protocol  = "email"
  endpoint  = try(local.config_file.monitoring.email, "")
}

# Metric Filter: Mass Instance Launches
resource "aws_cloudwatch_log_metric_filter" "run_instances" {
  name           = "${var.deployment_name}-run-instances-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.cloudtrail_logs.name

  pattern = <<PATTERN
{ ($.eventName = RunInstances) && ($.userIdentity.arn = *${var.deployment_name}-allocator-role*) && ($.errorCode NOT EXISTS) }
PATTERN

  metric_transformation {
    name      = "RunInstancesCount"
    namespace = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
    value     = "$.requestParameters.instancesSet.items[0].maxCount"
    unit      = "Count"
  }
}

# Alarm: Mass Instance Launches
resource "aws_cloudwatch_metric_alarm" "mass_instance_launch" {
  alarm_name          = "${var.deployment_name}-alarm-mass-launch-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "RunInstancesCount"
  namespace           = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
  period              = 300 # 5 minutes
  statistic           = "Sum"
  threshold           = try(local.config_file.monitoring.thresholds.max_instances_per_5min, 10)
  alarm_description   = "Alert when allocator launches >${try(local.config_file.monitoring.thresholds.max_instances_per_5min, 10)} instances in 5 minutes"
  alarm_actions       = [aws_sns_topic.admin_alerts.arn]
  treat_missing_data  = "notBreaching"

  tags = merge(local.common_tags, {
    Name     = "${var.deployment_name}-alarm-mass-launch-${var.environment}"
    Severity = "high"
  })
}

# Metric Filter: Large Instance Types
resource "aws_cloudwatch_log_metric_filter" "large_instances" {
  name           = "${var.deployment_name}-large-instances-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.cloudtrail_logs.name

  pattern = <<PATTERN
{ ($.eventName = RunInstances) && ($.userIdentity.arn = *${var.deployment_name}-allocator-role*) && ($.errorCode NOT EXISTS) && (($.requestParameters.instanceType = p4d.*) || ($.requestParameters.instanceType = p3.*) || ($.requestParameters.instanceType = g5.*)) }
PATTERN

  metric_transformation {
    name      = "LargeInstanceLaunched"
    namespace = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
    value     = "1"
    unit      = "Count"
  }
}

# Alarm: Large Instance Types
resource "aws_cloudwatch_metric_alarm" "large_instance_launched" {
  alarm_name          = "${var.deployment_name}-alarm-large-instance-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "LargeInstanceLaunched"
  namespace           = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
  period              = 300
  statistic           = "Sum"
  threshold           = 0 # Alert on ANY large instance
  alarm_description   = "Alert when allocator launches expensive instance types (p4d, p3, g5)"
  alarm_actions       = [aws_sns_topic.admin_alerts.arn]
  treat_missing_data  = "notBreaching"

  tags = merge(local.common_tags, {
    Name     = "${var.deployment_name}-alarm-large-instance-${var.environment}"
    Severity = "critical"
  })
}

# Metric Filter: Unauthorized API Calls
resource "aws_cloudwatch_log_metric_filter" "unauthorized_calls" {
  name           = "${var.deployment_name}-unauthorized-calls-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.cloudtrail_logs.name

  pattern = <<PATTERN
{ (($.errorCode = AccessDenied) || ($.errorCode = UnauthorizedOperation)) && ($.userIdentity.arn = *${var.deployment_name}-allocator-role*) }
PATTERN

  metric_transformation {
    name      = "UnauthorizedAPICalls"
    namespace = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
    value     = "1"
    unit      = "Count"
  }
}

# Alarm: Unauthorized API Calls
resource "aws_cloudwatch_metric_alarm" "unauthorized_calls" {
  alarm_name          = "${var.deployment_name}-alarm-unauthorized-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "UnauthorizedAPICalls"
  namespace           = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
  period              = 900 # 15 minutes
  statistic           = "Sum"
  threshold           = try(local.config_file.monitoring.thresholds.max_unauthorized_calls_per_15min, 5)
  alarm_description   = "Alert when allocator makes unauthorized API calls (possible attack or permission issue)"
  alarm_actions       = [aws_sns_topic.admin_alerts.arn]
  treat_missing_data  = "notBreaching"

  tags = merge(local.common_tags, {
    Name     = "${var.deployment_name}-alarm-unauthorized-${var.environment}"
    Severity = "critical"
  })
}

# Metric Filter: High Termination Rate
resource "aws_cloudwatch_log_metric_filter" "high_termination_rate" {
  name           = "${var.deployment_name}-high-termination-rate-${var.environment}"
  log_group_name = aws_cloudwatch_log_group.cloudtrail_logs.name
  pattern        = <<PATTERN
{ ($.eventName = TerminateInstances) && ($.userIdentity.arn = *${var.deployment_name}-allocator-role*) && ($.errorCode NOT EXISTS) }
PATTERN

  metric_transformation {
    name      = "TerminateInstancesCount"
    namespace = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
    value     = "1"
    unit      = "Count"
  }
}

# Alarm: High Termination Rate
resource "aws_cloudwatch_metric_alarm" "high_termination_rate" {
  alarm_name          = "${var.deployment_name}-alarm-high-termination-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "TerminateInstancesCount"
  namespace           = "LabLinkSecurity/${var.deployment_name}-${var.environment}"
  period              = 300 # 5 minutes
  statistic           = "Sum"
  threshold           = try(local.config_file.monitoring.thresholds.max_terminations_per_5min, 10)
  alarm_description   = "Alert when allocator terminates >${try(local.config_file.monitoring.thresholds.max_terminations_per_5min, 10)} instances in 5 minutes (possible cleanup or attack)"
  alarm_actions       = [aws_sns_topic.admin_alerts.arn]
  treat_missing_data  = "notBreaching"

  tags = merge(local.common_tags, {
    Name     = "${var.deployment_name}-alarm-high-termination-${var.environment}"
    Severity = "high"
  })
}
