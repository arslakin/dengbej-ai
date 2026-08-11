"""
Dengbej AI — Program Generator Lambda

Generates topic-specific program briefings by:
1. Classifying fresh articles into programs
2. Clustering related stories
3. Ranking by editorial significance
4. Storing up to 5 stories per program

Programs: today, kurdistan, world, middle-east, turkey, bakur, rojava, basur, rojhilat

Does NOT generate scripts or audio. Those are separate pipeline stages.
"""

import json
import os
import time
import re
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

# Add parent path for program_classifier import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from program_classifier.programs import (
    classify_story_deterministic, PROGRAMS, PROGRAM_MAP, PROGRAM_IDS
)

# Configuration
ARTICLES_TABLE = os.environ.get("ARTICLES_TABLE", "dengbej-articles")
PROGRAMS_TABLE = os.environ.get("PROGRAMS_TABLE", "dengbej-programs")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
FRESHNESS_HOURS = int(os.environ.get("FRESHNESS_HOURS", "48"))
MAX_STORIES_PER_PROGRAM = 5

# AWS Clients
dynamodb = boto3.resource("dynamodb")
articles_table = dynamodb.Table(ARTICLES_TABLE)
programs_table = dynamodb.Table(PROGRAMS_TABLE)
bedrock_runtime = boto3.client("bedrock-runtime")


class Telemetry:
    def __init__(self):
        self.articles_examined = 0
        self.deterministic_matches = 0
        self.deterministic_exclusions = 0
        self.ambiguous_candidates = 0
        self.bedrock_calls = 0
        self.bedrock_input_tokens = 0
        self.bedrock_output_tokens = 0
        self.programs_generated = 0
        self.total_stories_selected = 0
        self.start_time = time.time()
        self.duration_ms = 0

    def finish(self):
        self.duration_ms = int((time.time() - self.start_time) * 1000)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if k != 'start_time'}


def lambda_handler(event, context):
    """Generate program briefings."""
    telemetry = Telemetry()

    target_date = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    program_id = event.get("program_id")  # Optional: generate specific program only
    force = event.get("force", False)

    # Determine which programs to generate
    if program_id:
        if program_id == "today":
            telemetry.finish()
            return {"statusCode": 200, "body": {"message": "Use the curator for 'today' program"}}
        if program_id not in PROGRAM_IDS:
            telemetry.finish()
            return {"statusCode": 400, "body": {"error": f"Invalid program: {program_id}"}}
        programs_to_generate = [program_id]
    else:
        # Generate all topic programs (not 'today' — that uses the curator)
        programs_to_generate = [p for p in PROGRAM_IDS if p != "today"]

    # Get fresh articles
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESHNESS_HOURS)
    articles = get_fresh_articles(cutoff)
    telemetry.articles_examined = len(articles)

    if not articles:
        telemetry.finish()
        return {"statusCode": 200, "body": {"message": "No fresh articles", "telemetry": telemetry.to_dict()}}

    # Classify all articles into programs (deterministic first pass)
    article_programs = classify_articles(articles, telemetry)

    # Generate each program
    results = {}
    for pid in programs_to_generate:
        # Idempotency check
        if not force:
            existing = get_existing_program(pid, target_date)
            if existing:
                results[pid] = {"status": "exists", "story_count": existing.get("story_count", 0)}
                continue

        # Get candidates for this program
        candidates = [a for a in articles if pid in article_programs.get(a["article_id"], set())]

        if not candidates:
            results[pid] = {"status": "empty", "story_count": 0}
            store_program_briefing(pid, target_date, [])
            telemetry.programs_generated += 1
            continue

        # Cluster and rank
        selected = cluster_and_rank(candidates, pid, telemetry)

        # Store program briefing
        store_program_briefing(pid, target_date, selected)
        results[pid] = {"status": "generated", "story_count": len(selected)}
        telemetry.programs_generated += 1
        telemetry.total_stories_selected += len(selected)

    telemetry.finish()
    print(f"Telemetry: {json.dumps(telemetry.to_dict())}")

    return {"statusCode": 200, "body": {
        "date": target_date,
        "programs": results,
        "telemetry": telemetry.to_dict(),
    }}


def get_fresh_articles(cutoff):
    """Get articles published after cutoff."""
    cutoff_iso = cutoff.isoformat()
    items = []
    response = articles_table.scan(
        FilterExpression="pub_date > :cutoff",
        ExpressionAttributeValues={":cutoff": cutoff_iso},
    )
    items.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        response = articles_table.scan(
            FilterExpression="pub_date > :cutoff",
            ExpressionAttributeValues={":cutoff": cutoff_iso},
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))
    return items


def classify_articles(articles, telemetry):
    """Classify all articles into programs using deterministic logic."""
    article_programs = {}
    for article in articles:
        headline = article.get("headline", "")
        description = article.get("feed_description", "")
        result = classify_story_deterministic(headline, description)
        article_programs[article["article_id"]] = result.programs

        if len(result.programs) > 1:
            telemetry.deterministic_matches += 1
        else:
            telemetry.deterministic_exclusions += 1

    return article_programs


def cluster_and_rank(candidates, program_id, telemetry):
    """Cluster candidates and select top stories for the program."""
    # Simple clustering by headline similarity (reusing pattern from curator)
    STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of",
                 "and", "or", "but", "with", "by", "from", "as", "its", "has", "have", "had", "be",
                 "been", "will", "would", "could", "should", "that", "this", "it", "not", "no",
                 "can", "do", "does", "did", "says", "said", "after", "over", "new", "more", "about"}

    def normalize(headline):
        text = headline.lower()
        text = re.sub(r"[-–—/]", " ", text)
        text = re.sub(r"[^a-z0-9\s]", "", text)
        return [w for w in text.split() if w not in STOPWORDS and len(w) > 2]

    def similarity(tokens_a, tokens_b):
        a, b = set(tokens_a), set(tokens_b)
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    # Cluster by headline similarity
    tokenized = [(c, normalize(c.get("headline", ""))) for c in candidates]
    clusters = []
    assigned = set()

    for i, (art_i, tok_i) in enumerate(tokenized):
        if i in assigned:
            continue
        cluster = [art_i]
        assigned.add(i)
        for j, (art_j, tok_j) in enumerate(tokenized):
            if j in assigned or j <= i:
                continue
            if similarity(tok_i, tok_j) >= 0.40:
                cluster.append(art_j)
                assigned.add(j)
        clusters.append(cluster)

    # Build cluster info and rank by freshness + source diversity
    ranked = []
    for cluster in clusters:
        sources = list(set(a.get("source_name", "") for a in cluster))
        most_recent = max(cluster, key=lambda a: a.get("pub_date", ""))
        ranked.append({
            "headline": most_recent.get("headline", ""),
            "category": program_id,
            "primary_source": most_recent.get("source_name", ""),
            "original_url": most_recent.get("original_url", ""),
            "pub_date": most_recent.get("pub_date", ""),
            "feed_description": most_recent.get("feed_description", ""),
            "cross_source_count": len(sources),
            "supporting_sources": [
                {"source_name": a.get("source_name", ""), "url": a.get("original_url", "")}
                for a in cluster if a.get("original_url") != most_recent.get("original_url")
            ],
        })

    # Sort by cross-source coverage first, then freshness
    ranked.sort(key=lambda x: (x["cross_source_count"], x.get("pub_date", "")), reverse=True)

    return ranked[:MAX_STORIES_PER_PROGRAM]


def get_existing_program(program_id, date_str):
    """Check if a program briefing already exists for today."""
    try:
        response = programs_table.get_item(
            Key={"program_id": program_id, "briefing_date": date_str}
        )
        return response.get("Item")
    except ClientError:
        return None


def store_program_briefing(program_id, date_str, stories):
    """Store program briefing in DynamoDB."""
    program = PROGRAM_MAP.get(program_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    item = {
        "program_id": program_id,
        "briefing_date": date_str,
        "generated_at": now_iso,
        "label_ku": program.label_ku if program else program_id,
        "label_en": program.label_en if program else program_id,
        "story_count": len(stories),
        "stories": stories,
        "script_ku": None,
        "audio_url": None,
    }

    programs_table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
    print(f"Program stored: {program_id} ({len(stories)} stories)")
