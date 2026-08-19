# Gated by the same enable_rds flag as module.rds (instance + secret + this IRSA role).

data "aws_iam_policy_document" "test_app_assume" {
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
      values = [
        "system:serviceaccount:default:test-app",
        "system:serviceaccount:tenant-a:test-app",
        "system:serviceaccount:tenant-b:test-app",
      ]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "test_app" {
  count = var.enable_rds ? 1 : 0

  name               = "${var.name_prefix}-test-app"
  assume_role_policy = data.aws_iam_policy_document.test_app_assume[0].json
}

data "aws_iam_policy_document" "test_app_secrets" {
  count = var.enable_rds ? 1 : 0

  statement {
    sid       = "ReadRdsSecret"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [module.rds[0].rds_credentials_secret_arn]
  }
}

resource "aws_iam_role_policy" "test_app_secrets" {
  count = var.enable_rds ? 1 : 0

  name   = "${var.name_prefix}-test-app-secrets"
  role   = aws_iam_role.test_app[0].id
  policy = data.aws_iam_policy_document.test_app_secrets[0].json
}
