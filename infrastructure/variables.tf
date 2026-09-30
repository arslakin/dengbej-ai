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

# ─── Events Table (News Presentation V2) ─────────────────────────────────────

variable "events_table_name" {
  description = "DynamoDB table for canonical news events"
  type        = string
  default     = "dengbej-events"
}

# ─────────────────────────────────────────────────────────────────────────────
# Production Hardening — Phase 1 feature flags (PLAN-ONLY)
#
# Every hardening resource below is DISABLED by default (flag = false ->
# count = 0). With all flags false, `terraform plan` adds/changes/destroys
# NOTHING. Each item is enabled deliberately, one small reviewed apply at a
# time, per the SAFE APPLY SEQUENCE in docs/production_infrastructure_plan.md.
#
# Nothing here modifies an existing resource; these are all additive.
# ─────────────────────────────────────────────────────────────────────────────

variable "enable_s3_audio_lifecycle" {
  description = "Phase 1: enable an S3 lifecycle rule that transitions old audio to cheaper storage (transition only; NO expiry/delete)."
  type        = bool
  default     = false
}

variable "s3_audio_transition_days" {
  description = "Days before audio objects transition to STANDARD_IA (no expiry/delete configured)."
  type        = number
  default     = 90
}

variable "manage_least_privilege_legacy_role" {
  description = "Phase 1: create a scoped Bedrock/Polly inline policy for the legacy summary role (to replace the Full-access managed policies in the same reviewed apply). Enable only after confirming the legacy Lambda's real usage."
  type        = bool
  default     = false
}

# NOTE: DynamoDB TTL on the articles table and a pub_date GSI are also Phase 1
# proposals, but they are IN-PLACE edits to the existing table block rather than
# standalone resources. They are specified in docs/production_infrastructure_plan.md
# and are applied by editing news_ingestion.tf in their own reviewed apply, not
# via a feature flag here (to avoid any chance of a table-diff while disabled).
