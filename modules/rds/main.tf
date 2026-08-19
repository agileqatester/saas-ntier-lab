resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-rds-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-rds-subnet-group"
  })
}

resource "aws_security_group" "rds" {
  name        = "${var.name_prefix}-rds-sg"
  description = "Allow Postgres access from EKS"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_security_group_id]
  }

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-rds-sg"
  })
}

resource "aws_security_group_rule" "extra_clients" {
  for_each = var.extra_security_group_ids

  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = each.value
  description              = "Postgres from extra client SG (${each.key})"
}

data "aws_rds_engine_version" "postgres" {
  engine  = "postgres"
  version = var.engine_version
  latest  = true
}

resource "random_password" "db" {
  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db" {
  name                    = "${var.name_prefix}/rds/db-credentials"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db.result
    host     = aws_db_instance.primary.address
    port     = aws_db_instance.primary.port
    dbname   = var.db_name
  })
}

resource "aws_db_instance" "primary" {
  identifier     = "${var.name_prefix}-rds"
  engine         = "postgres"
  engine_version = data.aws_rds_engine_version.postgres.version
  instance_class = var.instance_class
  db_name        = var.db_name

  allocated_storage     = var.allocated_storage
  max_allocated_storage = 0
  storage_type          = "gp3"
  storage_encrypted     = true

  username = var.db_username
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = var.multi_az

  skip_final_snapshot        = var.environment != "prod"
  final_snapshot_identifier  = var.environment == "prod" ? "${var.name_prefix}-final-snapshot" : null
  backup_retention_period    = var.backup_retention_days
  backup_window              = var.backup_window
  deletion_protection        = var.environment == "prod"
  apply_immediately          = true
  auto_minor_version_upgrade = true

  performance_insights_enabled = false

  tags = merge(var.common_tags, {
    Name = "${var.name_prefix}-rds-primary"
  })
}



resource "aws_security_group_rule" "jumpbox_to_rds" {
  count                    = var.create_jumpbox_rule ? 1 : 0
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = var.jumpbox_security_group_id
  description              = "Allow Postgres access from Jumpbox"
}

resource "aws_cloudwatch_metric_alarm" "rds_high_cpu" {
  count = var.sns_topic_arn != "" ? 1 : 0

  alarm_name          = "${var.name_prefix}-rds-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 70
  alarm_description   = "Alarm when RDS CPU exceeds 70%"
  dimensions = {
    DBInstanceIdentifier = var.rds_instance_id != "" ? var.rds_instance_id : aws_db_instance.primary.id
  }
  alarm_actions = [var.sns_topic_arn]
  ok_actions    = [var.sns_topic_arn]
}


