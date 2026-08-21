# Dengbej AI Infrastructure

Terraform configuration for deploying the complete Dengbej AI infrastructure on AWS.

## What Gets Deployed

This Terraform configuration creates:

### Core Story Generator
- **S3 Bucket** — Audio file storage with public read access
- **Lambda: dengbej-summary** — Story generation backend (Bedrock + Polly + S3)
- **Lambda Function URL** — Public HTTPS endpoint with CORS
- **IAM Role & Policies** — Permissions for Bedrock, Polly, S3

### News Ingestion Pipeline
- **DynamoDB Table: dengbej-articles** — Article metadata storage
- **Lambda: dengbej-ai-news-ingester** — RSS feed fetcher (BBC, DW, Al Jazeera)
- **EventBridge Rule** — Triggers ingestion every 6 hours
- **Lambda Layer** — feedparser dependency

### Article Processor
- **Lambda: dengbej-ai-article-processor** — Processes pending articles through Bedrock (Kurdish story) + Polly (audio), uploads to S3, updates DynamoDB
- **EventBridge Rule** — Triggers 30 min after ingestion (cron offset)

### API Lambda
- **Lambda: dengbej-ai-api** — Read-only API returning processed articles for the frontend
- **Lambda Function URL** — Public GET endpoint with CORS

### Shared
- **CloudWatch Log Groups** — For all Lambdas (14-day retention)

## Prerequisites

1. **AWS Account** with access to:
   - Amazon Bedrock (Claude 3.5 Haiku model enabled)
   - AWS Lambda
   - Amazon Polly
   - Amazon S3
   - IAM

2. **Terraform** installed (v1.0+)
   ```bash
   # macOS
   brew install terraform
   
   # Or download from https://www.terraform.io/downloads
   ```

3. **AWS CLI** configured
   ```bash
   aws configure
   ```

4. **Enable Amazon Bedrock**
   - Go to AWS Console → Bedrock
   - Request access to Claude 3.5 Haiku model
   - Wait for approval (usually instant)

## Quick Start

### 1. Configure Variables

```bash
cd infrastructure
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` and set a unique S3 bucket name:
```hcl
s3_bucket_name = "dengbej-ai-audio-your-unique-name"
```

### 2. Initialize Terraform

```bash
terraform init
```

### 3. Review the Plan

```bash
terraform plan
```

### 4. Deploy Infrastructure

```bash
terraform apply
```

Type `yes` when prompted. Deployment takes 1-2 minutes.

### 5. Get Your API Endpoint

```bash
terraform output lambda_function_url
```

Copy this URL and update it in `frontend/index.html`.

## Configuration Options

### Custom AWS Region

```hcl
# terraform.tfvars
aws_region = "us-west-2"
```

### Different Environment

```hcl
# terraform.tfvars
environment = "dev"
```

### Custom Lambda Settings

Edit `main.tf` to adjust:
- Memory size (default: 512 MB)
- Timeout (default: 60 seconds)
- Runtime version
- Log retention (default: 7 days)

## Managing Infrastructure

### View Current State

```bash
terraform show
```

### View Outputs

```bash
terraform output
```

### Update Infrastructure

After making changes to `.tf` files:

```bash
terraform plan
terraform apply
```

### Destroy Infrastructure

To remove all resources:

```bash
terraform destroy
```

⚠️ This will delete the S3 bucket and all audio files!

## Cost Estimation

Approximate monthly costs (assuming 1000 stories/month):

- Lambda: ~$0.20 (first 1M requests free)
- Bedrock (Claude 3.5 Haiku): ~$0.25
- Polly: ~$16
- S3 Storage: ~$0.50 (for 20GB)
- S3 Requests: ~$0.01

**Total: ~$17/month** for 1000 stories

## Troubleshooting

### Bedrock Access Denied

Enable the Claude 3.5 Haiku model in AWS Bedrock console:
```bash
aws bedrock list-foundation-models --region us-east-1
```

### S3 Bucket Name Already Exists

S3 bucket names must be globally unique. Change `s3_bucket_name` in `terraform.tfvars`.

### Lambda Timeout

If stories are long, increase timeout in `main.tf`:
```hcl
timeout = 120  # 2 minutes
```

### View Lambda Logs

```bash
aws logs tail /aws/lambda/dengbej-ai-story-generator --follow
```

## Security Best Practices

1. **S3 Bucket** - Only audio files are public, not the bucket itself
2. **Lambda Function URL** - No authentication (public API)
3. **IAM Policies** - Least privilege access
4. **CORS** - Configured for web access

For production, consider:
- Adding API Gateway with rate limiting
- Implementing authentication (Cognito)
- Adding WAF rules
- Enabling S3 versioning and lifecycle policies

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy Infrastructure

on:
  push:
    branches: [main]
    paths:
      - 'infrastructure/**'

jobs:
  terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: hashicorp/setup-terraform@v2
      
      - name: Terraform Init
        run: terraform init
        working-directory: infrastructure
        
      - name: Terraform Apply
        run: terraform apply -auto-approve
        working-directory: infrastructure
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
```

## State Management

For team collaboration, use remote state:

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket = "your-terraform-state-bucket"
    key    = "dengbej-ai/terraform.tfstate"
    region = "us-east-1"
  }
}
```

## Additional Resources

- [Terraform AWS Provider Docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [AWS Lambda with Terraform](https://learn.hashicorp.com/tutorials/terraform/lambda-api-gateway)
- [Amazon Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
