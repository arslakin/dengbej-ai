output "lambda_function_url" {
  description = "Lambda Function URL endpoint"
  value       = aws_lambda_function_url.dengbej_ai.function_url
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.dengbej_ai.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN"
  value       = aws_lambda_function.dengbej_ai.arn
}

output "s3_bucket_name" {
  description = "S3 bucket name for audio storage"
  value       = aws_s3_bucket.audio_storage.id
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.audio_storage.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.lambda_logs.name
}

# ─── News Ingestion Pipeline Outputs ─────────────────────────────────────────

output "articles_table_name" {
  description = "DynamoDB articles table name"
  value       = aws_dynamodb_table.articles.name
}

output "articles_table_arn" {
  description = "DynamoDB articles table ARN"
  value       = aws_dynamodb_table.articles.arn
}

output "news_ingester_function_name" {
  description = "News ingester Lambda function name"
  value       = aws_lambda_function.news_ingester.function_name
}

output "news_ingester_function_arn" {
  description = "News ingester Lambda function ARN"
  value       = aws_lambda_function.news_ingester.arn
}

# ─── Today's 5 Curation Outputs ──────────────────────────────────────────────

output "briefings_table_name" {
  description = "DynamoDB briefings table name"
  value       = aws_dynamodb_table.briefings.name
}

output "briefings_table_arn" {
  description = "DynamoDB briefings table ARN"
  value       = aws_dynamodb_table.briefings.arn
}

output "curator_function_name" {
  description = "Curator Lambda function name"
  value       = aws_lambda_function.curator.function_name
}

output "curator_function_arn" {
  description = "Curator Lambda function ARN"
  value       = aws_lambda_function.curator.arn
}

# ─── Today's 5 Processor Outputs ─────────────────────────────────────────────

output "processor_function_name" {
  description = "Processor Lambda function name"
  value       = aws_lambda_function.processor.function_name
}

output "processor_function_arn" {
  description = "Processor Lambda function ARN"
  value       = aws_lambda_function.processor.arn
}

# ─── News API Outputs ─────────────────────────────────────────────────────────

output "news_api_function_name" {
  description = "News API Lambda function name"
  value       = aws_lambda_function.news_api.function_name
}

output "news_api_function_url" {
  description = "News API public URL"
  value       = aws_lambda_function_url.news_api.function_url
}

# ─── Daily Audio Script Generator Outputs ─────────────────────────────────────

output "daily_audio_function_name" {
  description = "Daily audio script generator Lambda"
  value       = aws_lambda_function.daily_audio.function_name
}
