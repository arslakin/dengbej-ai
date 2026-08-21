"""
Dengbej AI — API Lambda

Read-only API that returns processed articles from DynamoDB for the frontend.
Supports:
  - GET /  → returns latest processed articles (with audio_url)
  - GET /?status=pending → returns articles by processing status
  - GET /?limit=10 → limit number of results (default 20, max 50)

No authentication required (public demo).
"""

import json
import os
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError


# ─── Configuration ───────────────────────────────────────────────────────────

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "dengbej-articles")
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


# ─── AWS Clients ─────────────────────────────────────────────────────────────

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DYNAMODB_TABLE)


# ─── Main Handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Returns articles from DynamoDB, filtered by processing status.
    Designed to be called via Lambda Function URL (GET).
    """
    try:
        # Parse query parameters
        params = event.get("queryStringParameters") or {}
        status_filter = params.get("status", "completed")
        limit = min(int(params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)

        # Scan with filter (acceptable for demo scale < 1000 items)
        scan_kwargs = {
            "FilterExpression": Attr("processing_status").eq(status_filter),
            "Limit": limit * 3,  # Over-fetch to account for filter
        }

        response = table.scan(**scan_kwargs)
        articles = response.get("Items", [])

        # Sort by pub_date descending (newest first)
        articles.sort(
            key=lambda a: a.get("pub_date") or a.get("ingested_at") or "",
            reverse=True,
        )

        # Trim to requested limit
        articles = articles[:limit]

        # Clean up DynamoDB types for JSON serialization
        clean_articles = [clean_article(a) for a in articles]

        return create_response(200, {
            "articles": clean_articles,
            "count": len(clean_articles),
            "status_filter": status_filter,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    except ClientError as e:
        print(f"DynamoDB error: {e}")
        return create_response(500, {"error": "Database error"})
    except Exception as e:
        print(f"Unexpected error: {e}")
        return create_response(500, {"error": str(e)})


# ─── Helpers ─────────────────────────────────────────────────────────────────

def clean_article(article):
    """
    Clean a DynamoDB article item for frontend consumption.
    Ensures all expected fields exist and removes internal-only fields.
    """
    return {
        "article_id": article.get("article_id", ""),
        "headline": article.get("headline", ""),
        "source_name": article.get("source_name", ""),
        "original_url": article.get("original_url", ""),
        "pub_date": article.get("pub_date", ""),
        "feed_description": article.get("feed_description", ""),
        "image_url": article.get("image_url", ""),
        "story_ku": article.get("story_ku", ""),
        "story_en": article.get("story_en", ""),
        "audio_url": article.get("audio_url", ""),
        "processing_status": article.get("processing_status", "pending"),
        "processed_at": article.get("processed_at", ""),
    }


def create_response(status_code, body):
    """HTTP response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }
