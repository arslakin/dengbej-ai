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
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

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
        input_url  = body.get("url", "")
        languages  = body.get("languages", ["en"])
        dengbej_mode = body.get("dengbej_mode", False)

        if input_url:
            print("Fetching article:", input_url)
            input_text = fetch_article_content(input_url)

        if not input_text:
            return create_response(400, {"error": "No text or URL provided"})

        print(f"Generating English summary (dengbej_mode={dengbej_mode})")
        summary_en = generate_summary(input_text, dengbej_mode)

        response_body = {"summary_en": summary_en}

        if "ku" in languages:
            print("Translating to Kurdish")
            response_body["summary_ku"] = translate_text(summary_en, "Kurdish Kurmanji")

        if "tr" in languages:
            print("Translating to Turkish")
            response_body["summary_tr"] = translate_text(summary_en, "Turkish")

        print("Generating audio")
        audio_stream = synthesize_speech(summary_en)

        print("Uploading to S3")
        response_body["audio_url"] = upload_to_s3(audio_stream)
        response_body["timestamp"] = datetime.utcnow().isoformat()

        return create_response(200, response_body)

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
# Generate English summary (normal or dengbej mode)
# ---------------------------------------------
def generate_summary(text, dengbej_mode=False):

    if dengbej_mode:
        prompt = f"""You are a Kurdish dengbej storyteller.

Rewrite the following text in a poetic, emotional storytelling style inspired by the dengbej oral tradition.
Use vivid imagery, rhythm, and narrative flow. Keep it to 2 short paragraphs.

Text:
{text}

Dengbej Story:"""
    else:
        prompt = f"""Summarise the following text in clear, concise English.
Write 3 to 5 sentences. Be factual and easy to understand.

Text:
{text}

Summary:"""

    return invoke_bedrock(prompt, max_tokens=500)


# ---------------------------------------------
# Translate English text to a target language
# ---------------------------------------------
def translate_text(text, target_language):

    prompt = f"""Translate the following English text into {target_language}.
Keep the tone and meaning of the original. Return only the translation.

Text:
{text}

{target_language} Translation:"""

    return invoke_bedrock(prompt, max_tokens=800)


# ---------------------------------------------
# Shared Bedrock invocation helper
# ---------------------------------------------
def invoke_bedrock(prompt, max_tokens=500):

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "messages": [{"role": "user", "content": prompt}],
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