"""
Dengbej AI — News Ingestion Lambda

Fetches RSS/Atom feeds from configured sources and stores article metadata
in DynamoDB. Does NOT fetch full article bodies or perform any AI processing.

Deduplication: article_id is a SHA-256 hash of the canonical article URL.
DynamoDB's PutItem with ConditionExpression prevents duplicate writes.
"""

import json
import os
import hashlib
from datetime import datetime, timezone

import boto3
import feedparser
from botocore.exceptions import ClientError


# ─── Configuration ───────────────────────────────────────────────────────────

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "dengbej-articles")
FEEDS_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "feeds_config.json")


# ─── AWS Clients ─────────────────────────────────────────────────────────────

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DYNAMODB_TABLE)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_feeds_config():
    """Load feed sources from the configuration file."""
    with open(FEEDS_CONFIG_PATH, "r") as f:
        config = json.load(f)
    return [feed for feed in config["feeds"] if feed.get("enabled", True)]


def generate_article_id(url):
    """Deterministic article ID: SHA-256 of the canonical URL."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def parse_pub_date(entry):
    """Extract publication date as ISO 8601 string from a feed entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        from time import mktime
        dt = datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
        return dt.isoformat()
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        from time import mktime
        dt = datetime.fromtimestamp(mktime(entry.updated_parsed), tz=timezone.utc)
        return dt.isoformat()
    return None


def store_article(article):
    """
    Store article metadata in DynamoDB.
    Uses a condition expression to skip if the article_id already exists (dedup).
    Returns True if stored, False if duplicate.
    """
    try:
        table.put_item(
            Item=article,
            ConditionExpression="attribute_not_exists(article_id)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False  # Duplicate — already exists
        raise


# ─── Image Extraction ────────────────────────────────────────────────────────

def extract_source_image_url(entry):
    """
    Extract source image URL from RSS entry using priority chain:
    1. media:content with medium="image" or no medium attribute
    2. media:thumbnail
    3. enclosure with type starting with "image/"
    4. null (no image available)

    Validation: URL must be absolute http/https, max 2048 chars.
    No downloading. No scraping. No rehosting.
    """
    # Priority 1: media:content (medium="image" or unspecified medium)
    media_contents = entry.get("media_content", [])
    for media in media_contents:
        medium = media.get("medium", "")
        url = media.get("url", "").strip()
        if medium in ("image", ""):
            if _is_valid_image_url(url):
                return url

    # Priority 2: media:thumbnail
    media_thumbnails = entry.get("media_thumbnail", [])
    for thumb in media_thumbnails:
        url = thumb.get("url", "").strip()
        if _is_valid_image_url(url):
            return url

    # Priority 3: enclosure with image MIME type
    enclosures = entry.get("enclosures", [])
    for enc in enclosures:
        enc_type = enc.get("type", "")
        url = enc.get("href", enc.get("url", "")).strip()
        if enc_type.startswith("image/") and _is_valid_image_url(url):
            return url

    return None


def _is_valid_image_url(url):
    """Validate URL is absolute http(s) and within length limit."""
    if not url:
        return False
    if not url.startswith(("http://", "https://")):
        return False
    if len(url) > 2048:
        return False
    return True


# ─── Main Handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Fetch all enabled RSS feeds and store new article metadata in DynamoDB.
    """
    feeds = load_feeds_config()
    ingested_at = datetime.now(timezone.utc).isoformat()

    stats = {
        "feeds_processed": 0,
        "articles_found": 0,
        "articles_stored": 0,
        "duplicates_skipped": 0,
        "errors": [],
    }

    for feed_config in feeds:
        source_name = feed_config["source_name"]
        feed_url = feed_config["feed_url"]

        print(f"Fetching feed: {source_name} ({feed_url})")

        try:
            parsed = feedparser.parse(feed_url)

            if parsed.bozo and not parsed.entries:
                error_msg = f"Feed parse error for {source_name}: {parsed.bozo_exception}"
                print(error_msg)
                stats["errors"].append(error_msg)
                continue

            stats["feeds_processed"] += 1

            for entry in parsed.entries:
                stats["articles_found"] += 1

                # Extract the canonical URL
                link = entry.get("link", "").strip()
                if not link:
                    continue

                # Build article record
                image_url = extract_source_image_url(entry)
                article = {
                    "article_id": generate_article_id(link),
                    "source_name": source_name,
                    "headline": entry.get("title", "").strip(),
                    "original_url": link,
                    "pub_date": parse_pub_date(entry),
                    "ingested_at": ingested_at,
                    "feed_description": entry.get("summary", "").strip()[:1000],
                    "processing_status": "pending",
                    "source_language": "en",
                    "source_image_url": image_url,
                    "source_image_source": source_name if image_url else None,
                }

                # Attempt to store (dedup via condition expression)
                if store_article(article):
                    stats["articles_stored"] += 1
                else:
                    stats["duplicates_skipped"] += 1

        except Exception as e:
            error_msg = f"Error processing feed {source_name}: {str(e)}"
            print(error_msg)
            stats["errors"].append(error_msg)

    print(f"Ingestion complete: {json.dumps(stats)}")

    return {
        "statusCode": 200,
        "body": json.dumps(stats),
    }
