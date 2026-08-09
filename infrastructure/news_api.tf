# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — News API (Read-only public endpoint)
#
# No Bedrock. No Polly. No S3. No article processing.
# This Lambda only READS from dengbej-briefings.
# ─────────────────────────────────────────────────────────────────────────────

# ─── IAM Role ────────────────────────────────────────────────────────────────

resource "aws_iam_role" "news_api_role" {
  name = "${var.project_name}-news-api-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = {
    Name    = "Dengbej AI News API Role"
    Project = "dengbej-ai"
  }
}

resource "aws_iam_role_policy" "news_api_policy" {
  name = "${var.project_name}-news-api-policy"
  role = aws_iam_role.news_api_role.id

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
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.news_api_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem"
        ]
        Resource = [
          aws_dynamodb_table.briefings.arn,
          "${aws_dynamodb_table.briefings.arn}/index/*"
        ]
      }
    ]
  })
}

# ─── Lambda Function ─────────────────────────────────────────────────────────

data "archive_file" "news_api_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/news_api"
  output_path = "${path.module}/news_api.zip"

  excludes = [
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "tests"
  ]
}

resource "aws_lambda_function" "news_api" {
  filename         = data.archive_file.news_api_zip.output_path
  function_name    = var.news_api_function_name
  role             = aws_iam_role.news_api_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.news_api_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      BRIEFINGS_TABLE = aws_dynamodb_table.briefings.name
    }
  }

  tags = {
    Name    = "Dengbej AI News API"
    Project = "dengbej-ai"
  }
}

# ─── Function URL (Public, no auth) ─────────────────────────────────────────

resource "aws_lambda_function_url" "news_api" {
  function_name      = aws_lambda_function.news_api.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["GET"]
    allow_headers     = ["content-type"]
    expose_headers    = []
    max_age           = 86400
  }
}

resource "aws_lambda_permission" "news_api_public" {
  statement_id           = "AllowPublicFunctionURL"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.news_api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# ─── CloudWatch Log Group ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "news_api_logs" {
  name              = "/aws/lambda/${var.news_api_function_name}"
  retention_in_days = 14

  tags = {
    Name    = "Dengbej AI News API Logs"
    Project = "dengbej-ai"
  }
}
