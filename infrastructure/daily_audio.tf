# Dengbej AI — Daily Audio Script Generator
# Generates Kurdish broadcast script from Today's 5
# NO Polly. NO S3. TTS deferred until Kurdish provider available.

resource "aws_iam_role" "daily_audio_role" {
  name = "${var.project_name}-daily-audio-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = { Name = "Dengbej AI Daily Audio Role", Project = "dengbej-ai" }
}

resource "aws_iam_role_policy" "daily_audio_policy" {
  name = "${var.project_name}-daily-audio-policy"
  role = aws_iam_role.daily_audio_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.daily_audio_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = [
          aws_dynamodb_table.briefings.arn,
          "${aws_dynamodb_table.briefings.arn}/index/*",
          aws_dynamodb_table.programs.arn,
          "${aws_dynamodb_table.programs.arn}/index/*"
        ]
      },
      {
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}:*:inference-profile/${var.bedrock_model_id}",
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      }
    ]
  })
}

data "archive_file" "daily_audio_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/daily_audio"
  output_path = "${path.module}/daily_audio.zip"
  excludes    = ["__pycache__", "*.pyc", ".pytest_cache", "tests"]
}

resource "aws_lambda_function" "daily_audio" {
  filename         = data.archive_file.daily_audio_zip.output_path
  function_name    = var.daily_audio_function_name
  role             = aws_iam_role.daily_audio_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.daily_audio_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      BRIEFINGS_TABLE = aws_dynamodb_table.briefings.name
      PROGRAMS_TABLE  = aws_dynamodb_table.programs.name
      MODEL_ID        = var.bedrock_model_id
    }
  }
  tags = { Name = "Dengbej AI Daily Audio", Project = "dengbej-ai" }
}

resource "aws_cloudwatch_log_group" "daily_audio_logs" {
  name              = "/aws/lambda/${var.daily_audio_function_name}"
  retention_in_days = 14
  tags              = { Name = "Dengbej AI Daily Audio Logs", Project = "dengbej-ai" }
}
