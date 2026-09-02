# Per-tenant IRSA + Secrets Manager. Master RDS secret is only for the migrate Job.
# Tenant set is local.tenants (var.tenant_ids when enable_rds).

resource "random_password" "tenant_db" {
  for_each = local.tenants

  length           = 16
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "tenant" {
  for_each = local.tenants

  name                    = "${var.name_prefix}/rds/tenant-${each.key}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "tenant" {
  for_each = local.tenants

  secret_id = aws_secretsmanager_secret.tenant[each.key].id
  secret_string = jsonencode({
    username  = "tenant_${each.key}"
    password  = random_password.tenant_db[each.key].result
    host      = module.rds[0].rds_host
    port      = 5432
    dbname    = "postgres"
    tenant_id = each.key
  })
}

data "aws_iam_policy_document" "tenant_assume" {
  for_each = local.tenants

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:tenant-${each.key}:test-app"]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "tenant" {
  for_each = local.tenants

  name               = "${var.name_prefix}-tenant-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.tenant_assume[each.key].json
}

data "aws_iam_policy_document" "tenant_secrets" {
  for_each = local.tenants

  statement {
    sid       = "ReadOwnTenantSecret"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [aws_secretsmanager_secret.tenant[each.key].arn]
  }
}

resource "aws_iam_role_policy" "tenant_secrets" {
  for_each = local.tenants

  name   = "${var.name_prefix}-tenant-${each.key}-secrets"
  role   = aws_iam_role.tenant[each.key].id
  policy = data.aws_iam_policy_document.tenant_secrets[each.key].json
}

data "aws_iam_policy_document" "migrator_assume" {
  count = var.enable_rds ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:tenant-${local.first_tenant}:test-app-migrate"]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "migrator" {
  count = var.enable_rds ? 1 : 0

  name               = "${var.name_prefix}-rds-migrator"
  assume_role_policy = data.aws_iam_policy_document.migrator_assume[0].json
}

data "aws_iam_policy_document" "migrator_secrets" {
  count = var.enable_rds ? 1 : 0

  statement {
    sid     = "ReadMasterAndTenantSecrets"
    actions = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = concat(
      [module.rds[0].rds_credentials_secret_arn],
      [for s in aws_secretsmanager_secret.tenant : s.arn]
    )
  }
}

resource "aws_iam_role_policy" "migrator_secrets" {
  count = var.enable_rds ? 1 : 0

  name   = "${var.name_prefix}-rds-migrator-secrets"
  role   = aws_iam_role.migrator[0].id
  policy = data.aws_iam_policy_document.migrator_secrets[0].json
}
