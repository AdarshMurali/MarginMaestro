variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-south-1"
}

variable "aws_profile" {
  description = "Named AWS CLI profile Terraform should use"
  type        = string
  default     = "lavanya"
}

variable "environment" {
  description = "Deployment environment name, used in resource naming/tagging"
  type        = string
  default     = "local"
}

variable "app_env" {
  description = "Runtime APP_ENV for the deployed app -- selects the `marginmaestro/<app_env>` Secrets Manager secret. Deliberately separate from `environment`: `environment` is baked into already-real resource names (e.g. the S3 bucket) and must not change, while `app_env` only affects the app's secrets lookup path."
  type        = string
  default     = "prod"
}

variable "instance_type" {
  description = "EC2 instance type for the app box (runs the API + Chroma via Docker Compose). t3.small comfortably covers both containers; the app's URL is always-on (linked from a resume), so this isn't scaled to zero between uses."
  type        = string
  default     = "t3.small"
}
