import json
import boto3
import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# AWS clients
bedrock_runtime = boto3.client("bedrock-runtime")
polly_client = boto3.client("polly")
s3_client = boto3.client("s3")

# Config
S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "dengbej-audio")

# IMPORTANT: Must use inference profile
MODEL_ID = "us.anthropic.claude-3-5-haiku-20241022-v1:0"

MAX_ARTICLE_LENGTH = 8000


def lambda_handler(event, context):
    try:

        print("Incoming event:", event)

        # Accept both API Gateway and direct Lambda tests
        if "body" in event:
            body = json.loads(event["body"])
        else:
            body = event

        input_text = body.get("text", "")
        input_url = body.get("url", "")

        if input_url:
            print("Fetching article:", input_url)
            input_text = fetch_article_content(input_url)

        if not input_text:
            return create_response(400, {"error": "No text or URL provided"})

        print("Generating English summary")

        english_summary = generate_summary(input_text)

        print("Translating to Kurdish")

        kurdish_text = translate_to_kurdish(english_summary)

        print("Generating audio")

        audio_stream = synthesize_speech(english_summary)

        print("Uploading to S3")

        audio_url = upload_to_s3(audio_stream)

        return create_response(
            200,
            {
                "summary": english_summary,
                "kurdish_text": kurdish_text,
                "audio_url": audio_url,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    except Exception as e:

        print("ERROR:", str(e))

        return create_response(500, {"error": str(e)})


# ---------------------------------------------
# Fetch article text
# ---------------------------------------------
def fetch_article_content(url):

    try:

        headers = {"User-Agent": "Mozilla/5.0"}

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        paragraphs = soup.find_all("p")

        text_content = " ".join(
            [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
        )

        if len(text_content) > MAX_ARTICLE_LENGTH:
            text_content = text_content[:MAX_ARTICLE_LENGTH]

        if not text_content:
            raise Exception("No article text found")

        return text_content

    except Exception as e:

        raise Exception(f"Article extraction failed: {str(e)}")


# ---------------------------------------------
# Generate storytelling summary
# ---------------------------------------------
def generate_summary(text):

    prompt = f"""
You are a Kurdish dengbej storyteller.

Turn the following article into a short storytelling narrative that sounds like a traditional dengbej oral story.

Make it emotional and engaging.

Keep it 2 short paragraphs.

Article:
{text}

Story:
"""

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 500,
        "temperature": 0.7,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body),
    )

    response_body = json.loads(response["body"].read())

    return response_body["content"][0]["text"].strip()


# ---------------------------------------------
# Translate to Kurdish
# ---------------------------------------------
def translate_to_kurdish(text):

    prompt = f"""
Translate the following story into Kurdish Kurmanji.

Make it sound like a dengbej storytelling narration.

Keep poetic tone and emotion.

Story:
{text}

Kurdish Kurmanji Translation:
"""

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 800,
        "temperature": 0.7,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body),
    )

    response_body = json.loads(response["body"].read())

    return response_body["content"][0]["text"].strip()


# ---------------------------------------------
# Generate audio with Polly
# ---------------------------------------------
def synthesize_speech(text):

    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId="Joanna",
        Engine="neural",
    )

    return response["AudioStream"].read()


# ---------------------------------------------
# Upload audio to S3
# ---------------------------------------------
def upload_to_s3(audio_data):

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    filename = f"stories/dengbej_story_{timestamp}.mp3"

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=filename,
        Body=audio_data,
        ContentType="audio/mpeg",
    )

    return f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"


# ---------------------------------------------
# HTTP response helper
# ---------------------------------------------
def create_response(status_code, body):

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        
        },
        "body": json.dumps(body),
    }