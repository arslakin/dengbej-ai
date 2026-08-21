# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — API Lambda + Article Processor
#
# Resources:
#   - API Lambda (read-only, serves frontend with processed articles)
#   - Article Processor Lambda (batch processes pending → completed)
#   - EventBridge rule to trigger processor after ingestion
#   - IAM roles with least-privilege permissions
# ─────────────────────────────────────────────────────────────────────────────

# ─── Variables ───────────────────────────────────────────────────────────────

variable "api_function_name" {
  description = "Lambda function name for the API"
  type        = string
  default     = "dengbej-ai-api"
}

variable "processor_function_name" {
  description = "Lambda function name for the article processor"
  type        = string
  default     = "dengbej-ai-article-processor"
}

# ═══════════════════════════════════════════════════════════════════════════════
# API LAMBDA — serves processed articles to the frontend
# ═══════════════════════════════════════════════════════════════════════════════

# ─── IAM Role ────────────────────────────────────────────────────────────────

resource "aws_iam_role" "api_role" {
  name = "${var.project_name}-api-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project = "dengbej-ai"
  }
}

resource "aws_iam_role_policy" "api_policy" {
  name = "${var.project_name}-api-policy"
  role = aws_iam_role.api_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.api_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Scan",
          "dynamodb:Query",
          "dynamodb:GetItem"
        ]
        Resource = aws_dynamodb_table.articles.arn
      }
    ]
  })
}

# ─── Lambda Function ─────────────────────────────────────────────────────────

data "archive_file" "api_zip" {
  type        = "zip"
  source_file = "${path.module}/../backend/api_function.py"
  output_path = "${path.module}/api_function.zip"
}

resource "aws_lambda_function" "api" {
  filename         = data.archive_file.api_zip.output_path
  function_name    = var.api_function_name
  role             = aws_iam_role.api_role.arn
  handler          = "api_function.lambda_handler"
  source_code_hash = data.archive_file.api_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 15
  memory_size      = 256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.articles.name
    }
  }

  tags = {
    Name    = "Dengbej AI API"
    Project = "dengbej-ai"
  }
}

# ─── Lambda Function URL (public, read-only) ────────────────────────────────

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["GET", "OPTIONS"]
    allow_headers     = ["*"]
    expose_headers    = []
    max_age           = 300
  }
}

# ─── CloudWatch Log Group ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/lambda/${var.api_function_name}"
  retention_in_days = 14

  tags = {
    Project = "dengbej-ai"
  }
}

# ═══════════════════════════════════════════════════════════════════════════════
# ARTICLE PROCESSOR LAMBDA — processes pending articles through Bedrock + Polly
# ═══════════════════════════════════════════════════════════════════════════════

# ─── IAM Role ────────────────────────────────────────────────────────────────

resource "aws_iam_role" "processor_role" {
  name = "${var.project_name}-processor-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project = "dengbej-ai"
  }
}

resource "aws_iam_role_policy" "processor_policy" {
  name = "${var.project_name}-processor-policy"
  role = aws_iam_role.processor_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.processor_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Scan",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Resource = aws_dynamodb_table.articles.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = "${aws_s3_bucket.audio_storage.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "polly:SynthesizeSpeech"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "*"
      }
    ]
  })
}

# ─── Lambda Function ─────────────────────────────────────────────────────────

data "archive_file" "processor_zip" {
  type        = "zip"
  source_file = "${path.module}/../backend/article_processor.py"
  output_path = "${path.module}/article_processor.zip"
}

resource "aws_lambda_function" "processor" {
  filename         = data.archive_file.processor_zip.output_path
  function_name    = var.processor_function_name
  role             = aws_iam_role.processor_role.arn
  handler          = "article_processor.lambda_handler"
  source_code_hash = data.archive_file.processor_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 512

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.articles.name
      S3_BUCKET_NAME = aws_s3_bucket.audio_storage.id
      BATCH_SIZE     = "5"
    }
  }

  # Processor needs requests + beautifulsoup4 (same layer as main Lambda)
  layers = [aws_lambda_layer_version.news_ingester_deps.arn]

  tags = {
    Name    = "Dengbej AI Article Processor"
    Project = "dengbej-ai"
  }
}

# ─── CloudWatch Log Group ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "processor_logs" {
  name              = "/aws/lambda/${var.processor_function_name}"
  retention_in_days = 14

  tags = {
    Project = "dengbej-ai"
  }
}

# ─── EventBridge: Trigger processor 30 minutes after ingestion ───────────────

resource "aws_cloudwatch_event_rule" "processor_schedule" {
  name                = "${var.project_name}-processor-schedule"
  description         = "Trigger article processor every 6 hours (30 min after ingestion)"
  schedule_expression = "cron(30 0/6 * * ? *)"

  tags = {
    Project = "dengbej-ai"
  }
}

resource "aws_cloudwatch_event_target" "processor_target" {
  rule = aws_cloudwatch_event_rule.processor_schedule.name
  arn  = aws_lambda_function.processor.arn
}

resource "aws_lambda_permission" "allow_eventbridge_processor" {
  statement_id  = "AllowEventBridgeInvokeProcessor"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.processor.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.processor_schedule.arn
}

# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUTS
# ═══════════════════════════════════════════════════════════════════════════════

output "api_function_url" {
  description = "API Lambda Function URL (public, read-only)"
  value       = aws_lambda_function_url.api.function_url
}

output "api_function_name" {
  description = "API Lambda function name"
  value       = aws_lambda_function.api.function_name
}

output "processor_function_name" {
  description = "Article Processor Lambda function name"
  value       = aws_lambda_function.processor.function_name
}

output "processor_function_arn" {
  description = "Article Processor Lambda ARN"
  value       = aws_lambda_function.processor.arn
}
