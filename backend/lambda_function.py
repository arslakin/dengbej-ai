import json
import boto3
import os
from datetime import datetime
import hashlib

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
polly_client = boto3.client('polly', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Configuration
S3_BUCKET = os.environ.get('S3_BUCKET_NAME', 'dengbej-ai-audio')
MODEL_ID = 'anthropic.claude-3-haiku-20240307-v1:0'


def lambda_handler(event, context):
    """
    Main Lambda handler for Dengbej AI story generation
    """
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        input_text = body.get('text', '')
        
        if not input_text:
            return create_response(400, {'error': 'No text provided'})
        
        # Step 1: Generate story summary using Bedrock
        summary = generate_summary(input_text)
        
        # Step 2: Convert summary to speech using Polly
        audio_stream = synthesize_speech(summary)
        
        # Step 3: Upload audio to S3
        audio_url = upload_to_s3(audio_stream, summary)
        
        # Return response
        return create_response(200, {
            'summary': summary,
            'audio_url': audio_url,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return create_response(500, {'error': str(e)})


def generate_summary(text):
    """
    Generate a storytelling summary using Amazon Bedrock (Claude)
    """
    prompt = f"""Transform the following text into a compelling short story summary in the style of a dengbêj (Kurdish oral storyteller). 
Make it engaging, narrative-focused, and suitable for audio narration. Keep it concise (2-3 paragraphs).

Text:
{text}

Story Summary:"""
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "top_p": 0.9
    }
    
    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body)
    )
    
    response_body = json.loads(response['body'].read())
    summary = response_body['content'][0]['text'].strip()
    
    return summary


def synthesize_speech(text):
    """
    Convert text to speech using Amazon Polly
    """
    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat='mp3',
        VoiceId='Joanna',  # Neural voice
        Engine='neural',
        LanguageCode='en-US'
    )
    
    return response['AudioStream'].read()


def upload_to_s3(audio_data, summary):
    """
    Upload audio file to S3 and return public URL
    """
    # Generate unique filename based on content hash
    file_hash = hashlib.md5(summary.encode()).hexdigest()[:12]
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"stories/{timestamp}_{file_hash}.mp3"
    
    # Upload to S3
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=filename,
        Body=audio_data,
        ContentType='audio/mpeg',
        CacheControl='max-age=31536000'
    )
    
    # Generate public URL
    audio_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"
    
    return audio_url


def create_response(status_code, body):
    """
    Create HTTP response with CORS headers
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Methods': 'POST, OPTIONS'
        },
        'body': json.dumps(body)
    }
