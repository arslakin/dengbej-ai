# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — Today's 5 Curation Pipeline (Step 2a)
#
# Resources:
#   - DynamoDB table for daily briefings
#   - GSI on existing articles table for time-based queries
#   - Lambda function for curation
#   - EventBridge rule for scheduled curation (2x daily)
#   - IAM role with least-privilege permissions
# ─────────────────────────────────────────────────────────────────────────────

# ─── DynamoDB: Briefings Table ───────────────────────────────────────────────

resource "aws_dynamodb_table" "briefings" {
  name         = var.briefings_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "briefing_date"
  range_key    = "generated_at"

  attribute {
    name = "briefing_date"
    type = "S"
  }

  attribute {
    name = "generated_at"
    type = "S"
  }

  tags = {
    Name    = "Dengbej AI Briefings"
    Project = "dengbej-ai"
  }
}

# ─── IAM Role for Curator Lambda ─────────────────────────────────────────────

resource "aws_iam_role" "curator_role" {
  name = "${var.project_name}-curator-role"

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
    Name    = "Dengbej AI Curator Role"
    Project = "dengbej-ai"
  }
}

resource "aws_iam_role_policy" "curator_policy" {
  name = "${var.project_name}-curator-policy"
  role = aws_iam_role.curator_role.id

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
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.curator_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Scan",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.articles.arn,
          "${aws_dynamodb_table.articles.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.briefings.arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}:*:inference-profile/${var.bedrock_model_id}",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      }
    ]
  })
}

# ─── Lambda Function ─────────────────────────────────────────────────────────

data "archive_file" "curator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/todays_five_curator"
  output_path = "${path.module}/todays_five_curator.zip"

  excludes = [
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "tests"
  ]
}

resource "aws_lambda_function" "curator" {
  filename         = data.archive_file.curator_zip.output_path
  function_name    = var.curator_function_name
  role             = aws_iam_role.curator_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.curator_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 120
  memory_size      = 256

  environment {
    variables = {
      ARTICLES_TABLE  = aws_dynamodb_table.articles.name
      BRIEFINGS_TABLE = aws_dynamodb_table.briefings.name
      MODEL_ID        = var.bedrock_model_id
    }
  }

  tags = {
    Name    = "Dengbej AI Curator"
    Project = "dengbej-ai"
  }
}

# ─── CloudWatch Log Group ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "curator_logs" {
  name              = "/aws/lambda/${var.curator_function_name}"
  retention_in_days = 14

  tags = {
    Name    = "Dengbej AI Curator Logs"
    Project = "dengbej-ai"
  }
}

# ─── EventBridge Schedule (2x daily) ────────────────────────────────────────

resource "aws_cloudwatch_event_rule" "curation_schedule" {
  name                = "${var.project_name}-curation-schedule"
  description         = "Trigger Today's 5 curation twice daily"
  schedule_expression = "cron(0 6,18 * * ? *)"

  tags = {
    Name    = "Dengbej AI Curation Schedule"
    Project = "dengbej-ai"
  }
}

resource "aws_cloudwatch_event_target" "curation_target" {
  rule = aws_cloudwatch_event_rule.curation_schedule.name
  arn  = aws_lambda_function.curator.arn
}

resource "aws_lambda_permission" "allow_eventbridge_curator" {
  statement_id  = "AllowEventBridgeCurator"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.curator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.curation_schedule.arn
}
