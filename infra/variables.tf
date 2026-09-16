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
  description = "EC2 instance type for the app box (runs the API + Chroma via Docker Compose). Downsized from t3.small to t3.micro (2026-09-16, AWS cost reduction pass) -- measured live usage was ~245MB (app) + ~20MB (chroma) + ~320MB OS/Docker overhead against t3.small's 2GB, comfortably fitting t3.micro's 1GB with headroom; t3.nano's 512MB was ruled out since OS/Docker overhead alone exceeds it. The app's URL is still always-on (linked from a resume), so this isn't scaled to zero between uses -- only the instance size changed, not the always-on architecture."
  type        = string
  default     = "t3.micro"
}
