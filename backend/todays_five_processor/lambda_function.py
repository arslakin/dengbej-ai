"""
Dengbej AI — Today's 5 Processor Lambda

Takes the 5 selected stories from dengbej-briefings and produces:
  1. English summary (3-5 sentences) synthesized from multiple sources
  2. Kurdish Kurmanji translation of the English summary

Processing pipeline per story:
  1. Check idempotency (skip if already processed)
  2. Fetch primary article text via HTTP + BeautifulSoup
  3. Fetch supporting source texts (graceful failure)
  4. Call Bedrock to synthesize factual English summary
  5. Call Bedrock to translate summary to Kurdish Kurmanji
  6. Update briefing item with results

Resilience:
  - One story failure does not stop others
  - Failed supporting sources are tracked but don't block processing
  - Already-processed stories are skipped (idempotent)
"""

import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import requests
from bs4 import BeautifulSoup
from botocore.exceptions import ClientError


# ─── Configuration ───────────────────────────────────────────────────────────

BRIEFINGS_TABLE = os.environ.get("BRIEFINGS_TABLE", "dengbej-briefings")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
MAX_ARTICLE_LENGTH = int(os.environ.get("MAX_ARTICLE_LENGTH", "4000"))


# ─── AWS Clients ─────────────────────────────────────────────────────────────

dynamodb = boto3.resource("dynamodb")
briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
bedrock_runtime = boto3.client("bedrock-runtime")


# ─── Telemetry ───────────────────────────────────────────────────────────────

class Telemetry:
    """Tracks processing metrics for each invocation."""

    def __init__(self):
        self.stories_attempted = 0
        self.stories_processed = 0
        self.stories_partial = 0
        self.stories_failed = 0
        self.stories_skipped = 0
        self.bedrock_calls = 0
        self.bedrock_input_tokens = 0
        self.bedrock_output_tokens = 0
        self.sources_fetched = 0
        self.sources_failed = 0
        self.start_time = time.time()
        self.duration_ms = 0

    def finish(self):
        self.duration_ms = int((time.time() - self.start_time) * 1000)

    def to_dict(self):
        return {
            "stories_attempted": self.stories_attempted,
            "stories_processed": self.stories_processed,
            "stories_partial": self.stories_partial,
            "stories_failed": self.stories_failed,
            "stories_skipped": self.stories_skipped,
            "bedrock_calls": self.bedrock_calls,
            "bedrock_input_tokens": self.bedrock_input_tokens,
            "bedrock_output_tokens": self.bedrock_output_tokens,
            "sources_fetched": self.sources_fetched,
            "sources_failed": self.sources_failed,
            "duration_ms": self.duration_ms,
        }


# ─── Main Handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """Process today's 5 stories: summarize and translate."""
    telemetry = Telemetry()

    # Determine target date
    target_date = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"Processing briefing for date: {target_date}")

    # Fetch the briefing
    briefing = get_briefing(target_date)
    if not briefing:
        telemetry.finish()
        return {
            "statusCode": 404,
            "body": {
                "error": f"No briefing found for {target_date}",
                "telemetry": telemetry.to_dict(),
            },
        }

    stories = briefing.get("stories", [])
    briefing_date = briefing["briefing_date"]
    generated_at = briefing["generated_at"]

    print(f"Found briefing with {len(stories)} stories")

    # Process each story independently
    for i, story in enumerate(stories):
        telemetry.stories_attempted += 1

        # Idempotency: skip already-processed stories
        if story.get("processing_status") == "processed":
            print(f"Story {i+1} already processed, skipping: {story.get('headline', '')[:60]}")
            telemetry.stories_skipped += 1
            continue

        try:
            process_story(story, telemetry)
        except Exception as e:
            print(f"Story {i+1} failed: {e}")
            story["processing_status"] = "failed"
            story["processing_error"] = str(e)[:200]
            telemetry.stories_failed += 1

    # Write updated briefing back to DynamoDB
    update_briefing(briefing_date, generated_at, stories)

    telemetry.finish()
    print(f"Telemetry: {json.dumps(telemetry.to_dict())}")

    return {
        "statusCode": 200,
        "body": {
            "briefing_date": briefing_date,
            "stories_attempted": telemetry.stories_attempted,
            "stories_processed": telemetry.stories_processed,
            "stories_partial": telemetry.stories_partial,
            "stories_failed": telemetry.stories_failed,
            "stories_skipped": telemetry.stories_skipped,
            "telemetry": telemetry.to_dict(),
        },
    }


# ─── Briefing Access ─────────────────────────────────────────────────────────

def get_briefing(target_date):
    """Query the briefings table for the given date. Returns most recent briefing."""
    try:
        response = briefings_table.query(
            KeyConditionExpression="briefing_date = :bd",
            ExpressionAttributeValues={":bd": target_date},
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except ClientError as e:
        print(f"Error querying briefings: {e}")
        return None


def update_briefing(briefing_date, generated_at, stories):
    """Update the stories list in the briefing."""
    try:
        # Convert to DynamoDB-safe format (handle floats -> Decimal)
        safe_stories = json.loads(json.dumps(stories, default=str), parse_float=Decimal)
        briefings_table.update_item(
            Key={"briefing_date": briefing_date, "generated_at": generated_at},
            UpdateExpression="SET stories = :s",
            ExpressionAttributeValues={":s": safe_stories},
        )
        print(f"Briefing updated: {briefing_date}")
    except ClientError as e:
        print(f"Error updating briefing: {e}")
        raise


# ─── Story Processing ────────────────────────────────────────────────────────

def process_story(story, telemetry):
    """Process a single story: fetch sources, summarize, translate."""
    headline = story.get("headline", "Unknown")
    print(f"Processing: {headline[:80]}")

    # Collect source texts
    sources_used = []
    sources_failed = []

    # Fetch primary article
    primary_url = story.get("original_url", "")
    primary_text = ""
    if primary_url:
        primary_text = fetch_source_text(primary_url, telemetry)
        if primary_text:
            sources_used.append(primary_url)
        else:
            sources_failed.append(primary_url)

    # Fetch supporting sources
    supporting_sources = story.get("supporting_sources", [])
    supporting_texts = []
    for source in supporting_sources:
        url = source.get("url", "")
        if not url:
            continue
        text = fetch_source_text(url, telemetry)
        if text:
            supporting_texts.append(text)
            sources_used.append(url)
        else:
            sources_failed.append(url)

    # Determine if we have enough to summarize
    all_texts = []
    if primary_text:
        all_texts.append(primary_text)
    all_texts.extend(supporting_texts)

    if not all_texts:
        # No source text available — use feed description as fallback
        feed_desc = story.get("feed_description", "")
        if feed_desc:
            all_texts.append(feed_desc)
        else:
            story["processing_status"] = "failed"
            story["processing_error"] = "No source text available"
            telemetry.stories_failed += 1
            return

    # Generate English summary
    summary_en = generate_summary(headline, all_texts, telemetry)
    if not summary_en:
        story["processing_status"] = "failed"
        story["processing_error"] = "Summary generation failed"
        telemetry.stories_failed += 1
        return

    # Translate to Kurdish Kurmanji
    summary_ku = translate_to_kurdish(summary_en, telemetry)

    # Update story
    story["summary_en"] = summary_en
    story["summary_ku"] = summary_ku if summary_ku else None
    story["processing_status"] = "processed" if summary_ku else "partial"
    story["processed_at"] = datetime.now(timezone.utc).isoformat()
    story["sources_used"] = sources_used
    story["sources_failed"] = sources_failed

    if story["processing_status"] == "processed":
        telemetry.stories_processed += 1
    else:
        telemetry.stories_partial += 1

    print(f"  ✓ Processed: {headline[:60]} (sources: {len(sources_used)} used, {len(sources_failed)} failed)")


# ─── Article Extraction ──────────────────────────────────────────────────────

def extract_article_text(url, max_length=None):
    """
    Fetch and extract article text from a URL.
    Removes non-content elements and extracts paragraph text.
    """
    if max_length is None:
        max_length = MAX_ARTICLE_LENGTH

    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove script, style, nav, footer, header elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    paragraphs = soup.find_all("p")
    text = " ".join(p.get_text().strip() for p in paragraphs if p.get_text().strip())
    return text[:max_length] if text else ""


def fetch_source_text(url, telemetry):
    """Fetch article text with error handling. Returns empty string on failure."""
    try:
        text = extract_article_text(url)
        if text:
            telemetry.sources_fetched += 1
        return text
    except requests.RequestException as e:
        print(f"  Failed to fetch {url}: {e}")
        telemetry.sources_failed += 1
        return ""
    except Exception as e:
        print(f"  Unexpected error fetching {url}: {e}")
        telemetry.sources_failed += 1
        return ""


# ─── Bedrock: Summary Generation ─────────────────────────────────────────────

SYNTHESIS_PROMPT = """You are a factual news briefing writer for a global news platform.

Given the headline and source texts below, write a 3-5 sentence factual English summary.

RULES:
- Synthesize facts from ALL provided sources into ONE neutral briefing paragraph
- Do NOT reproduce any single source's article verbatim
- Be factual and neutral — avoid sensational language
- Do NOT invent facts or add information not supported by the sources
- When sources disagree on a detail, either describe the disagreement briefly or omit the disputed detail
- Answer: What happened? Where? Who is involved? Why does it matter? What is the context?
- Produce exactly 3-5 sentences
- Write in clear, concise English suitable for a global audience

HEADLINE: {headline}

SOURCE TEXTS:
{sources}

SUMMARY:"""


def generate_summary(headline, source_texts, telemetry):
    """Generate a 3-5 sentence English summary from multiple source texts."""
    # Format source texts with numbering
    sources_formatted = ""
    for i, text in enumerate(source_texts, 1):
        sources_formatted += f"\n--- Source {i} ---\n{text}\n"

    prompt = SYNTHESIS_PROMPT.format(headline=headline, sources=sources_formatted)

    try:
        result = invoke_bedrock(prompt, max_tokens=500, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"  Bedrock summary generation failed: {e}")
        return None


# ─── Bedrock: Kurdish Translation ────────────────────────────────────────────

TRANSLATION_PROMPT = """Translate the following English news summary faithfully into Kurdish Kurmanji.

RULES:
- Translate accurately — preserve the meaning of the original text
- Do NOT independently summarize or reinterpret the content
- Do NOT add information not present in the English text
- Use standard Kurdish Kurmanji orthography
- Maintain the same sentence structure and tone as the English version
- Translate proper nouns phonetically where no established Kurdish form exists

ENGLISH SUMMARY:
{summary}

KURDISH KURMANJI TRANSLATION:"""


def translate_to_kurdish(summary_en, telemetry):
    """Translate English summary to Kurdish Kurmanji."""
    prompt = TRANSLATION_PROMPT.format(summary=summary_en)

    try:
        result = invoke_bedrock(prompt, max_tokens=600, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"  Bedrock translation failed: {e}")
        return None


# ─── Bedrock Helper ──────────────────────────────────────────────────────────

def invoke_bedrock(prompt, max_tokens=500, telemetry=None):
    """Invoke Bedrock Claude model and track token usage."""
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = bedrock_runtime.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(request_body),
    )

    response_body = json.loads(response["body"].read())

    # Track telemetry
    if telemetry:
        telemetry.bedrock_calls += 1
        usage = response_body.get("usage", {})
        telemetry.bedrock_input_tokens += usage.get("input_tokens", 0)
        telemetry.bedrock_output_tokens += usage.get("output_tokens", 0)

    return response_body["content"][0]["text"].strip()
