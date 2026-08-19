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


# HTTP listener (optional, for development without SSL)
resource "aws_lb_listener" "http" {
  count             = var.enable_http ? 1 : 0
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.enable_https && var.http_redirect_to_https ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = var.enable_https && var.http_redirect_to_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "forward" {
      for_each = var.enable_https && var.http_redirect_to_https ? [] : [1]
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

# HTTP target group (for HTTP-only setups or when HTTPS is disabled)
resource "aws_lb_target_group" "http" {
  count       = var.enable_http ? 1 : 0
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

# Update HTTPS target group to be conditional
resource "aws_lb_target_group" "https" {
  count       = var.enable_https ? 1 : 0
  name        = "${var.name_prefix}-tg-https"
  port        = 443
  protocol    = "HTTPS"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    interval            = 30
    path                = "/"
    protocol            = "HTTPS"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 5
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-tg-https"
  })
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
