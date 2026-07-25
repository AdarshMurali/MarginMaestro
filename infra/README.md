# infra

Terraform for AWS. Region `ap-south-1`, local state (`terraform.tfstate`, gitignored).

```bash
terraform init
terraform plan     # uses the AWS CLI profile in variables.tf (default: lavanya)
terraform apply
```

- `providers.tf` — AWS provider + version pins.
- `backend.tf` — local state backend.
- `variables.tf` — region/profile/environment inputs.
- `parameter_store.tf` — SSM Parameter Store (SecureString) placeholders for secrets from `.env.example` (OpenAI, DB, Slack, Jira). Values are placeholders (`REPLACE_ME`) with `lifecycle.ignore_changes` on `value` — set the real value out-of-band (console/CLI) after `apply`, Terraform won't overwrite it on subsequent runs.
- `iam.tf` — least-privilege policy scoped to `ssm:GetParameter*` on exactly those parameter ARNs. Not yet attached to a role — that depends on the compute choice below.
- `compute.tf` — deliberately empty. Compute platform (ECS/EC2/Lambda/App Runner) isn't decided yet — see `docs/ROADMAP.md` Phase 10 (MM-102).
- `outputs.tf` — parameter names + the IAM policy ARN.
