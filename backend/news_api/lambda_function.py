"""
Dengbej AI — News API Lambda

Read-only public API for the Dengbej News frontend.
Returns processed Today's 5 briefings from DynamoDB.

No Bedrock. No Polly. No S3 writes. No article processing.
This Lambda only READS from dengbej-briefings.
"""

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

BRIEFINGS_TABLE = os.environ.get("BRIEFINGS_TABLE", "dengbej-briefings")
PROGRAMS_TABLE = os.environ.get("PROGRAMS_TABLE", "dengbej-programs")

dynamodb = boto3.resource("dynamodb")
briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
programs_table_resource = dynamodb.Table(PROGRAMS_TABLE)


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def lambda_handler(event, context):
    """Route requests to appropriate handler."""
    path = event.get("rawPath", event.get("path", "/"))
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")

    # CORS preflight
    if method == "OPTIONS":
        return cors_response(200, "")

    if method != "GET":
        return cors_response(405, {"error": "Method not allowed"})

    # Routing
    if path == "/news/today":
        return handle_today()

    # Match /news/program/{id}
    program_match = re.match(r'^/news/program/([a-z0-9-]+)$', path)
    if program_match:
        return handle_program(program_match.group(1))

    # Match /news/YYYY-MM-DD
    date_match = re.match(r'^/news/(\d{4}-\d{2}-\d{2})$', path)
    if date_match:
        return handle_date(date_match.group(1))

    return cors_response(404, {"error": "Not found"})


def handle_today():
    """Return today's briefing (or most recent available)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    briefing = get_processed_briefing(today)

    if not briefing:
        # Try yesterday if today's isn't ready yet
        from datetime import timedelta
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        briefing = get_processed_briefing(yesterday)

    if not briefing:
        return cors_response(404, {"error": "No briefing available", "date": today})

    return cors_response(200, format_briefing(briefing))


def handle_date(date_str):
    """Return briefing for specific date."""
    briefing = get_processed_briefing(date_str)
    if not briefing:
        return cors_response(404, {"error": "No briefing available", "date": date_str})
    return cors_response(200, format_briefing(briefing))


def handle_program(program_id):
    """Return latest program briefing."""
    from datetime import timedelta
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Try today, then yesterday
    for date in [today, (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")]:
        try:
            response = programs_table_resource.get_item(
                Key={"program_id": program_id, "briefing_date": date}
            )
            item = response.get("Item")
            if item and item.get("story_count", 0) > 0:
                return cors_response(200, format_program(item))
        except ClientError:
            pass

    # Return empty program
    return cors_response(200, {
        "program_id": program_id,
        "label_ku": "",
        "label_en": "",
        "generated_at": None,
        "story_count": 0,
        "stories": [],
        "message": "No stories available for this program right now."
    })


def format_program(item):
    """Format program briefing for API response."""
    stories = item.get("stories", [])
    formatted = []
    for i, story in enumerate(stories):
        formatted.append({
            "rank": i + 1,
            "headline": story.get("headline"),
            "category": story.get("category"),
            "primary_source": {"name": story.get("primary_source", ""), "url": story.get("original_url", "")},
            "supporting_sources": [{"name": s.get("source_name", ""), "url": s.get("url", "")} for s in story.get("supporting_sources", [])],
            "published_at": story.get("pub_date"),
            "feed_description": story.get("feed_description"),
        })

    # Script and audio metadata
    script_ku = item.get("script_ku")
    audio_url = item.get("audio_url")

    return {
        "program_id": item.get("program_id"),
        "label_ku": item.get("label_ku", ""),
        "label_en": item.get("label_en", ""),
        "generated_at": item.get("generated_at"),
        "story_count": len(formatted),
        "stories": formatted,
        "script_ku": script_ku if script_ku else None,
        "audio": {
            "available": bool(audio_url),
            "url": audio_url,
        },
    }


def get_processed_briefing(date_str):
    """Query DynamoDB for the latest briefing on this date with processed stories."""
    try:
        response = briefings_table.query(
            KeyConditionExpression="briefing_date = :bd",
            ExpressionAttributeValues={":bd": date_str},
            ScanIndexForward=False,
            Limit=5,
        )
        items = response.get("Items", [])

        # Find the most recent briefing that has at least one processed story
        for item in items:
            stories = item.get("stories", [])
            processed = [s for s in stories if s.get("processing_status") == "processed"]
            if processed:
                return item

        return None
    except ClientError as e:
        print(f"DynamoDB error: {e}")
        return None


def format_briefing(briefing):
    """Transform DynamoDB briefing into clean public API response."""
    stories = briefing.get("stories", [])

    # Filter to only processed stories, sort by rank
    processed_stories = sorted(
        [s for s in stories if s.get("processing_status") == "processed"],
        key=lambda s: s.get("rank", 99)
    )

    formatted_stories = []
    for story in processed_stories:
        supporting = []
        for src in story.get("supporting_sources", []):
            if src.get("source_name") and src.get("url"):
                supporting.append({
                    "name": src["source_name"],
                    "url": src["url"],
                })

        formatted_stories.append({
            "rank": story.get("rank"),
            "headline": story.get("headline"),
            "category": story.get("category"),
            "summary_en": story.get("summary_en"),
            "summary_ku": story.get("summary_ku"),
            "primary_source": {
                "name": story.get("primary_source"),
                "url": story.get("original_url"),
            },
            "supporting_sources": supporting,
            "published_at": story.get("pub_date"),
            "processed_at": story.get("processed_at"),
        })

    # Daily audio metadata
    daily_audio_meta = briefing.get("daily_audio_meta", {})
    script_exists = bool(briefing.get("daily_audio_script_ku"))
    audio_url = daily_audio_meta.get("audio_url") if daily_audio_meta else None

    daily_audio = {
        "available": bool(audio_url),
        "script_available": script_exists,
        "language": "ku",
        "url": audio_url,
        "duration_seconds": daily_audio_meta.get("audio_duration_seconds") if daily_audio_meta else None,
        "generated_at": daily_audio_meta.get("script_generated_at") if daily_audio_meta else None,
    }

    return {
        "date": briefing.get("briefing_date"),
        "generated_at": briefing.get("generated_at"),
        "edition": "today",
        "story_count": len(formatted_stories),
        "stories": formatted_stories,
        "daily_audio": daily_audio,
    }


def cors_response(status_code, body):
    """Return response with appropriate headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=300",
        },
        "body": json.dumps(body, cls=DecimalEncoder) if isinstance(body, dict) else body,
    }
