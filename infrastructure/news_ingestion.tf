# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — News Ingestion Pipeline (Step 1)
#
# Resources:
#   - DynamoDB table for article metadata
#   - Lambda function for RSS feed ingestion
#   - EventBridge rule for scheduled execution
#   - IAM role with least-privilege permissions
# ─────────────────────────────────────────────────────────────────────────────

# ─── DynamoDB Table ──────────────────────────────────────────────────────────

resource "aws_dynamodb_table" "articles" {
  name         = var.articles_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "article_id"

  attribute {
    name = "article_id"
    type = "S"
  }

  tags = {
    Name    = "Dengbej AI Articles"
    Project = "dengbej-ai"
  }
}

# ─── IAM Role for News Ingester Lambda ───────────────────────────────────────

resource "aws_iam_role" "news_ingester_role" {
  name = "${var.project_name}-news-ingester-role"

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
    Name    = "Dengbej AI News Ingester Role"
    Project = "dengbej-ai"
  }
}

resource "aws_iam_role_policy" "news_ingester_policy" {
  name = "${var.project_name}-news-ingester-policy"
  role = aws_iam_role.news_ingester_role.id

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
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.news_ingester_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.articles.arn
      }
    ]
  })
}

# ─── Lambda Function for News Ingestion ──────────────────────────────────────

data "archive_file" "news_ingester_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/news_ingester"
  output_path = "${path.module}/news_ingester.zip"

  excludes = [
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "tests"
  ]
}

resource "aws_lambda_function" "news_ingester" {
  filename         = data.archive_file.news_ingester_zip.output_path
  function_name    = var.news_ingester_function_name
  role             = aws_iam_role.news_ingester_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.news_ingester_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 120
  memory_size      = 256

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.articles.name
    }
  }

  layers = [aws_lambda_layer_version.news_ingester_deps.arn]

  tags = {
    Name    = "Dengbej AI News Ingester"
    Project = "dengbej-ai"
  }
}

# ─── Lambda Layer for feedparser dependency ──────────────────────────────────

resource "aws_lambda_layer_version" "news_ingester_deps" {
  filename            = "${path.module}/news_ingester_layer.zip"
  layer_name          = "${var.project_name}-news-ingester-deps"
  compatible_runtimes = ["python3.11"]
  description         = "feedparser dependency for news ingester"
}

# ─── CloudWatch Log Group ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "news_ingester_logs" {
  name              = "/aws/lambda/${var.news_ingester_function_name}"
  retention_in_days = 14

  tags = {
    Name    = "Dengbej AI News Ingester Logs"
    Project = "dengbej-ai"
  }
}

# ─── EventBridge Scheduled Rule ──────────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "news_ingestion_schedule" {
  name                = "${var.project_name}-news-ingestion-schedule"
  description         = "Trigger news ingestion every 6 hours"
  schedule_expression = "rate(6 hours)"

  tags = {
    Name    = "Dengbej AI News Ingestion Schedule"
    Project = "dengbej-ai"
  }
}

resource "aws_cloudwatch_event_target" "news_ingestion_target" {
  rule = aws_cloudwatch_event_rule.news_ingestion_schedule.name
  arn  = aws_lambda_function.news_ingester.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.news_ingester.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.news_ingestion_schedule.arn
}
