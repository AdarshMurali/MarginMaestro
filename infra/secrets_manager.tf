# MarginMaestro's runtime secrets (DB creds, OPENAI_API_KEY, SLACK_BOT_TOKEN,
# JIRA_API_TOKEN, AUTH_BACKEND_SECRET) live in a single AWS Secrets Manager
# secret, `marginmaestro/<app_env>` -- created and populated out-of-band
# (not by Terraform), matching the existing pattern this AWS account already
# uses for the FinSight_AI project's own secrets. Referenced here as a data
# source, not an `aws_secretsmanager_secret` resource, so Terraform never
# owns or overwrites the secret's contents and a `terraform destroy` can't
# take real credentials with it.
data "aws_secretsmanager_secret" "app" {
  name = "marginmaestro/${var.app_env}"
}
