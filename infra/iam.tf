data "aws_iam_policy_document" "read_parameters" {
  statement {
    sid    = "ReadMarginMaestroParameters"
    effect = "Allow"

    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
    ]

    resources = [for p in aws_ssm_parameter.secrets : p.arn]
  }
}

resource "aws_iam_policy" "read_parameters" {
  name        = "marginmaestro-${var.environment}-read-parameters"
  description = "Least-privilege read access to MarginMaestro's SSM Parameter Store secrets"
  policy      = data.aws_iam_policy_document.read_parameters.json
}
