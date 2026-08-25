# infra

Terraform for AWS. Region `ap-south-1`, local state (`terraform.tfstate`, gitignored).

```bash
terraform init
terraform plan     # uses the AWS CLI profile in variables.tf (default: lavanya)
terraform apply
```

- `providers.tf` — AWS provider + version pins.
- `backend.tf` — local state backend.
- `variables.tf` — region/profile/environment/app_env inputs.
- `secrets_manager.tf` — data-source reference to `marginmaestro/<app_env>` in AWS Secrets Manager (DB creds, OPENAI_API_KEY, SLACK_BOT_TOKEN, JIRA_API_TOKEN, AUTH_BACKEND_SECRET). The secret itself is created and populated out-of-band (a one-off script), not by Terraform — this file only reads its ARN for IAM wiring, so `terraform destroy` can never delete real credentials.
- `iam.tf` — least-privilege policy scoped to `secretsmanager:GetSecretValue` on exactly that secret's ARN. Not yet attached to a role — that depends on the compute choice below.
- `compute.tf` — ECS Fargate (decided), not yet written — see `docs/ROADMAP.md` Phase 10 (MM-102).
- `outputs.tf` — the secret's ARN + the IAM policy ARN.
