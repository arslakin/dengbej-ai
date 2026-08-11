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

variable "s3_bucket_name" {
  description = "S3 bucket name for audio storage"
  type        = string
  default     = "dengbej-audio"
}

variable "lambda_function_name" {
  description = "Lambda function name"
  type        = string
  default     = "dengbej-summary"
}

variable "lambda_role_name" {
  description = "IAM role name for the Lambda function"
  type        = string
  default     = "dengbej-summary-role-c6jwhqf1"
}

# ─── News Ingestion Pipeline ─────────────────────────────────────────────────

variable "articles_table_name" {
  description = "DynamoDB table name for news articles"
  type        = string
  default     = "dengbej-articles"
}

variable "news_ingester_function_name" {
  description = "Lambda function name for news ingester"
  type        = string
  default     = "dengbej-ai-news-ingester"
}

# ─── Today's 5 Curation Pipeline ─────────────────────────────────────────────

variable "briefings_table_name" {
  description = "DynamoDB table name for daily briefings"
  type        = string
  default     = "dengbej-briefings"
}

variable "curator_function_name" {
  description = "Lambda function name for Today's 5 curator"
  type        = string
  default     = "dengbej-ai-todays-five-curator"
}

variable "bedrock_model_id" {
  description = "Bedrock model inference profile ID"
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

# ─── Today's 5 Processor Pipeline ────────────────────────────────────────────

variable "processor_function_name" {
  description = "Lambda function name for Today's 5 processor"
  type        = string
  default     = "dengbej-ai-todays-five-processor"
}

# ─── News API (Read-only public endpoint) ────────────────────────────────────

variable "news_api_function_name" {
  description = "Lambda function name for news API"
  type        = string
  default     = "dengbej-ai-news-api"
}

# ─── Daily Audio Script Generator ────────────────────────────────────────────

variable "daily_audio_function_name" {
  description = "Lambda function name for daily audio script generator"
  type        = string
  default     = "dengbej-ai-daily-audio"
}

# ─── Program Generator Pipeline ──────────────────────────────────────────────

variable "programs_table_name" {
  description = "DynamoDB table for program briefings"
  type        = string
  default     = "dengbej-programs"
}

variable "program_generator_function_name" {
  description = "Lambda function name for program generator"
  type        = string
  default     = "dengbej-ai-program-generator"
}
