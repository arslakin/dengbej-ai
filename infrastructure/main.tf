terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# ─────────────────────────────────────────────────────────────────────────────
# S3 Bucket for audio storage
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "audio_storage" {
  bucket = var.s3_bucket_name

  tags = {}
}

# S3 Bucket Public Access Configuration
resource "aws_s3_bucket_public_access_block" "audio_storage" {
  bucket = aws_s3_bucket.audio_storage.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# S3 Bucket Policy for public read access
resource "aws_s3_bucket_policy" "audio_storage" {
  bucket = aws_s3_bucket.audio_storage.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadAudioFiles"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.audio_storage.arn}/*"
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.audio_storage]
}

# NOTE: No S3 CORS configuration exists on the live bucket.
# Do not add one during reconciliation.

# ─────────────────────────────────────────────────────────────────────────────
# IAM Role for Lambda
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_iam_role" "lambda_role" {
  name = var.lambda_role_name
  path = "/service-role/"

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
}

# Inline policy: S3 upload only (matches existing DengbejS3Upload)
resource "aws_iam_role_policy" "lambda_s3_policy" {
  name = "DengbejS3Upload"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.audio_storage.arn,
          "${aws_s3_bucket.audio_storage.arn}/*"
        ]
      }
    ]
  })
}

# Managed policy attachments (matching current AWS state)
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::387276719593:policy/service-role/AWSLambdaBasicExecutionRole-b438d8f4-deab-4808-bec7-e57d2f7cbb29"
}

resource "aws_iam_role_policy_attachment" "lambda_polly_full" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonPollyFullAccess"
}

resource "aws_iam_role_policy_attachment" "lambda_bedrock_full" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
}

# ─────────────────────────────────────────────────────────────────────────────
# Lambda Function
# ─────────────────────────────────────────────────────────────────────────────

# Package Lambda function
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../backend"
  output_path = "${path.module}/lambda_function.zip"

  excludes = [
    "README.md",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "tests",
    "news_ingester"
  ]
}

# TODO: The dengbej-summary Lambda was originally deployed manually via the
# AWS Console. Terraform now manages its infrastructure configuration (role,
# timeout, memory, runtime, etc.) but application-code deployment remains
# intentionally protected by a lifecycle rule below.
#
# The ignore_changes on filename and source_code_hash prevents Terraform from
# overwriting the currently deployed Lambda package with the local zip. This is
# a temporary measure. Remove this lifecycle block when we deliberately migrate
# Lambda code deployment to Terraform or CI/CD, at which point the local code
# should match what we intend to deploy.
resource "aws_lambda_function" "dengbej_ai" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = var.lambda_function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.11"
  timeout          = 30
  memory_size      = 512
  architectures    = ["x86_64"]

  # NOTE: The existing Lambda has NO environment variables.
  # Do not add any during reconciliation.

  tags = {}

  lifecycle {
    # Temporary: Protect deployed application code from being overwritten.
    # Terraform still manages all other Lambda configuration attributes.
    ignore_changes = [filename, source_code_hash]
  }
}

# Lambda Function URL
resource "aws_lambda_function_url" "dengbej_ai" {
  function_name      = aws_lambda_function.dengbej_ai.function_name
  authorization_type = "NONE"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["POST"]
    allow_headers     = ["*"]
    expose_headers    = []
    max_age           = 300
  }
}

# ─────────────────────────────────────────────────────────────────────────────
# CloudWatch Log Group
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.lambda_function_name}"
  retention_in_days = 0 # Never expires (matches current AWS state)

  tags = {}
}
