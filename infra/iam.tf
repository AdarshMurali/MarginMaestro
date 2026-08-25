data "aws_iam_policy_document" "read_secrets" {
  statement {
    sid    = "ReadMarginMaestroSecrets"
    effect = "Allow"

    actions = [
      "secretsmanager:GetSecretValue",
    ]

    resources = [data.aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_policy" "read_secrets" {
  name        = "marginmaestro-${var.environment}-read-secrets"
  description = "Least-privilege read access to MarginMaestro's Secrets Manager secret"
  policy      = data.aws_iam_policy_document.read_secrets.json
}
