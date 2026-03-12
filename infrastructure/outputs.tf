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
