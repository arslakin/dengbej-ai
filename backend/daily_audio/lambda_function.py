"""
Dengbej AI — Daily Audio Script Generator

Generates ONE coherent Kurmanji Kurdish broadcast script from Today's 5.
Does NOT generate audio — TTS provider to be connected separately.

Pipeline:
  1. Retrieve latest processed Today's 5 briefing
  2. Check idempotency (skip if script already exists)
  3. Generate Kurdish broadcast script via Bedrock
  4. Store script + metadata in DynamoDB
  5. (Future) Pass script to TTS provider

The broadcast script is NOT a concatenation of summaries.
It is a coherent radio-style program with:
  - Opening greeting
  - Natural transitions between stories
  - Closing
"""

import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

# Configuration
BRIEFINGS_TABLE = os.environ.get("BRIEFINGS_TABLE", "dengbej-briefings")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# AWS Clients
dynamodb = boto3.resource("dynamodb")
briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
bedrock_runtime = boto3.client("bedrock-runtime")


class Telemetry:
    def __init__(self):
        self.bedrock_calls = 0
        self.bedrock_input_tokens = 0
        self.bedrock_output_tokens = 0
        self.start_time = time.time()
        self.duration_ms = 0
        self.script_chars = 0

    def finish(self):
        self.duration_ms = int((time.time() - self.start_time) * 1000)

    def to_dict(self):
        return {
            "bedrock_calls": self.bedrock_calls,
            "bedrock_input_tokens": self.bedrock_input_tokens,
            "bedrock_output_tokens": self.bedrock_output_tokens,
            "script_chars": self.script_chars,
            "duration_ms": self.duration_ms,
        }


def lambda_handler(event, context):
    """Generate daily Kurdish broadcast script from Today's 5."""
    telemetry = Telemetry()

    target_date = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    force = event.get("force", False)

    print(f"Daily audio script generation for: {target_date} (force={force})")

    # Get the latest processed briefing
    briefing = get_processed_briefing(target_date)
    if not briefing:
        telemetry.finish()
        return {"statusCode": 404, "body": {"error": f"No processed briefing for {target_date}", "telemetry": telemetry.to_dict()}}

    stories = briefing.get("stories", [])
    processed_stories = [s for s in stories if s.get("processing_status") == "processed"]

    if len(processed_stories) < 3:
        telemetry.finish()
        return {"statusCode": 400, "body": {"error": "Insufficient processed stories (need at least 3)", "telemetry": telemetry.to_dict()}}

    # Idempotency check
    existing_script = briefing.get("daily_audio_script_ku")
    if existing_script and not force:
        print("Script already exists, skipping generation")
        telemetry.finish()
        return {"statusCode": 200, "body": {
            "status": "already_exists",
            "briefing_date": target_date,
            "script_length": len(existing_script),
            "telemetry": telemetry.to_dict(),
        }}

    # Generate the broadcast script
    script = generate_broadcast_script(processed_stories, target_date, telemetry)
    if not script:
        telemetry.finish()
        return {"statusCode": 500, "body": {"error": "Script generation failed", "telemetry": telemetry.to_dict()}}

    telemetry.script_chars = len(script)

    # Store script in DynamoDB
    store_script(briefing, script, target_date, telemetry)

    telemetry.finish()
    print(f"Telemetry: {json.dumps(telemetry.to_dict())}")

    return {"statusCode": 200, "body": {
        "status": "generated",
        "briefing_date": target_date,
        "script_length": len(script),
        "story_count": len(processed_stories),
        "telemetry": telemetry.to_dict(),
    }}


def get_processed_briefing(date_str):
    """Get the latest briefing with processed stories."""
    try:
        response = briefings_table.query(
            KeyConditionExpression="briefing_date = :bd",
            ExpressionAttributeValues={":bd": date_str},
            ScanIndexForward=False,
            Limit=5,
        )
        for item in response.get("Items", []):
            stories = item.get("stories", [])
            processed = [s for s in stories if s.get("processing_status") == "processed"]
            if processed:
                return item
        return None
    except ClientError as e:
        print(f"DynamoDB error: {e}")
        return None


def generate_broadcast_script(stories, date_str, telemetry):
    """Generate a coherent Kurdish broadcast script from processed stories."""

    # Build story summaries for the prompt
    story_blocks = []
    for i, story in enumerate(stories, 1):
        block = f"""Story {i}:
Headline: {story.get('headline', '')}
Category: {story.get('category', '')}
Summary (Kurdish): {story.get('summary_ku', story.get('summary_en', ''))}
Source: {story.get('primary_source', '')}"""
        story_blocks.append(block)

    stories_text = "\n\n".join(story_blocks)

    prompt = f"""You are preparing a Kurdish-language (Kurmanji) daily news briefing for Dengbej, a Kurdish news audio service.

STRICT RULES:
- Use ONLY information contained in the supplied stories below
- Do NOT invent facts, quotes, statistics, or analysis not present in the source material
- Do NOT add commentary or opinion beyond what the sources report
- Do NOT present Dengbej as a human journalist or reporter
- Use calm, natural radio-style Kurmanji Kurdish
- Preserve important names, places, dates, and numbers accurately
- When sources express uncertainty, reflect that uncertainty
- Avoid sensational language

STRUCTURE:
1. Brief opening: "Rojbaş. Ev Dengbej e. Nûçeyên îro, {date_str}."
2. Story 1 — the most important story, told naturally
3. Brief transition to Story 2
4. Story 2
5. Brief transition to Story 3
6. Story 3
7. Brief transition to Story 4
8. Story 4
9. Brief transition to Story 5
10. Story 5
11. Brief closing: "Ev bû Dengbej. Soz didin ku sibehê jî li gel we bin."

STYLE:
- Natural spoken Kurmanji — as if reading aloud on radio
- Vary sentence length for natural rhythm
- Do NOT use identical transition phrases for each story
- Do NOT include stage directions, speaker labels, or formatting
- Output ONLY the text that would be spoken aloud
- Target approximately 800-1200 words total

TODAY'S STORIES:

{stories_text}

KURDISH BROADCAST SCRIPT:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=3000, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"Broadcast script generation failed: {e}")
        return None


def store_script(briefing, script, date_str, telemetry):
    """Store the broadcast script and metadata in the briefing record."""
    try:
        generated_at = briefing.get("generated_at", "")
        now_iso = datetime.now(timezone.utc).isoformat()

        briefings_table.update_item(
            Key={"briefing_date": date_str, "generated_at": generated_at},
            UpdateExpression="SET daily_audio_script_ku = :script, daily_audio_meta = :meta",
            ExpressionAttributeValues={
                ":script": script,
                ":meta": {
                    "script_generated_at": now_iso,
                    "model_id": MODEL_ID,
                    "script_chars": len(script),
                    "tts_status": "pending",
                    "tts_provider": None,
                    "audio_url": None,
                    "audio_duration_seconds": None,
                    "bedrock_input_tokens": telemetry.bedrock_input_tokens,
                    "bedrock_output_tokens": telemetry.bedrock_output_tokens,
                },
            },
        )
        print(f"Script stored for {date_str} ({len(script)} chars)")
    except ClientError as e:
        print(f"Failed to store script: {e}")
        raise


def invoke_bedrock(prompt, max_tokens=3000, telemetry=None):
    """Invoke Bedrock and track usage."""
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.4,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body),
    )

    response_body = json.loads(response["body"].read())

    if telemetry:
        telemetry.bedrock_calls += 1
        usage = response_body.get("usage", {})
        telemetry.bedrock_input_tokens += usage.get("input_tokens", 0)
        telemetry.bedrock_output_tokens += usage.get("output_tokens", 0)

    return response_body["content"][0]["text"].strip()
