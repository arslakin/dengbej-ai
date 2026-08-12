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
import hashlib
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

# Import program classifier (bundled locally)
from programs import (
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
        self.programs_unchanged = 0
        self.programs_empty = 0
        self.scripts_generated = 0
        self.scripts_reused = 0
        self.total_stories_selected = 0
        self.start_time = time.time()
        self.duration_ms = 0

    def finish(self):
        self.duration_ms = int((time.time() - self.start_time) * 1000)

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if k != 'start_time'}


def lambda_handler(event, context):
    """Generate program briefings with content-based change detection."""
    telemetry = Telemetry()

    target_date = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    program_id = event.get("program_id")  # Optional: generate specific program only
    force = event.get("force", False)
    generate_scripts = event.get("generate_scripts", True)  # Auto-generate scripts for changed programs

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
    programs_needing_scripts = []

    for pid in programs_to_generate:
        try:
            # Get candidates for this program
            candidates = [a for a in articles if pid in article_programs.get(a["article_id"], set())]

            if not candidates:
                # Empty program
                existing = get_existing_program(pid, target_date)
                if not existing or existing.get("story_count", 0) != 0:
                    store_program_briefing(pid, target_date, [], content_fingerprint="empty")
                results[pid] = {"status": "empty", "story_count": 0}
                telemetry.programs_empty += 1
                continue

            # Cluster and rank
            selected = cluster_and_rank(candidates, pid, telemetry)

            # Calculate content fingerprint
            fingerprint = compute_content_fingerprint(selected)

            # Check if content actually changed
            existing = get_existing_program(pid, target_date)
            if existing and not force:
                existing_fingerprint = existing.get("content_fingerprint", "")
                if existing_fingerprint == fingerprint:
                    # Content unchanged — check if script needs retry
                    existing_script = existing.get("script_ku")
                    if existing_script:
                        # Complete: content + script intact, nothing to do
                        results[pid] = {"status": "unchanged", "story_count": len(selected)}
                        telemetry.programs_unchanged += 1
                        telemetry.scripts_reused += 1
                    else:
                        # Content matches but script is missing — retry generation
                        results[pid] = {"status": "unchanged", "story_count": len(selected)}
                        telemetry.programs_unchanged += 1
                        programs_needing_scripts.append(pid)
                    continue

            # Content changed or new — store updated program
            store_program_briefing(pid, target_date, selected, content_fingerprint=fingerprint)
            results[pid] = {"status": "generated", "story_count": len(selected)}
            telemetry.programs_generated += 1
            telemetry.total_stories_selected += len(selected)
            programs_needing_scripts.append(pid)

        except Exception as e:
            print(f"Program {pid} failed: {e}")
            results[pid] = {"status": "error", "error": str(e)[:100]}

    # Generate scripts for changed programs (if enabled)
    if generate_scripts and programs_needing_scripts:
        for pid in programs_needing_scripts:
            try:
                script = generate_program_script_inline(pid, target_date, telemetry)
                if script:
                    telemetry.scripts_generated += 1
                    results[pid]["script_generated"] = True
            except Exception as e:
                print(f"Script generation failed for {pid}: {e}")
                results[pid]["script_error"] = str(e)[:100]

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


def store_program_briefing(program_id, date_str, stories, content_fingerprint=""):
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
        "content_fingerprint": content_fingerprint,
        "script_ku": None,
        "audio_url": None,
    }

    programs_table.put_item(Item=json.loads(json.dumps(item, default=str), parse_float=Decimal))
    print(f"Program stored: {program_id} ({len(stories)} stories, fingerprint: {content_fingerprint[:12]}...)")


def compute_content_fingerprint(stories):
    """
    Compute a stable fingerprint for a set of stories.
    Based on sorted unique article URLs — stable regardless of ordering.
    """
    urls = sorted(set(s.get("original_url", "") for s in stories if s.get("original_url")))
    content = "|".join(urls)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]


def generate_program_script_inline(program_id, date_str, telemetry):
    """Generate a Kurmanji script for a program (inline, after story generation)."""
    program = get_existing_program(program_id, date_str)
    if not program:
        return None

    stories = program.get("stories", [])
    if not stories:
        return None

    # Build prompt
    story_blocks = []
    for i, story in enumerate(stories, 1):
        block = f"Story {i}:\nHeadline: {story.get('headline', '')}\nCategory: {story.get('category', program_id)}\nDescription: {story.get('feed_description', '')}\nSource: {story.get('primary_source', '')}"
        story_blocks.append(block)

    stories_text = "\n\n".join(story_blocks)
    story_count = len(stories)

    prompt = f"""You are composing a Kurmanji Kurdish news segment for Dengbej audio service.
Program: {program_id} | Date: {date_str} | Stories: {story_count}

IMPORTANT — DUPLICATE DETECTION:
Multiple source stories below may describe the SAME event from different publishers.
If stories overlap, synthesize them into ONE segment. Do NOT narrate each source separately.
State each fact ONLY ONCE.

LANGUAGE RULES:
- Write DIRECTLY in natural Kurmanji Kurdish
- Use ONLY standard, widely understood Kurmanji vocabulary
- NEVER invent a Kurdish-looking word
- NEVER insert English words
- Do NOT use the characters "ğ" or "ı"

NUMBER ACCURACY (CRITICAL):
- Preserve the EXACT semantic value of every number
- 40 = çil (NOT çardeh), 14 = çardeh
- If uncertain, keep the numeric form

GEOGRAPHIC TERMINOLOGY:
- Rojhilata Navîn = Middle East (NEVER "Rojava Navîn")

FACTUAL RULES:
- Use ONLY facts from the supplied stories
- Do NOT invent facts, quotes, or background context
- If a source provides only a headline, produce a SHORT bulletin

LENGTH AND REPETITION:
- Length must match available factual material — never pad
- NEVER repeat the same fact in different words

STRUCTURE:
- Opening: "Rojbaş. Ev Dengbej e. {date_str}."
- Tell the stories concisely
- Closing: "Ev bû Dengbej. Hêvî dikin ku sibê jî li gel we bin."

OUTPUT: Write ONLY the spoken text.

STORIES:

{stories_text}

KURDISH BROADCAST SCRIPT:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=2000, telemetry=telemetry)
        if result:
            script = result.strip()
            # Store script
            now_iso = datetime.now(timezone.utc).isoformat()
            programs_table.update_item(
                Key={"program_id": program_id, "briefing_date": date_str},
                UpdateExpression="SET script_ku = :script, script_meta = :meta",
                ExpressionAttributeValues={
                    ":script": script,
                    ":meta": {
                        "script_generated_at": now_iso,
                        "model_id": MODEL_ID,
                        "script_chars": len(script),
                        "bedrock_input_tokens": telemetry.bedrock_input_tokens,
                        "bedrock_output_tokens": telemetry.bedrock_output_tokens,
                    },
                },
            )
            print(f"Script generated for {program_id} ({len(script)} chars)")
            return script
    except Exception as e:
        print(f"Inline script generation failed for {program_id}: {e}")
    return None


def invoke_bedrock(prompt, max_tokens=2000, telemetry=None):
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
