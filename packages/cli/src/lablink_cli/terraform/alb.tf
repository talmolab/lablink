# Application Load Balancer for ACM SSL termination
# Only created when ssl.provider = "acm"

# Get default VPC for ALB and security group placement
data "aws_vpc" "default" {
  count   = local.create_alb ? 1 : 0
  default = true
}

# Security group for ALB (allow HTTP/HTTPS from internet)
# NOTE: Security group must be in the same VPC as the ALB. Using default VPC.
resource "aws_security_group" "alb_sg" {
  count  = local.create_alb ? 1 : 0
  name   = "lablink-alb-sg-${var.resource_suffix}"
  vpc_id = data.aws_vpc.default[0].id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTP from internet"
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTPS from internet"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name        = "lablink-alb-sg-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Update allocator security group to allow traffic from ALB
resource "aws_security_group_rule" "allow_alb_to_allocator" {
  count                    = local.create_alb ? 1 : 0
  type                     = "ingress"
  from_port                = 5000
  to_port                  = 5000
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb_sg[0].id
  security_group_id        = aws_security_group.allow_http.id
  description              = "Allow ALB to reach allocator on port 5000"
}

# Get default subnets for ALB (requires at least 2 AZs)
data "aws_subnets" "default" {
  count = local.create_alb ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

# Application Load Balancer
resource "aws_lb" "allocator_alb" {
  count              = local.create_alb ? 1 : 0
  name               = "lablink-alb-${var.resource_suffix}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg[0].id]
  subnets            = data.aws_subnets.default[0].ids

  enable_deletion_protection = false

  tags = {
    Name        = "lablink-alb-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Target group for allocator EC2 instance
resource "aws_lb_target_group" "allocator_tg" {
  count    = local.create_alb ? 1 : 0
  name     = "lablink-tg-${var.resource_suffix}"
  port     = 5000
  protocol = "HTTP"
  vpc_id   = data.aws_vpc.default[0].id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 2
  }

  tags = {
    Name        = "lablink-tg-${var.resource_suffix}"
    Environment = var.resource_suffix
  }
}

# Attach allocator EC2 instance to target group
resource "aws_lb_target_group_attachment" "allocator_attachment" {
  count            = local.create_alb ? 1 : 0
  target_group_arn = aws_lb_target_group.allocator_tg[0].arn
  target_id        = aws_instance.lablink_allocator_server.id
  port             = 5000
}

# HTTP listener (redirect to HTTPS)
resource "aws_lb_listener" "http" {
  count             = local.create_alb ? 1 : 0
  load_balancer_arn = aws_lb.allocator_alb[0].arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# HTTPS listener (forward to target group)
resource "aws_lb_listener" "https" {
  count             = local.create_alb ? 1 : 0
  load_balancer_arn = aws_lb.allocator_alb[0].arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = local.ssl_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.allocator_tg[0].arn
  }
}

# DNS A record for ALB (alias record)
resource "aws_route53_record" "lablink_alb_record" {
  count   = local.dns_enabled && local.dns_terraform_managed && local.create_alb ? 1 : 0
  zone_id = local.zone_id
  name    = local.dns_domain
  type    = "A"

  alias {
    name                   = aws_lb.allocator_alb[0].dns_name
    zone_id                = aws_lb.allocator_alb[0].zone_id
    evaluate_target_health = true
  }

  lifecycle {
    # Prevent accidental deletion in production
    prevent_destroy = false # Set to true for production environments
  }
}

# Output ALB DNS name
output "alb_dns_name" {
  value       = local.create_alb ? aws_lb.allocator_alb[0].dns_name : "N/A"
  description = "DNS name of the Application Load Balancer (when using ACM)"
}