variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "dengbej-ai"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "s3_bucket_name" {
  description = "S3 bucket name for audio storage (must be globally unique)"
  type        = string
  default     = "dengbej-ai-audio-storage"
}

variable "lambda_function_name" {
  description = "Lambda function name"
  type        = string
  default     = "dengbej-ai-story-generator"
}
