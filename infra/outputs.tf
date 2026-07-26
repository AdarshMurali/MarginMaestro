output "secret_parameter_names" {
  description = "SSM Parameter Store paths created for MarginMaestro secrets"
  value       = [for p in aws_ssm_parameter.secrets : p.name]
}

output "read_parameters_policy_arn" {
  description = "ARN of the least-privilege policy for reading MarginMaestro's SSM parameters"
  value       = aws_iam_policy.read_parameters.arn
}

output "documents_bucket_name" {
  description = "Name of the S3 bucket storing the RAG document corpus"
  value       = aws_s3_bucket.documents.bucket
}

output "read_write_documents_policy_arn" {
  description = "ARN of the least-privilege policy for reading/writing the document corpus bucket"
  value       = aws_iam_policy.read_write_documents.arn
}
