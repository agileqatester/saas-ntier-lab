resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb-sg"
  description = "Allow HTTP and HTTPS traffic to ALB"
  vpc_id      = var.vpc_id

  ingress {
    description = "Allow HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  dynamic "ingress" {
    for_each = var.enable_https ? [1] : []
    content {
      description = "Allow HTTPS"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = var.ingress_cidrs
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-alb-sg"
  })
}

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
  internal           = false

  enable_deletion_protection = false

  dynamic "access_logs" {
    for_each = var.access_logs_bucket != "" ? [1] : []
    content {
      bucket  = var.access_logs_bucket
      prefix  = var.access_logs_prefix
      enabled = true
    }
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-alb"
  })
}


locals {
  http_listener_mode = (
    var.enable_https && var.http_redirect_to_https ? "redirect" :
    length(var.path_target_groups) > 0 ? "fixed-response" :
    "forward"
  )
}

resource "aws_lb_listener" "http" {
  count             = var.enable_http ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.http_listener_mode

    dynamic "redirect" {
      for_each = local.http_listener_mode == "redirect" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "fixed_response" {
      for_each = local.http_listener_mode == "fixed-response" ? [1] : []
      content {
        content_type = "text/plain"
        message_body = "use /tenant-a/ or /tenant-b/"
        status_code  = "404"
      }
    }

    dynamic "forward" {
      for_each = local.http_listener_mode == "forward" ? [1] : []
      content {
        target_group {
          arn = var.enable_https ? aws_lb_target_group.https[0].arn : aws_lb_target_group.http[0].arn
        }
      }
    }
  }
}

# HTTPS listener (optional, requires ACM certificate)
resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.https[0].arn
  }
}

# HTTP target group (single-TG mode). Omitted when path_target_groups is set.
resource "aws_lb_target_group" "http" {
  count       = var.enable_http && length(var.path_target_groups) == 0 ? 1 : 0
  name        = "${var.name_prefix}-tg-http"
  port        = var.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = var.target_type

  health_check {
    enabled             = true
    interval            = 30
    path                = var.health_check_path
    protocol            = "HTTP"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-tg-http"
  })
}

# HTTPS listener terminates TLS. Backend matches the HTTP TG: instance/NodePort over HTTP.
resource "aws_lb_target_group" "https" {
  count       = var.enable_https ? 1 : 0
  name        = "${var.name_prefix}-tg-https"
  port        = var.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = var.target_type

  health_check {
    enabled             = true
    interval            = 30
    path                = var.health_check_path
    protocol            = "HTTP"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-tg-https"
  })
}

resource "aws_lb_target_group" "path" {
  for_each = var.enable_http ? var.path_target_groups : {}

  name        = "${var.name_prefix}-tg-${each.key}"
  port        = each.value.target_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = var.target_type

  health_check {
    enabled             = true
    interval            = 30
    path                = var.health_check_path
    protocol            = "HTTP"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-tg-${each.key}"
  })
}

resource "aws_lb_listener_rule" "path" {
  for_each = var.enable_http ? var.path_target_groups : {}

  listener_arn = aws_lb_listener.http[0].arn
  priority     = each.value.priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.path[each.key].arn
  }

  condition {
    path_pattern {
      values = [each.value.path_pattern]
    }
  }
}

# Route53 DNS record (optional - only created if zone_id is provided)
resource "aws_route53_record" "alb_dns" {
  count   = var.route53_zone_id != "" && var.subdomain_name != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.subdomain_name
  type    = "A"

  alias {
    name                   = aws_lb.this.dns_name
    zone_id                = aws_lb.this.zone_id
    evaluate_target_health = true
  }
}
