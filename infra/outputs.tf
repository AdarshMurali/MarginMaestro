output "secrets_manager_secret_arn" {
  description = "ARN of MarginMaestro's Secrets Manager secret (created out-of-band, referenced via data source)"
  value       = data.aws_secretsmanager_secret.app.arn
}

output "read_secrets_policy_arn" {
  description = "ARN of the least-privilege policy for reading MarginMaestro's Secrets Manager secret"
  value       = aws_iam_policy.read_secrets.arn
}

output "documents_bucket_name" {
  description = "Name of the S3 bucket storing the RAG document corpus"
  value       = aws_s3_bucket.documents.bucket
}

output "read_write_documents_policy_arn" {
  description = "ARN of the least-privilege policy for reading/writing the document corpus bucket"
  value       = aws_iam_policy.read_write_documents.arn
}

output "api_url" {
  description = "Public URL of the deployed MarginMaestro API (Elastic IP, HTTP only -- no custom domain/cert yet)"
  value       = "http://${aws_eip.app.public_ip}:8000"
}

output "app_instance_id" {
  description = "EC2 instance ID -- use with `aws ssm start-session --target <id>` for remote shell access (redeploys, log checks; no SSH port is open)"
  value       = aws_instance.app.id
}
