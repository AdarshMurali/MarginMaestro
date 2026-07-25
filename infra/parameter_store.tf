locals {
  secret_parameters = {
    OPENAI_API_KEY  = "OpenAI API key (only used when LLM_PROVIDER=openai)"
    DB_PASSWORD     = "Azure SQL password"
    SLACK_BOT_TOKEN = "Slack bot token for margin-call notifications"
    JIRA_API_TOKEN  = "Jira API token for escalation tickets"
  }
}

resource "aws_ssm_parameter" "secrets" {
  for_each = local.secret_parameters

  name        = "/marginmaestro/${var.environment}/${each.key}"
  description = each.value
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}
