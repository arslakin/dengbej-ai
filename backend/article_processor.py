"""
Dengbej AI — Article Processor Lambda

Processes pending articles from DynamoDB:
  1. Scans for articles with processing_status = "pending"
  2. Fetches article content from the original URL
  3. Generates a Kurdish dengbêj-style story via Amazon Bedrock
  4. Generates audio narration via Amazon Polly
  5. Uploads audio to S3
  6. Updates DynamoDB with story text, audio URL, and status = "completed"

Designed to run on a schedule (EventBridge) after the news ingester populates
the articles table. Processes up to BATCH_SIZE articles per invocation to stay
within Lambda timeout.
"""

import json
import os
import hashlib
from datetime import datetime, timezone

import boto3
import requests
from bs4 import BeautifulSoup
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr


# ─── Configuration ───────────────────────────────────────────────────────────

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "dengbej-articles")
S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "dengbej-audio")
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5"))
MAX_ARTICLE_LENGTH = 6000


# ─── AWS Clients ─────────────────────────────────────────────────────────────

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DYNAMODB_TABLE)
bedrock_runtime = boto3.client("bedrock-runtime")
polly_client = boto3.client("polly")
s3_client = boto3.client("s3")


# ─── Main Handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Process a batch of pending articles through the AI pipeline.
    """
    stats = {
        "scanned": 0,
        "processed": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
    }

    # Fetch pending articles
    pending_articles = get_pending_articles()
    stats["scanned"] = len(pending_articles)

    print(f"Found {len(pending_articles)} pending articles to process")

    for article in pending_articles[:BATCH_SIZE]:
        article_id = article.get("article_id", "unknown")
        headline = article.get("headline", "")
        url = article.get("original_url", "")

        print(f"Processing: {headline[:60]}...")

        try:
            # Mark as processing to prevent duplicate work
            mark_processing(article_id)

            # Step 1: Get article content
            content = fetch_article_content(url, article.get("feed_description", ""))

            if not content or len(content.strip()) < 50:
                print(f"  Skipping — insufficient content for {article_id}")
                mark_status(article_id, "skipped")
                stats["skipped"] += 1
                continue

            # Step 2: Generate Kurdish dengbêj story
            story_ku = generate_kurdish_story(content, headline)

            # Step 3: Generate English summary for audio
            story_en = generate_english_summary(content, headline)

            # Step 4: Generate audio (English narration)
            audio_data = synthesize_speech(story_en)

            # Step 5: Upload audio to S3
            audio_url = upload_to_s3(audio_data, article_id)

            # Step 6: Update DynamoDB with results
            update_article(article_id, {
                "story_ku": story_ku,
                "story_en": story_en,
                "audio_url": audio_url,
                "processing_status": "completed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })

            stats["processed"] += 1
            print(f"  Completed: {headline[:60]}")

        except Exception as e:
            error_msg = f"Failed to process {article_id}: {str(e)}"
            print(f"  ERROR: {error_msg}")
            stats["errors"].append(error_msg)
            stats["failed"] += 1

            # Mark as failed so we can retry or skip later
            try:
                mark_status(article_id, "failed", error=str(e))
            except Exception:
                pass

    print(f"Processing complete: {json.dumps(stats)}")

    return {
        "statusCode": 200,
        "body": json.dumps(stats),
    }


# ─── DynamoDB Operations ─────────────────────────────────────────────────────

def get_pending_articles():
    """Scan for articles with processing_status = pending."""
    response = table.scan(
        FilterExpression=Attr("processing_status").eq("pending"),
        Limit=BATCH_SIZE * 3,  # Over-fetch to allow for filtering
    )
    return response.get("Items", [])


def mark_processing(article_id):
    """Mark article as currently being processed."""
    table.update_item(
        Key={"article_id": article_id},
        UpdateExpression="SET processing_status = :s",
        ExpressionAttributeValues={":s": "processing"},
    )


def mark_status(article_id, status, error=None):
    """Update article processing status."""
    update_expr = "SET processing_status = :s, processed_at = :t"
    expr_values = {
        ":s": status,
        ":t": datetime.now(timezone.utc).isoformat(),
    }

    if error:
        update_expr += ", processing_error = :e"
        expr_values[":e"] = error[:500]

    table.update_item(
        Key={"article_id": article_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )


def update_article(article_id, updates):
    """Update article with processing results."""
    update_parts = []
    expr_values = {}

    for key, value in updates.items():
        safe_key = key.replace("-", "_")
        update_parts.append(f"{key} = :{safe_key}")
        expr_values[f":{safe_key}"] = value

    update_expr = "SET " + ", ".join(update_parts)

    table.update_item(
        Key={"article_id": article_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )


# ─── Content Extraction ──────────────────────────────────────────────────────

def fetch_article_content(url, fallback_description=""):
    """
    Fetch and extract article text from URL.
    Falls back to feed description if fetching fails.
    """
    if not url:
        return fallback_description

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; DengbejAI/1.0; news-reader)"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script, style, nav, footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Extract article body or all paragraphs
        article = soup.find("article") or soup.find("main") or soup
        paragraphs = article.find_all("p")

        text = " ".join(
            p.get_text().strip() for p in paragraphs if p.get_text().strip()
        )

        if len(text) > MAX_ARTICLE_LENGTH:
            text = text[:MAX_ARTICLE_LENGTH]

        # Fall back to description if extraction yields too little
        if len(text.strip()) < 100:
            return fallback_description or text

        return text

    except Exception as e:
        print(f"  Article fetch failed ({e}), using feed description")
        return fallback_description


# ─── AI Generation (Bedrock) ─────────────────────────────────────────────────

def generate_kurdish_story(content, headline):
    """
    Generate a Kurdish dengbêj-style short story from article content.
    """
    prompt = f"""Tu dengbêjekî Kurd î. Ev nûçeyek e:

Sernav: {headline}

Naverok: {content[:3000]}

Ji kerema xwe vê nûçeyê bi şêwazê dengbêjî bi Kurdî (Kurmancî) binivîse.
Divê ew kurt be (2-3 paragraf), bi zimanekî xweş û poêtîk be, û wateyê nûçeyê bide.
Tenê nivîsa Kurdî binivîse, tu tiştek din nîne."""

    return invoke_bedrock(prompt, max_tokens=600)


def generate_english_summary(content, headline):
    """
    Generate a concise English summary for audio narration.
    """
    prompt = f"""Summarize this news article in 3–4 clear, engaging sentences suitable for audio narration.
Write in a warm, storytelling tone.

Headline: {headline}

Content: {content[:3000]}

Summary:"""

    return invoke_bedrock(prompt, max_tokens=300)


def invoke_bedrock(prompt, max_tokens=500):
    """Call Amazon Bedrock with Claude."""
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


# ─── Audio Generation (Polly) ────────────────────────────────────────────────

def synthesize_speech(text):
    """Generate MP3 audio from English text using Amazon Polly."""
    # Truncate if too long for Polly (3000 char limit for neural)
    if len(text) > 2900:
        text = text[:2900] + "."

    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId="Joanna",
        Engine="neural",
    )

    return response["AudioStream"].read()


# ─── S3 Upload ───────────────────────────────────────────────────────────────

def upload_to_s3(audio_data, article_id):
    """Upload audio to S3 and return public URL."""
    # Use a short hash for the filename to keep URLs clean
    short_id = article_id[:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"news/{short_id}_{timestamp}.mp3"

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=filename,
        Body=audio_data,
        ContentType="audio/mpeg",
    )

    return f"https://{S3_BUCKET}.s3.amazonaws.com/{filename}"
