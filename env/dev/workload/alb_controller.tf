# AWS Load Balancer Controller (Phase A shared Ingress edge).

data "aws_iam_policy_document" "lbc_assume" {
  count = local.use_controller ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lbc" {
  count = local.use_controller ? 1 : 0

  name               = "${var.name_prefix}-aws-lbc"
  assume_role_policy = data.aws_iam_policy_document.lbc_assume[0].json
}

resource "aws_iam_policy" "lbc" {
  count = local.use_controller ? 1 : 0

  name   = "${var.name_prefix}-aws-lbc"
  policy = file("${path.module}/iam-policy-lbc.json")
}

resource "aws_iam_role_policy_attachment" "lbc" {
  count = local.use_controller ? 1 : 0

  role       = aws_iam_role.lbc[0].name
  policy_arn = aws_iam_policy.lbc[0].arn
}
