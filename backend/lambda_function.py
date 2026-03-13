import json
import boto3
import os
from datetime import datetime
import hashlib
import requests
from bs4 import BeautifulSoup

# Initialize AWS clients
bedrock_runtime = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
polly_client = boto3.client('polly', region_name=os.environ.get('AWS_REGION', 'us-east-1'))
s3_client = boto3.client('s3', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

# Configuration
S3_BUCKET = os.environ.get('S3_BUCKET_NAME', 'dengbej-ai-audio')
MODEL_ID = 'anthropic.claude-3-5-haiku-20241022-v1:0'
MAX_ARTICLE_LENGTH = 8000


def lambda_handler(event, context):
    """
    Main Lambda handler for Dengbej AI story generation
    """
    try:
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        input_text = body.get('text', '')
        input_url = body.get('url', '')
        
        # Determine input source
        if input_url:
            print(f"Fetching article from URL: {input_url}")
            input_text = fetch_article_content(input_url)
        elif not input_text:
            return create_response(400, {'error': 'No text or URL provided'})
        
        # Step 1: Generate English story summary using Bedrock
        english_summary = generate_summary(input_text)
        
        # Step 2: Translate summary to Kurdish (Kurmanji)
        kurdish_text = translate_to_kurdish(english_summary)
        
        # Step 3: Convert Kurdish text to speech using Polly
        audio_stream = synthesize_speech(kurdish_text)
        
        # Step 4: Upload audio to S3
        audio_url = upload_to_s3(audio_stream)
        
        # Return response
        return create_response(200, {
            'summary': english_summary,
            'kurdish_text': kurdish_text,
            'audio_url': audio_url,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return create_response(500, {'error': str(e)})


def fetch_article_content(url):
    """
    Fetch and extract text content from a URL
    """
    try:
        # Set headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Fetch the webpage
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract text from paragraph tags
        paragraphs = soup.find_all('p')
        text_content = ' '.join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
        
        # Limit to max length
        if len(text_content) > MAX_ARTICLE_LENGTH:
            text_content = text_content[:MAX_ARTICLE_LENGTH]
        
        if not text_content:
            raise ValueError("No text content found in the article")
        
        return text_content
        
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch article: {str(e)}")
    except Exception as e:
        raise Exception(f"Failed to parse article: {str(e)}")


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


def translate_to_kurdish(text):
    """
    Translate English text to Kurdish (Kurmanji dialect) using Amazon Bedrock
    """
    prompt = f"""Translate the following story into Kurdish (Kurmanji dialect). 
Maintain a storytelling tone similar to a traditional dengbêj narration. 
Keep the emotional depth and narrative flow of the original text.

English Story:
{text}

Kurdish (Kurmanji) Translation:"""
    
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 800,
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
    kurdish_text = response_body['content'][0]['text'].strip()
    
    return kurdish_text


def synthesize_speech(text):
    """
    Convert text to speech using Amazon Polly
    Note: Polly doesn't have native Kurdish support, so we use a neutral voice
    """
    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat='mp3',
        VoiceId='Joanna',  # Neural voice - neutral for Kurdish text
        Engine='neural',
        LanguageCode='en-US'
    )
    
    return response['AudioStream'].read()


def upload_to_s3(audio_data):
    """
    Upload audio file to S3 and return public URL
    """
    # Generate unique filename with timestamp
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"stories/dengbej_story_{timestamp}.mp3"
    
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
