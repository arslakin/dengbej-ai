# Dengbej AI — Program Generator
# Classifies articles and generates topic program briefings

resource "aws_dynamodb_table" "programs" {
  name         = var.programs_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "program_id"
  range_key    = "briefing_date"

  attribute {
    name = "program_id"
    type = "S"
  }
  attribute {
    name = "briefing_date"
    type = "S"
  }

  tags = { Name = "Dengbej AI Programs", Project = "dengbej-ai" }
}

resource "aws_iam_role" "program_generator_role" {
  name = "${var.project_name}-program-generator-role"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Action = "sts:AssumeRole", Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" } }]
  })
  tags = { Name = "Dengbej AI Program Generator Role", Project = "dengbej-ai" }
}

resource "aws_iam_role_policy" "program_generator_policy" {
  name = "${var.project_name}-program-generator-policy"
  role = aws_iam_role.program_generator_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.program_generator_function_name}:*" },
      { Effect = "Allow", Action = ["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem"], Resource = [aws_dynamodb_table.articles.arn, "${aws_dynamodb_table.articles.arn}/index/*"] },
      { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"], Resource = [aws_dynamodb_table.programs.arn, "${aws_dynamodb_table.programs.arn}/index/*"] },
      { Effect = "Allow", Action = ["bedrock:InvokeModel"], Resource = ["arn:aws:bedrock:${var.aws_region}:*:inference-profile/${var.bedrock_model_id}", "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"] }
    ]
  })
}

data "archive_file" "program_generator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend/program_generator"
  output_path = "${path.module}/program_generator.zip"
  excludes    = ["__pycache__", "*.pyc", ".pytest_cache", "tests"]
}

resource "aws_lambda_function" "program_generator" {
  filename         = data.archive_file.program_generator_zip.output_path
  function_name    = var.program_generator_function_name
  role             = aws_iam_role.program_generator_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.program_generator_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 180
  memory_size      = 256
  environment {
    variables = {
      ARTICLES_TABLE = aws_dynamodb_table.articles.name
      PROGRAMS_TABLE = aws_dynamodb_table.programs.name
      MODEL_ID       = var.bedrock_model_id
    }
  }
  tags = { Name = "Dengbej AI Program Generator", Project = "dengbej-ai" }
}

resource "aws_cloudwatch_log_group" "program_generator_logs" {
  name              = "/aws/lambda/${var.program_generator_function_name}"
  retention_in_days = 14
  tags              = { Name = "Dengbej AI Program Generator Logs", Project = "dengbej-ai" }
}
