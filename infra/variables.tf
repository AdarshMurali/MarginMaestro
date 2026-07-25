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
