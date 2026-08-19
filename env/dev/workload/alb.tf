data "aws_caller_identity" "current" {}
data "aws_elb_service_account" "current" {}

locals {
  alb_logs_bucket = "${var.name_prefix}-alb-logs-${data.aws_caller_identity.current.account_id}"
  app_node_port   = 30080
}

resource "aws_s3_bucket" "alb_logs" {
  count = var.enable_alb ? 1 : 0

  bucket        = local.alb_logs_bucket
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "alb_logs" {
  count  = var.enable_alb ? 1 : 0
  bucket = aws_s3_bucket.alb_logs[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  count = var.enable_alb ? 1 : 0

  bucket                  = aws_s3_bucket.alb_logs[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  count  = var.enable_alb ? 1 : 0
  bucket = aws_s3_bucket.alb_logs[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  count  = var.enable_alb ? 1 : 0
  bucket = aws_s3_bucket.alb_logs[0].id

  rule {
    id     = "expire-alb-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = 14
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_policy" "alb_logs" {
  count  = var.enable_alb ? 1 : 0
  bucket = aws_s3_bucket.alb_logs[0].id

  depends_on = [
    aws_s3_bucket_public_access_block.alb_logs,
    aws_s3_bucket_ownership_controls.alb_logs,
  ]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSLogDeliveryWrite"
        Effect    = "Allow"
        Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.alb_logs[0].arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
      },
      {
        Sid       = "AWSLogDeliveryWriteLegacy"
        Effect    = "Allow"
        Principal = { AWS = data.aws_elb_service_account.current.arn }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.alb_logs[0].arn}/alb/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
      }
    ]
  })
}

module "alb" {
  count  = var.enable_alb ? 1 : 0
  source = "../../../modules/alb"

  name_prefix            = var.name_prefix
  vpc_id                 = data.terraform_remote_state.network.outputs.vpc_id
  public_subnet_ids      = data.terraform_remote_state.network.outputs.public_subnet_ids
  enable_http            = true
  enable_https           = false
  http_redirect_to_https = false
  ingress_cidrs          = [var.my_ip]
  target_type            = "instance"
  target_port            = local.app_node_port
  health_check_path      = "/health"
  access_logs_bucket     = aws_s3_bucket.alb_logs[0].id
  access_logs_prefix     = "alb"

  depends_on = [aws_s3_bucket_policy.alb_logs]
}

resource "aws_security_group_rule" "alb_to_nodes" {
  count = var.enable_alb ? 1 : 0

  type                     = "ingress"
  from_port                = local.app_node_port
  to_port                  = local.app_node_port
  protocol                 = "tcp"
  security_group_id        = module.eks.cluster_security_group_id
  source_security_group_id = module.alb[0].alb_security_group_id
  description              = "ALB to EKS NodePort"
}

resource "aws_autoscaling_attachment" "alb" {
  count = var.enable_alb ? 1 : 0

  autoscaling_group_name = module.eks.node_group_asg_name
  lb_target_group_arn    = coalesce(module.alb[0].https_target_group_arn, module.alb[0].http_target_group_arn)
}

resource "aws_sns_topic" "alerts" {
  count = var.enable_alb ? 1 : 0
  name  = "${var.name_prefix}-alerts"
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  count = var.enable_alb ? 1 : 0

  alarm_name          = "${var.name_prefix}-alb-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_description   = "ALB 5xx from the load balancer itself"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
  dimensions = {
    LoadBalancer = module.alb[0].alb_arn_suffix
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name_prefix}/app"
  retention_in_days = 7
}
