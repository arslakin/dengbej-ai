"""
Dengbej AI — Daily Audio Script + Narration Generator

Generates a coherent Kurmanji Kurdish broadcast script from Today's 5,
then synthesizes an English narration via Amazon Polly and uploads to S3.

Pipeline:
  1. Retrieve latest processed Today's 5 briefing
  2. Check idempotency (skip if script + audio already exist)
  3. Generate Kurdish broadcast script via Bedrock
  4. Generate short English narration script via Bedrock
  5. Synthesize English audio via Amazon Polly (neural)
  6. Upload audio to S3
  7. Store script + audio URL + metadata in DynamoDB

The Kurdish script is the primary editorial product (displayed as text).
The English audio narration provides an accessible listening experience
until a Kurdish TTS provider becomes available.
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
PROGRAMS_TABLE = os.environ.get("PROGRAMS_TABLE", "dengbej-programs")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "dengbej-audio")
TTS_ENABLED = os.environ.get("TTS_ENABLED", "true").lower() == "true"
KURDISH_TTS_ENABLED = os.environ.get("KURDISH_TTS_ENABLED", "false").lower() == "true"
KURDISH_TTS_MONTHLY_BUDGET_CHARS = int(os.environ.get("KURDISH_TTS_MONTHLY_BUDGET_CHARS", "18000"))

# AWS Clients
dynamodb = boto3.resource("dynamodb")
briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
programs_table = dynamodb.Table(PROGRAMS_TABLE)
bedrock_runtime = boto3.client("bedrock-runtime")
polly_client = boto3.client("polly")
s3_client = boto3.client("s3")


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
    """Generate Kurdish broadcast script from Today's 5 or a specific program."""

    # Controlled test event: synthesize a short Kurdish sample without touching briefings
    if event.get("test_kurdish_tts") is True:
        return handle_tts_test(event)

    # Controlled batch: generate Kurdish audio for multiple programs within budget
    if event.get("generate_kurdish_batch") is True:
        return handle_kurdish_batch(event)

    telemetry = Telemetry()

    target_date = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    force = event.get("force", False)
    program_id = event.get("program_id")  # None = Today's 5, otherwise topic program

    if program_id and program_id != "today":
        return handle_program_script(program_id, target_date, force, telemetry)
    else:
        return handle_today_script(target_date, force, telemetry)


# ─── Controlled TTS Test (does not touch briefings or programs) ──────────────

def handle_tts_test(event):
    """
    Synthesize a short Kurdish text sample for testing.

    Required event fields:
      test_kurdish_tts: true  (exactly boolean true)
      text: string, max 300 characters

    Stores result under tts-tests/ S3 prefix. Does not modify DynamoDB.
    Does not log or expose the API key.
    """
    text = event.get("text", "")
    if not text or not isinstance(text, str):
        return {"statusCode": 400, "body": {"error": "text is required (string)"}}
    if len(text) > 300:
        return {"statusCode": 400, "body": {"error": f"text exceeds 300 char limit ({len(text)} chars)"}}

    speaker = event.get("speaker_id", KURDISH_TTS_SPEAKER)

    try:
        from kurdish_tts import synthesize_kurdish
        audio_data = synthesize_kurdish(text, speaker_id=speaker)
    except Exception as e:
        return {"statusCode": 500, "body": {"error": f"TTS synthesis failed: {str(e)[:200]}"}}

    # Upload to S3 under tts-tests/ prefix
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_key = f"tts-tests/{speaker}_{timestamp}.wav"
    s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=audio_data, ContentType="audio/wav")
    audio_url = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"

    print(f"TTS test: {len(text)} chars, speaker={speaker}, size={len(audio_data)} bytes, key={s3_key}")

    return {"statusCode": 200, "body": {
        "status": "test_complete",
        "chars_synthesized": len(text),
        "speaker_id": speaker,
        "audio_size_bytes": len(audio_data),
        "audio_url": audio_url,
        "s3_key": s3_key,
    }}


KURDISH_TTS_SPEAKER = os.environ.get("KURDISH_TTS_SPEAKER", "kurmanji_236")

# Priority order for batch generation
BATCH_PRIORITY = ["today", "world", "middle-east", "turkey", "kurdistan", "bakur", "rojava", "basur", "rojhilat"]


def handle_kurdish_batch(event):
    """
    Generate Kurdish audio for multiple programs within a character budget.

    Required event fields:
      generate_kurdish_batch: true
      max_chars: int (hard cap for this invocation)

    Optional:
      dry_run: bool (default true — report candidates without making API calls)
      chars_already_used: int (characters already consumed this month, default 0)

    Prioritizes: today > world > middle-east > turkey > regional programs.
    Skips programs that already have audio_url_ku or have zero stories.
    Stops before exceeding budget. Does not modify English audio fields.
    """
    dry_run = event.get("dry_run", True)
    max_chars = event.get("max_chars")
    chars_already_used = int(event.get("chars_already_used", 0))

    if not isinstance(max_chars, int) or max_chars <= 0:
        return {"statusCode": 400, "body": {"error": "max_chars is required (positive int)"}}

    # Use persistent DynamoDB quota if available, fall back to event parameter
    from quota import get_usage, get_remaining, reserve as quota_reserve, refund as quota_refund, get_current_month_key
    month_key = get_current_month_key()
    try:
        persistent_used = get_usage(month_key)
        chars_already_used = max(chars_already_used, persistent_used)
    except Exception:
        pass  # Fall back to event-passed value

    budget_remaining = min(max_chars, KURDISH_TTS_MONTHLY_BUDGET_CHARS - chars_already_used)
    if budget_remaining <= 0:
        return {"statusCode": 200, "body": {"status": "budget_exhausted", "budget_remaining": 0, "candidates": []}}

    target_date = event.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    speaker = event.get("speaker_id", KURDISH_TTS_SPEAKER)

    # Gather candidates with their scripts
    candidates = []

    # Today's briefing
    briefing = _get_briefing_for_batch(target_date)
    if briefing:
        script = briefing.get("daily_audio_script_ku", "")
        existing_ku = (briefing.get("daily_audio_meta") or {}).get("audio_url_ku")
        if script and not existing_ku:
            candidates.append({
                "program_id": "today",
                "script": script,
                "chars": len(script),
                "source": "briefing",
                "briefing_date": briefing["briefing_date"],
                "generated_at": briefing.get("generated_at", ""),
            })

    # Topic programs in priority order
    for pid in BATCH_PRIORITY:
        if pid == "today":
            continue
        program = _get_program_for_batch(pid, target_date)
        if not program:
            continue
        script = program.get("script_ku", "")
        existing_ku = program.get("audio_url_ku")
        story_count = program.get("story_count", 0)
        if not script or existing_ku or story_count == 0:
            continue
        candidates.append({
            "program_id": pid,
            "script": script,
            "chars": len(script),
            "source": "program",
            "briefing_date": program.get("briefing_date", target_date),
        })

    # Calculate what fits within budget
    selected = []
    total_chars = 0
    for c in candidates:
        if total_chars + c["chars"] > budget_remaining:
            break
        selected.append(c)
        total_chars += c["chars"]

    report = {
        "status": "dry_run" if dry_run else "completed",
        "date": target_date,
        "budget_remaining": budget_remaining,
        "candidates_found": len(candidates),
        "candidates_selected": len(selected),
        "total_chars_selected": total_chars,
        "chars_already_used": chars_already_used,
        "programs": [{"program_id": c["program_id"], "chars": c["chars"]} for c in selected],
        "skipped": [{"program_id": c["program_id"], "chars": c["chars"], "reason": "over_budget"} for c in candidates[len(selected):]],
    }

    if dry_run:
        return {"statusCode": 200, "body": report}

    # Execute synthesis with atomic quota reservation
    from kurdish_tts import synthesize_kurdish
    results = []

    for c in selected:
        # Reserve quota atomically before calling the API
        reserved = False
        try:
            reserved = quota_reserve(c["chars"], month_key)
        except Exception:
            reserved = True  # If quota check fails, proceed cautiously

        if not reserved:
            results.append({"program_id": c["program_id"], "chars": c["chars"], "status": "skipped", "reason": "quota_exceeded"})
            print(f"  Batch: {c['program_id']} skipped (quota would be exceeded)")
            continue

        try:
            audio_data = synthesize_kurdish(c["script"], speaker_id=speaker)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

            if c["source"] == "briefing":
                s3_key = f"daily/{c['briefing_date']}_ku_{timestamp}.wav"
            else:
                s3_key = f"programs/{c['program_id']}/{c['briefing_date']}_ku_{timestamp}.wav"

            s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=audio_data, ContentType="audio/wav")
            audio_url_ku = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"

            # Update DynamoDB (only audio_url_ku, never touch audio_url or audio_url_en)
            if c["source"] == "briefing":
                _update_briefing_ku_audio(c["briefing_date"], c["generated_at"], audio_url_ku)
            else:
                _update_program_ku_audio(c["program_id"], c["briefing_date"], audio_url_ku)

            results.append({"program_id": c["program_id"], "chars": c["chars"], "status": "success", "audio_url_ku": audio_url_ku})
            print(f"  Batch: {c['program_id']} synthesized ({c['chars']} chars)")

        except Exception as e:
            # Refund the reservation on failure
            try:
                quota_refund(c["chars"], month_key)
            except Exception:
                pass
            results.append({"program_id": c["program_id"], "chars": c["chars"], "status": "failed", "error": str(e)[:100]})
            print(f"  Batch: {c['program_id']} FAILED: {e}")

    chars_consumed = sum(r["chars"] for r in results if r["status"] == "success")
    report["status"] = "completed"
    report["results"] = results
    report["chars_consumed"] = chars_consumed
    report["new_monthly_total"] = chars_already_used + chars_consumed

    return {"statusCode": 200, "body": report}


def _get_briefing_for_batch(date_str):
    """Get today's briefing without filtering by processing status."""
    try:
        response = briefings_table.query(
            KeyConditionExpression="briefing_date = :bd",
            ExpressionAttributeValues={":bd": date_str},
            ScanIndexForward=False, Limit=1,
        )
        items = response.get("Items", [])
        return items[0] if items else None
    except Exception:
        return None


def _get_program_for_batch(program_id, date_str):
    """Get a program briefing."""
    try:
        response = programs_table.get_item(Key={"program_id": program_id, "briefing_date": date_str})
        return response.get("Item")
    except Exception:
        return None


def _update_briefing_ku_audio(briefing_date, generated_at, audio_url_ku):
    """Update only audio_url_ku in the briefing's daily_audio_meta."""
    briefings_table.update_item(
        Key={"briefing_date": briefing_date, "generated_at": generated_at},
        UpdateExpression="SET daily_audio_meta.audio_url_ku = :ku",
        ExpressionAttributeValues={":ku": audio_url_ku},
    )


def _update_program_ku_audio(program_id, briefing_date, audio_url_ku):
    """Update only audio_url_ku on the program record."""
    programs_table.update_item(
        Key={"program_id": program_id, "briefing_date": briefing_date},
        UpdateExpression="SET audio_url_ku = :ku",
        ExpressionAttributeValues={":ku": audio_url_ku},
    )


def handle_today_script(target_date, force, telemetry):
    """Generate script for Today's 5 (original behavior)."""
    print(f"Daily audio script generation for: {target_date} (force={force})")

    briefing = get_processed_briefing(target_date)
    if not briefing:
        telemetry.finish()
        return {"statusCode": 404, "body": {"error": f"No processed briefing for {target_date}", "telemetry": telemetry.to_dict()}}

    stories = briefing.get("stories", [])
    processed_stories = [s for s in stories if s.get("processing_status") == "processed"]

    if len(processed_stories) < 3:
        telemetry.finish()
        return {"statusCode": 400, "body": {"error": "Insufficient processed stories (need at least 3)", "telemetry": telemetry.to_dict()}}

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

    script = generate_broadcast_script(processed_stories, target_date, telemetry)
    if not script:
        telemetry.finish()
        return {"statusCode": 500, "body": {"error": "Script generation failed", "telemetry": telemetry.to_dict()}}

    telemetry.script_chars = len(script)

    # Generate English audio narration via Polly
    audio_url_en = None
    if TTS_ENABLED:
        try:
            narration_en = generate_english_narration(processed_stories, target_date, telemetry)
            if narration_en:
                audio_url_en = synthesize_and_upload(narration_en, f"daily/{target_date}_en")
                print(f"English audio uploaded: {audio_url_en}")
        except Exception as e:
            print(f"English audio generation failed (non-fatal): {e}")

    # Generate Kurdish audio narration via KurdishTTS
    audio_url_ku = None
    if KURDISH_TTS_ENABLED:
        try:
            from kurdish_tts import synthesize_kurdish
            audio_data_ku = synthesize_kurdish(script)
            if audio_data_ku:
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                s3_key = f"daily/{target_date}_ku_{timestamp}.wav"
                s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=audio_data_ku, ContentType="audio/wav")
                audio_url_ku = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
                print(f"Kurdish audio uploaded: {audio_url_ku}")
        except Exception as e:
            print(f"Kurdish audio generation failed (non-fatal): {e}")

    # Legacy compat: audio_url always points to English Polly
    audio_url = audio_url_en
    store_script(briefing, script, target_date, telemetry, audio_url=audio_url, audio_url_en=audio_url_en, audio_url_ku=audio_url_ku)

    telemetry.finish()
    print(f"Telemetry: {json.dumps(telemetry.to_dict())}")

    return {"statusCode": 200, "body": {
        "status": "generated",
        "briefing_date": target_date,
        "script_length": len(script),
        "story_count": len(processed_stories),
        "audio_url": audio_url,
        "audio_url_en": audio_url_en,
        "audio_url_ku": audio_url_ku,
        "telemetry": telemetry.to_dict(),
    }}


VALID_PROGRAM_IDS = {"kurdistan", "world", "middle-east", "turkey", "bakur", "rojava", "basur", "rojhilat"}


def handle_program_script(program_id, target_date, force, telemetry):
    """Generate script for a specific topic program."""
    print(f"Program script generation: {program_id} for {target_date} (force={force})")

    if program_id not in VALID_PROGRAM_IDS:
        telemetry.finish()
        return {"statusCode": 400, "body": {"error": f"Invalid program_id: {program_id}", "telemetry": telemetry.to_dict()}}

    # Get the program briefing from dengbej-programs
    program = get_program_briefing(program_id, target_date)
    if not program:
        telemetry.finish()
        return {"statusCode": 404, "body": {"error": f"No program briefing for {program_id} on {target_date}", "telemetry": telemetry.to_dict()}}

    stories = program.get("stories", [])
    if not stories:
        telemetry.finish()
        return {"statusCode": 200, "body": {
            "status": "empty",
            "program_id": program_id,
            "briefing_date": target_date,
            "message": "No stories in this program — no script generated",
            "telemetry": telemetry.to_dict(),
        }}

    # Idempotency: check if script already exists
    existing_script = program.get("script_ku")
    if existing_script and not force:
        print(f"Program script already exists for {program_id}, skipping")
        telemetry.finish()
        return {"statusCode": 200, "body": {
            "status": "already_exists",
            "program_id": program_id,
            "briefing_date": target_date,
            "script_length": len(existing_script),
            "telemetry": telemetry.to_dict(),
        }}

    # Generate the script
    script = generate_program_script(stories, program_id, target_date, telemetry)
    if not script:
        telemetry.finish()
        return {"statusCode": 500, "body": {"error": "Program script generation failed", "telemetry": telemetry.to_dict()}}

    telemetry.script_chars = len(script)

    # Generate English audio narration via Polly
    audio_url_en = None
    if TTS_ENABLED:
        try:
            narration_en = generate_program_narration_en(stories, program_id, target_date, telemetry)
            if narration_en:
                audio_url_en = synthesize_and_upload(narration_en, f"programs/{program_id}/{target_date}_en")
                print(f"Program English audio uploaded: {audio_url_en}")
        except Exception as e:
            print(f"Program English audio generation failed (non-fatal): {e}")

    # Generate Kurdish audio narration via KurdishTTS
    audio_url_ku = None
    if KURDISH_TTS_ENABLED:
        try:
            from kurdish_tts import synthesize_kurdish
            audio_data_ku = synthesize_kurdish(script)
            if audio_data_ku:
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                s3_key = f"programs/{program_id}/{target_date}_ku_{timestamp}.wav"
                s3_client.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=audio_data_ku, ContentType="audio/wav")
                audio_url_ku = f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
                print(f"Program Kurdish audio uploaded: {audio_url_ku}")
        except Exception as e:
            print(f"Program Kurdish audio generation failed (non-fatal): {e}")

    # Legacy compat: audio_url always points to English Polly
    audio_url = audio_url_en
    store_program_script(program_id, target_date, program.get("briefing_date", target_date), script, telemetry, audio_url=audio_url, audio_url_en=audio_url_en, audio_url_ku=audio_url_ku)

    telemetry.finish()
    print(f"Telemetry: {json.dumps(telemetry.to_dict())}")

    return {"statusCode": 200, "body": {
        "status": "generated",
        "program_id": program_id,
        "briefing_date": target_date,
        "script_length": len(script),
        "story_count": len(stories),
        "audio_url": audio_url,
        "audio_url_en": audio_url_en,
        "audio_url_ku": audio_url_ku,
        "telemetry": telemetry.to_dict(),
    }}


def get_program_briefing(program_id, date_str):
    """Get a program briefing from dengbej-programs table."""
    try:
        response = programs_table.get_item(
            Key={"program_id": program_id, "briefing_date": date_str}
        )
        return response.get("Item")
    except ClientError as e:
        print(f"DynamoDB programs error: {e}")
        return None


def generate_program_script(stories, program_id, date_str, telemetry):
    """Generate a Kurdish broadcast script for a topic program."""
    story_blocks = []
    for i, story in enumerate(stories, 1):
        block = f"""Story {i}:
Headline: {story.get('headline', '')}
Category: {story.get('category', program_id)}
Description: {story.get('feed_description', '')}
Source: {story.get('primary_source', '')}"""
        story_blocks.append(block)

    stories_text = "\n\n".join(story_blocks)
    story_count = len(stories)

    prompt = f"""You are composing a Kurmanji Kurdish news segment for Dengbej audio service.
Program: {program_id} | Date: {date_str} | Stories: {story_count}

IMPORTANT — DUPLICATE DETECTION:
Multiple source stories below may describe the SAME event from different publishers.
If stories overlap, synthesize them into ONE segment. Do NOT narrate each source separately.
State each fact ONLY ONCE. Different sources may add different details — combine them.

LANGUAGE RULES:
- Write DIRECTLY in natural Kurmanji Kurdish
- Use ONLY standard, widely understood Kurmanji vocabulary
- If you are uncertain about a Kurdish word, use a simpler established expression instead
- NEVER invent a Kurdish-looking word — if no standard term exists, describe it simply
- NEVER insert English words (no "clear", "process", "deal", etc.)
- Avoid unnecessary Turkish vocabulary
- Linguistic simplicity is always preferable to uncertain vocabulary
- Do NOT use the characters "ğ" or "ı"

NUMBER ACCURACY (CRITICAL):
- Preserve the EXACT semantic value of every number from the source material
- 40 = çil (NOT çardeh which means 14)
- 14 = çardeh
- "four decades" = nêzîkî çil sal
- "thousands" = bi hezaran
- If uncertain how to write a number in Kurmanji, keep the numeric form (e.g., "40") rather than risk changing its value
- NEVER transform a number in a way that changes the underlying quantity

GEOGRAPHIC TERMINOLOGY:
- Rojhilata Navîn = Middle East (NEVER "Rojava Navîn")
- Rojava = western Kurdistan / Kurdish region in Syria
- Bakur = northern Kurdistan / Kurdish region in Turkey
- Başûr = southern Kurdistan / Kurdistan Region of Iraq
- Rojhilat = eastern Kurdistan / Kurdish region in Iran

FACTUAL RULES:
- Use ONLY facts from the supplied stories
- Do NOT invent facts, quotes, or background context not in the sources
- Do NOT present Dengbej as a human journalist
- If a source provides only a headline with minimal detail, produce a SHORT bulletin
- Do NOT repeat a headline in different words merely to fill space

LENGTH AND REPETITION:
- Length must match available factual material — never pad
- A thin story (only headline + brief description) → 2-3 sentences maximum
- A detailed story → 3-5 sentences
- NEVER repeat the same fact in different words to increase length
- If all stories are about the same event, produce ONE concise combined segment
- A very short accurate broadcast is acceptable and preferable to a padded one

STRUCTURE:
- Opening: "Rojbaş. Ev Dengbej e. {date_str}."
- Tell the story/stories concisely with natural transitions if multiple
- Closing: "Ev bû Dengbej. Hêvî dikin ku sibê jî li gel we bin."

OUTPUT:
- Write ONLY the spoken text — no labels, no formatting, no stage directions
- The result should sound like a concise Kurdish radio news segment

SELF-CHECK (do this internally before outputting, do NOT include in output):
- No invented facts? No changed numbers? No English words? No invented vocabulary?
- No unnecessary repetition? Geographic terms correct? Overlapping stories consolidated?

STORIES:

{stories_text}

KURDISH BROADCAST SCRIPT:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=2000, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"Program script generation failed: {e}")
        return None


def store_program_script(program_id, date_str, briefing_date, script, telemetry, audio_url=None, audio_url_en=None, audio_url_ku=None):
    """Store generated script in the programs table."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        update_expr = "SET script_ku = :script, script_meta = :meta"
        expr_values = {
            ":script": script,
            ":meta": {
                "script_generated_at": now_iso,
                "model_id": MODEL_ID,
                "script_chars": len(script),
                "bedrock_input_tokens": telemetry.bedrock_input_tokens,
                "bedrock_output_tokens": telemetry.bedrock_output_tokens,
            },
        }

        if audio_url:
            update_expr += ", audio_url = :audio_url"
            expr_values[":audio_url"] = audio_url
        if audio_url_en:
            update_expr += ", audio_url_en = :audio_url_en"
            expr_values[":audio_url_en"] = audio_url_en
        if audio_url_ku:
            update_expr += ", audio_url_ku = :audio_url_ku"
            expr_values[":audio_url_ku"] = audio_url_ku

        programs_table.update_item(
            Key={"program_id": program_id, "briefing_date": briefing_date},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
        print(f"Program script stored: {program_id} ({len(script)} chars, audio_en={'yes' if audio_url_en else 'no'}, audio_ku={'yes' if audio_url_ku else 'no'})")
    except ClientError as e:
        print(f"Failed to store program script: {e}")
        raise


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

    # Build story summaries for the prompt — provide BOTH English and Kurdish
    story_blocks = []
    for i, story in enumerate(stories, 1):
        block = f"""Story {i}:
Headline: {story.get('headline', '')}
Category: {story.get('category', '')}
English summary: {story.get('summary_en', '')}
Kurdish summary: {story.get('summary_ku', '')}
Source: {story.get('primary_source', '')}"""
        story_blocks.append(block)

    stories_text = "\n\n".join(story_blocks)

    prompt = f"""You are composing a Kurmanji Kurdish daily news briefing for Dengbej audio service.

LANGUAGE AND STYLE:
- Write DIRECTLY in natural, fluent Kurmanji Kurdish — do NOT translate English sentence-by-sentence
- Use standard, widely understood Kurmanji vocabulary
- Write short-to-medium sentences suitable for being read aloud on radio
- Vary sentence structure and transition phrases — avoid repetition
- Use natural Kurdish number expressions: "sêzdeh kes" not "13 kes", "sê ji sed" not "%3"
- For currencies and measurements, use natural spoken forms: "heştê û çar dolar" not "84.64 dolar"
- Keep proper nouns in their recognized form (Netanyahu, Erdogan, Hormuz, Taneco)
- Use standard Kurdish political terminology where established
- Avoid mixing Turkish or English syntax into Kurdish sentences
- Avoid bookish or overly formal Arabic/Persian loans when simpler Kurdish exists
- Do NOT use the characters "ğ" or "ı" — these are Turkish, not Kurmanji

FACTUAL RULES:
- Use ONLY facts from the supplied stories — do NOT invent anything
- Preserve exact numbers, casualty figures, percentages, dates, and names
- When a source expresses uncertainty, keep that uncertainty in your text
- Do NOT add analysis, opinion, or interpretation beyond what sources state
- Do NOT invent quotations or attribute statements not in the source material
- Do NOT present Dengbej as a human journalist or eyewitness

STRUCTURE:
- Opening: "Rojbaş. Ev Dengbej e. Nûçeyên îro, {date_str}."
- Tell the five stories as one coherent program with varied transitions
- Do NOT start every transition with "Niha" — use variety: "Li aliyekî din...", "Derbarê...", "Di nûçeyên din de...", etc.
- Each story: 3-5 sentences, focused on key facts
- Closing: "Ev bû Dengbej. Hêvî dikin ku sibê jî li gel we bin."

OUTPUT:
- Write ONLY the spoken text — no stage directions, no labels, no formatting
- Target 700-1000 words of natural spoken Kurmanji
- The result should sound like a professional Kurdish radio news bulletin

TODAY'S STORIES (use as factual source material, not text to translate literally):

{stories_text}

KURDISH BROADCAST SCRIPT:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=3000, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"Broadcast script generation failed: {e}")
        return None


def store_script(briefing, script, date_str, telemetry, audio_url=None, audio_url_en=None, audio_url_ku=None):
    """Store the broadcast script and metadata in the briefing record."""
    try:
        generated_at = briefing.get("generated_at", "")
        now_iso = datetime.now(timezone.utc).isoformat()

        meta = {
            "script_generated_at": now_iso,
            "model_id": MODEL_ID,
            "script_chars": len(script),
            "tts_status": "completed" if audio_url else "pending",
            "tts_provider": "kurdish-tts" if audio_url_ku else ("polly-en" if audio_url_en else None),
            "audio_url": audio_url,
            "audio_url_en": audio_url_en,
            "audio_url_ku": audio_url_ku,
            "audio_duration_seconds": None,
            "bedrock_input_tokens": telemetry.bedrock_input_tokens,
            "bedrock_output_tokens": telemetry.bedrock_output_tokens,
        }

        briefings_table.update_item(
            Key={"briefing_date": date_str, "generated_at": generated_at},
            UpdateExpression="SET daily_audio_script_ku = :script, daily_audio_meta = :meta",
            ExpressionAttributeValues={
                ":script": script,
                ":meta": meta,
            },
        )
        print(f"Script stored for {date_str} ({len(script)} chars, audio_en={'yes' if audio_url_en else 'no'}, audio_ku={'yes' if audio_url_ku else 'no'})")
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


# ─── English Narration Generation ────────────────────────────────────────────

def generate_english_narration(stories, date_str, telemetry):
    """Generate a concise English narration for Polly synthesis from Today's 5."""
    story_blocks = []
    for i, story in enumerate(stories, 1):
        summary = story.get("summary_en", "")
        headline = story.get("headline", "")
        if summary:
            story_blocks.append(f"Story {i}: {headline}\n{summary}")
        else:
            story_blocks.append(f"Story {i}: {headline}")

    stories_text = "\n\n".join(story_blocks)

    prompt = f"""Write a concise English radio news briefing (90-120 seconds when read aloud) from these stories.

Structure:
- Opening: "Good day. This is Dengbej, your daily news briefing for {date_str}."
- Cover each story in 2-3 clear sentences. Use natural spoken English.
- Closing: "That's all for today's Dengbej briefing. See you tomorrow."

Rules:
- Write ONLY spoken text — no labels, no formatting
- Keep total length under 250 words
- Be factual, concise, and natural

STORIES:

{stories_text}

ENGLISH NARRATION:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=600, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"English narration generation failed: {e}")
        return None


def generate_program_narration_en(stories, program_id, date_str, telemetry):
    """Generate a short English narration for a topic program."""
    story_blocks = []
    for i, story in enumerate(stories, 1):
        headline = story.get("headline", "")
        desc = story.get("feed_description", "")
        story_blocks.append(f"Story {i}: {headline}\n{desc[:200]}")

    stories_text = "\n\n".join(story_blocks)

    prompt = f"""Write a short English radio news segment (60-90 seconds when read aloud) about the {program_id} program.

Structure:
- Opening: "This is Dengbej with your {program_id.replace('-', ' ')} update."
- Cover the stories concisely in 2-3 sentences each.
- Closing: "That's your {program_id.replace('-', ' ')} update from Dengbej."

Rules:
- Write ONLY spoken text — no labels, no formatting
- Keep total length under 200 words
- Be factual and natural

STORIES:

{stories_text}

ENGLISH NARRATION:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=500, telemetry=telemetry)
        return result.strip() if result else None
    except Exception as e:
        print(f"Program narration generation failed: {e}")
        return None


# ─── Polly TTS + S3 Upload ───────────────────────────────────────────────────

def synthesize_and_upload(text, key_prefix):
    """
    Synthesize text to speech via Polly (English, neural) and upload to S3.
    Returns the public S3 URL.
    """
    # Polly neural has a 3000 char limit per request
    if len(text) > 2900:
        text = text[:2900] + "."

    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId="Joanna",
        Engine="neural",
    )

    audio_data = response["AudioStream"].read()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    s3_key = f"{key_prefix}_{timestamp}.mp3"

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=audio_data,
        ContentType="audio/mpeg",
    )

    return f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
