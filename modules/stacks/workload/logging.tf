# Fluent Bit IRSA. Log group is aws_cloudwatch_log_group.app (/name_prefix/app).

data "aws_iam_policy_document" "fluent_bit_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [module.eks.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:amazon-cloudwatch:fluent-bit"]
    }
    condition {
      test     = "StringEquals"
      variable = "${module.eks.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fluent_bit" {
  name               = "${var.name_prefix}-fluent-bit"
  assume_role_policy = data.aws_iam_policy_document.fluent_bit_assume.json
}

data "aws_iam_policy_document" "fluent_bit_logs" {
  statement {
    sid     = "WriteAppLogGroup"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = [
      aws_cloudwatch_log_group.app.arn,
      "${aws_cloudwatch_log_group.app.arn}:*",
    ]
  }
  statement {
    sid       = "DescribeLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "fluent_bit_logs" {
  name   = "${var.name_prefix}-fluent-bit-logs"
  role   = aws_iam_role.fluent_bit.id
  policy = data.aws_iam_policy_document.fluent_bit_logs.json
}
