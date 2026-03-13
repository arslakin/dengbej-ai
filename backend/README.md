# Dengbej AI Backend

AWS Lambda function that powers the Dengbej AI storytelling platform.

## Overview

This Lambda function orchestrates the AI storytelling pipeline:
1. Receives text input or article URL via HTTP POST
2. Fetches and extracts article content (if URL provided)
3. Generates an English story summary using Amazon Bedrock (Claude Haiku)
4. Translates the summary to Kurdish (Kurmanji dialect)
5. Converts the Kurdish text to speech using Amazon Polly
6. Stores the audio file in S3
7. Returns the English summary, Kurdish translation, and audio URL

## Requirements

- Python 3.11 or later
- AWS Lambda runtime
- IAM role with permissions for:
  - Amazon Bedrock (invoke model)
  - Amazon Polly (synthesize speech)
  - Amazon S3 (put object)

## Dependencies

- `boto3` - AWS SDK for Python
- `requests` - HTTP library for fetching articles
- `beautifulsoup4` - HTML parsing for article extraction

## Environment Variables

Configure these in your Lambda function:

- `AWS_REGION` - AWS region (default: us-east-1)
- `S3_BUCKET_NAME` - S3 bucket for audio storage (default: dengbej-ai-audio)

## Deployment

### Option 1: AWS Console

1. Create a new Lambda function
2. Select Python 3.11 runtime
3. Copy `lambda_function.py` code
4. Add environment variables
5. Configure IAM role with required permissions
6. Enable Function URL with CORS

### Option 2: AWS CLI

```bash
# Create deployment package
pip install -r requirements.txt -t package/
cp lambda_function.py package/
cd package
zip -r ../function.zip .
cd ..

# Deploy to Lambda
aws lambda create-function \
  --function-name dengbej-ai \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT:role/dengbej-lambda-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --environment Variables="{S3_BUCKET_NAME=your-bucket-name}"
```

## IAM Permissions

Required IAM policy for the Lambda execution role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-3-haiku-20240307-v1:0"
    },
    {
      "Effect": "Allow",
      "Action": [
        "polly:SynthesizeSpeech"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ],
      "Resource": "arn:aws:s3:::your-bucket-name/*"
    }
  ]
}
```

## API Endpoint

### POST Request

**Option 1: Text Input**
```bash
curl -X POST https://your-function-url.lambda-url.us-east-1.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{"text": "Your article text here..."}'
```

**Option 2: URL Input**
```bash
curl -X POST https://your-function-url.lambda-url.us-east-1.on.aws/ \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'
```

### Response

```json
{
  "summary": "English story summary...",
  "kurdish_text": "Kurdish (Kurmanji) translation...",
  "audio_url": "https://bucket.s3.amazonaws.com/stories/dengbej_story_20240312_103000.mp3",
  "timestamp": "2024-03-12T10:30:00.000000"
}
```

## Testing Locally

You can test the function locally using the AWS SAM CLI or by mocking the event:

```python
import json
from lambda_function import lambda_handler

event = {
    'body': json.dumps({
        'text': 'Your test article here...'
    })
}

result = lambda_handler(event, None)
print(json.dumps(result, indent=2))
```

## Configuration Options

### Voice Selection

Modify the `VoiceId` in `synthesize_speech()` function. Available neural voices:
- Joanna (US English, Female)
- Matthew (US English, Male)
- Amy (British English, Female)
- Brian (British English, Male)

### Model Selection

Change `MODEL_ID` to use different Bedrock models:
- `anthropic.claude-3-haiku-20240307-v1:0` (fast, cost-effective)
- `anthropic.claude-3-sonnet-20240229-v1:0` (balanced)
- `anthropic.claude-3-opus-20240229-v1:0` (most capable)

## Monitoring

View logs in CloudWatch:
```bash
aws logs tail /aws/lambda/dengbej-ai --follow
```

## Cost Optimization

- Bedrock Claude Haiku: ~$0.00025 per request
- Polly Neural: ~$0.016 per request (1000 characters)
- S3 Storage: ~$0.023 per GB/month
- Lambda: First 1M requests free

Estimated cost per story: $0.02-0.03
