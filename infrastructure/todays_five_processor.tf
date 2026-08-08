# ─────────────────────────────────────────────────────────────────────────────
# Dengbej AI — Today's 5 Processor Pipeline (Step 2b)
#
# Resources:
#   - Lambda function for processing (summarize + translate)
#   - IAM role with least-privilege permissions
#   - Lambda layer with requests + beautifulsoup4
#   - CloudWatch log group
#
# Permissions:
#   - DynamoDB: read+write dengbej-briefings, read dengbej-articles
#   - Bedrock: InvokeModel on inference profile + foundation model
#   - CloudWatch: logs
#
# NO Polly, NO S3, NO EventBridge schedule (manual invocation only)
# ─────────────────────────────────────────────────────────────────────────────

# ─── IAM Role for Processor Lambda ───────────────────────────────────────────

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
    Name    = "Dengbej AI Processor Role"
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
          "dynamodb:Query",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem"
        ]
        Resource = [
          aws_dynamodb_table.briefings.arn,
          "${aws_dynamodb_table.briefings.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem",
          "dynamodb:Scan"
        ]
        Resource = [
          aws_dynamodb_table.articles.arn,
          "${aws_dynamodb_table.articles.arn}/index/*"
        ]
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

# ─── Lambda Layer (requests + beautifulsoup4) ────────────────────────────────

resource "aws_lambda_layer_version" "processor_deps" {
  filename            = "${path.module}/processor_layer.zip"
  layer_name          = "${var.project_name}-processor-deps"
  compatible_runtimes = ["python3.11"]
  description         = "Dependencies for Today's 5 Processor: requests, beautifulsoup4"

  source_code_hash = filebase64sha256("${path.module}/processor_layer.zip")
}

# ─── Lambda Function ─────────────────────────────────────────────────────────

data "archive_file" "processor_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/todays_five_processor"
  output_path = "${path.module}/todays_five_processor.zip"

  excludes = [
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "tests"
  ]
}

resource "aws_lambda_function" "processor" {
  filename         = data.archive_file.processor_zip.output_path
  function_name    = var.processor_function_name
  role             = aws_iam_role.processor_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.processor_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 300
  memory_size      = 256

  layers = [aws_lambda_layer_version.processor_deps.arn]

  environment {
    variables = {
      BRIEFINGS_TABLE    = aws_dynamodb_table.briefings.name
      MODEL_ID           = var.bedrock_model_id
      MAX_ARTICLE_LENGTH = "4000"
    }
  }

  tags = {
    Name    = "Dengbej AI Processor"
    Project = "dengbej-ai"
  }
}

# ─── CloudWatch Log Group ────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "processor_logs" {
  name              = "/aws/lambda/${var.processor_function_name}"
  retention_in_days = 14

  tags = {
    Name    = "Dengbej AI Processor Logs"
    Project = "dengbej-ai"
  }
}
