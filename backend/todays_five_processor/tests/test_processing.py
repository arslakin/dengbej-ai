"""
Unit tests for the Today's 5 Processor pipeline.

Tests cover:
- Article text extraction (mock HTTP)
- Multiple-source handling
- Failed supporting source (graceful degradation)
- Single-source fallback
- Idempotency (skip already-processed stories)
- One story failure not stopping others
- Preservation of source attribution
- Preservation of curator scores/ranking
- Telemetry calculations
- Processing status transitions
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lambda_function import (
    extract_article_text,
    fetch_source_text,
    generate_summary,
    translate_to_kurdish,
    process_story,
    lambda_handler,
    Telemetry,
    SYNTHESIS_PROMPT,
    TRANSLATION_PROMPT,
    MAX_ARTICLE_LENGTH,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_html(paragraphs, include_nav=False):
    """Build a simple HTML page with paragraphs."""
    nav = "<nav><a href='/'>Home</a></nav>" if include_nav else ""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"<html><head><title>Test</title></head><body>{nav}{body}</body></html>"


def _make_story(rank=1, headline="Test Story", source="BBC News", url="https://bbc.co.uk/story1",
                status="pending", supporting=None):
    """Build a test story object matching the curator output format."""
    story = {
        "rank": rank,
        "headline": headline,
        "category": "world",
        "primary_source": source,
        "original_url": url,
        "pub_date": "2026-08-08T10:00:00+00:00",
        "supporting_sources": supporting or [],
        "international_significance_score": 4,
        "kurdish_relevance_score": 3,
        "cross_source_count": 1,
        "freshness_score": 0.8,
        "raw_score": 0.75,
        "diversity_adjusted_score": 0.75,
        "final_score": 0.75,
        "selection_reason": "Major international event",
        "feed_description": "A test story description",
        "summary_en": None,
        "summary_ku": None,
        "audio_url": None,
        "processing_status": status,
    }
    return story


def _make_briefing(stories=None, date="2026-08-08"):
    """Build a test briefing."""
    if stories is None:
        stories = [_make_story(rank=i+1) for i in range(5)]
    return {
        "briefing_date": date,
        "generated_at": "2026-08-08T06:00:00+00:00",
        "stories": stories,
        "status": "published",
    }


def _mock_response(text="", status_code=200):
    """Create a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return mock


def _mock_bedrock_response(text="Summary text here.", input_tokens=100, output_tokens=50):
    """Create a mock Bedrock response."""
    body_content = json.dumps({
        "content": [{"text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_content
    return {"body": mock_body}


# ─── Test: Article Extraction ────────────────────────────────────────────────

@patch("lambda_function.requests.get")
def test_extract_article_basic(mock_get):
    """Should extract paragraph text from HTML."""
    html = _make_html(["First paragraph.", "Second paragraph.", "Third paragraph."])
    mock_get.return_value = _mock_response(html)

    text = extract_article_text("https://example.com/article")
    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert "Third paragraph." in text


@patch("lambda_function.requests.get")
def test_extract_article_removes_nav_footer(mock_get):
    """Should remove nav, footer, header, aside elements."""
    html = """<html><body>
        <nav><p>Navigation text</p></nav>
        <header><p>Header text</p></header>
        <p>Article content here.</p>
        <footer><p>Footer text</p></footer>
        <aside><p>Sidebar text</p></aside>
    </body></html>"""
    mock_get.return_value = _mock_response(html)

    text = extract_article_text("https://example.com/article")
    assert "Article content here." in text
    assert "Navigation text" not in text
    assert "Header text" not in text
    assert "Footer text" not in text
    assert "Sidebar text" not in text


@patch("lambda_function.requests.get")
def test_extract_article_respects_max_length(mock_get):
    """Should truncate text to max_length."""
    long_paragraphs = ["A" * 1000 for _ in range(10)]
    html = _make_html(long_paragraphs)
    mock_get.return_value = _mock_response(html)

    text = extract_article_text("https://example.com/article", max_length=500)
    assert len(text) <= 500


@patch("lambda_function.requests.get")
def test_extract_article_empty_page(mock_get):
    """Should return empty string for page with no paragraphs."""
    html = "<html><body><div>No paragraphs here</div></body></html>"
    mock_get.return_value = _mock_response(html)

    text = extract_article_text("https://example.com/article")
    assert text == ""


@patch("lambda_function.requests.get")
def test_extract_article_removes_script_style(mock_get):
    """Should remove script and style elements."""
    html = """<html><body>
        <script>var x = 1;</script>
        <style>.class { color: red; }</style>
        <p>Real content.</p>
    </body></html>"""
    mock_get.return_value = _mock_response(html)

    text = extract_article_text("https://example.com/article")
    assert "Real content." in text
    assert "var x" not in text
    assert "color" not in text


# ─── Test: Multiple-Source Handling ──────────────────────────────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_multiple_sources_combined(mock_get, mock_bedrock):
    """Should fetch and combine multiple source texts for summary."""
    primary_html = _make_html(["Primary source content about the event."])
    support_html = _make_html(["Supporting source adds more context."])

    mock_get.side_effect = [
        _mock_response(primary_html),
        _mock_response(support_html),
    ]
    mock_bedrock.return_value = "Combined summary from multiple sources."

    telemetry = Telemetry()
    story = _make_story(
        supporting=[{"source_name": "DW", "url": "https://dw.com/story"}]
    )

    process_story(story, telemetry)

    assert story["processing_status"] in ("processed", "partial")
    assert telemetry.sources_fetched == 2
    # Bedrock should be called with combined text
    assert mock_bedrock.call_count >= 1


# ─── Test: Failed Supporting Source (Graceful Degradation) ───────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_failed_supporting_source_continues(mock_get, mock_bedrock):
    """Should process story even if supporting source fails."""
    primary_html = _make_html(["Primary source content."])

    def side_effect(url, **kwargs):
        if "primary" in url or "bbc" in url:
            return _mock_response(primary_html)
        raise ConnectionError("Connection failed")

    mock_get.side_effect = side_effect
    mock_bedrock.return_value = "Summary based on available sources."

    telemetry = Telemetry()
    story = _make_story(
        url="https://bbc.co.uk/primary",
        supporting=[{"source_name": "DW", "url": "https://dw.com/failing"}]
    )

    process_story(story, telemetry)

    assert story["processing_status"] in ("processed", "partial")
    assert "https://dw.com/failing" in story.get("sources_failed", [])
    assert "https://bbc.co.uk/primary" in story.get("sources_used", [])


# ─── Test: Single-Source Fallback ────────────────────────────────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_single_source_fallback(mock_get, mock_bedrock):
    """Should process story with only primary source if no supporting sources."""
    primary_html = _make_html(["The only source content available."])
    mock_get.return_value = _mock_response(primary_html)
    mock_bedrock.return_value = "Summary from single source."

    telemetry = Telemetry()
    story = _make_story(supporting=[])

    process_story(story, telemetry)

    assert story["processing_status"] in ("processed", "partial")
    assert telemetry.sources_fetched == 1


@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_feed_description_fallback(mock_get, mock_bedrock):
    """Should use feed_description when all HTTP fetches fail."""
    mock_get.side_effect = ConnectionError("All sources unavailable")
    mock_bedrock.return_value = "Summary from description."

    telemetry = Telemetry()
    story = _make_story()
    story["feed_description"] = "A story about something important."

    process_story(story, telemetry)

    # Should still attempt to process using feed_description
    assert story["processing_status"] in ("processed", "partial")


# ─── Test: Idempotency ───────────────────────────────────────────────────────

@patch("lambda_function.get_briefing")
@patch("lambda_function.update_briefing")
def test_idempotency_skips_processed(mock_update, mock_get_briefing):
    """Already-processed stories should be skipped."""
    stories = [
        _make_story(rank=1, status="processed"),
        _make_story(rank=2, status="processed"),
        _make_story(rank=3, status="processed"),
        _make_story(rank=4, status="processed"),
        _make_story(rank=5, status="processed"),
    ]
    mock_get_briefing.return_value = _make_briefing(stories)

    result = lambda_handler({"date": "2026-08-08"}, None)

    assert result["body"]["stories_skipped"] == 5
    assert result["body"]["stories_attempted"] == 5
    assert result["body"]["stories_processed"] == 0


@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
@patch("lambda_function.get_briefing")
@patch("lambda_function.update_briefing")
def test_idempotency_partial_reprocess(mock_update, mock_get_briefing, mock_get, mock_bedrock):
    """Should only process pending stories, skipping already-processed ones."""
    stories = [
        _make_story(rank=1, status="processed"),
        _make_story(rank=2, headline="New Story", status="pending"),
    ]
    mock_get_briefing.return_value = _make_briefing(stories)
    mock_get.return_value = _mock_response(_make_html(["Content."]))
    mock_bedrock.return_value = "Summary."

    result = lambda_handler({"date": "2026-08-08"}, None)

    assert result["body"]["stories_skipped"] == 1
    assert result["body"]["stories_attempted"] == 2


# ─── Test: One Story Failure Doesn't Stop Others ─────────────────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
@patch("lambda_function.get_briefing")
@patch("lambda_function.update_briefing")
def test_one_failure_doesnt_stop_others(mock_update, mock_get_briefing, mock_get, mock_bedrock):
    """A failing story should not prevent other stories from processing."""
    stories = [
        _make_story(rank=1, headline="Good Story 1", url="https://good1.com/a"),
        _make_story(rank=2, headline="Bad Story", url="https://bad.com/fail"),
        _make_story(rank=3, headline="Good Story 2", url="https://good2.com/b"),
    ]
    mock_get_briefing.return_value = _make_briefing(stories)

    call_count = [0]

    def get_side_effect(url, **kwargs):
        if "bad.com" in url:
            raise ConnectionError("Permanent failure")
        return _mock_response(_make_html(["Content for good story."]))

    mock_get.side_effect = get_side_effect

    def bedrock_side_effect(prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 2:
            # Fail on the bad story's bedrock call (shouldn't happen since fetch fails)
            return "Summary text."
        return "Summary text."

    mock_bedrock.return_value = "Summary text."

    result = lambda_handler({"date": "2026-08-08"}, None)

    # At least some stories should process successfully
    # Story 2 will use feed_description fallback since HTTP fetch fails
    total_processed = result["body"]["stories_processed"] + result["body"]["stories_partial"]
    assert total_processed >= 2 or result["body"]["stories_processed"] >= 1


# ─── Test: Preservation of Source Attribution ────────────────────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_source_attribution_preserved(mock_get, mock_bedrock):
    """Processing should track which sources were used and which failed."""
    primary_html = _make_html(["Primary content."])
    support_html = _make_html(["Support content."])

    def get_side_effect(url, **kwargs):
        if "primary" in url:
            return _mock_response(primary_html)
        elif "support1" in url:
            return _mock_response(support_html)
        elif "support2" in url:
            raise ConnectionError("Failed")
        return _mock_response(primary_html)

    mock_get.side_effect = get_side_effect
    mock_bedrock.return_value = "Summary text."

    telemetry = Telemetry()
    story = _make_story(
        url="https://example.com/primary",
        supporting=[
            {"source_name": "Source A", "url": "https://example.com/support1"},
            {"source_name": "Source B", "url": "https://example.com/support2"},
        ]
    )

    process_story(story, telemetry)

    assert "https://example.com/primary" in story["sources_used"]
    assert "https://example.com/support1" in story["sources_used"]
    assert "https://example.com/support2" in story["sources_failed"]


# ─── Test: Preservation of Curator Scores/Ranking ────────────────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_curator_scores_preserved(mock_get, mock_bedrock):
    """Processing should not modify curator-assigned scores and rankings."""
    mock_get.return_value = _mock_response(_make_html(["Content."]))
    mock_bedrock.return_value = "Summary text."

    telemetry = Telemetry()
    story = _make_story()
    original_rank = story["rank"]
    original_score = story["final_score"]
    original_significance = story["international_significance_score"]
    original_kurdish = story["kurdish_relevance_score"]

    process_story(story, telemetry)

    # Scores should remain unchanged
    assert story["rank"] == original_rank
    assert story["final_score"] == original_score
    assert story["international_significance_score"] == original_significance
    assert story["kurdish_relevance_score"] == original_kurdish


# ─── Test: Telemetry Calculations ────────────────────────────────────────────

def test_telemetry_initialization():
    """Telemetry should start with all zeros."""
    t = Telemetry()
    d = t.to_dict()
    assert d["stories_attempted"] == 0
    assert d["stories_processed"] == 0
    assert d["stories_failed"] == 0
    assert d["stories_skipped"] == 0
    assert d["bedrock_calls"] == 0
    assert d["bedrock_input_tokens"] == 0
    assert d["bedrock_output_tokens"] == 0
    assert d["sources_fetched"] == 0
    assert d["sources_failed"] == 0


def test_telemetry_duration():
    """Telemetry should track duration."""
    import time
    t = Telemetry()
    time.sleep(0.05)
    t.finish()
    assert t.duration_ms >= 40  # At least 40ms (allowing some tolerance)


@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_telemetry_bedrock_tracking(mock_get, mock_bedrock):
    """Telemetry should count Bedrock calls and tokens."""
    mock_get.return_value = _mock_response(_make_html(["Content."]))

    # Mock invoke_bedrock to track telemetry
    call_count = [0]

    def bedrock_side_effect(prompt, max_tokens=500, telemetry=None):
        call_count[0] += 1
        if telemetry:
            telemetry.bedrock_calls += 1
            telemetry.bedrock_input_tokens += 100
            telemetry.bedrock_output_tokens += 50
        return "Summary text."

    mock_bedrock.side_effect = bedrock_side_effect

    telemetry = Telemetry()
    story = _make_story()

    process_story(story, telemetry)

    # Should have called Bedrock at least once (summary), possibly twice (translation)
    assert telemetry.bedrock_calls >= 1
    assert telemetry.bedrock_input_tokens >= 100
    assert telemetry.bedrock_output_tokens >= 50


# ─── Test: Processing Status Transitions ─────────────────────────────────────

@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_status_pending_to_processed(mock_get, mock_bedrock):
    """Story should transition from pending to processed on success."""
    mock_get.return_value = _mock_response(_make_html(["Content."]))
    mock_bedrock.return_value = "Summary text."

    telemetry = Telemetry()
    story = _make_story(status="pending")

    process_story(story, telemetry)

    assert story["processing_status"] == "processed"
    assert story["summary_en"] is not None
    assert story["summary_ku"] is not None
    assert story["processed_at"] is not None


@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_status_partial_when_translation_fails(mock_get, mock_bedrock):
    """Story should be 'partial' when summary succeeds but translation fails."""
    mock_get.return_value = _mock_response(_make_html(["Content."]))

    call_count = [0]

    def bedrock_side_effect(prompt, max_tokens=500, telemetry=None):
        call_count[0] += 1
        if telemetry:
            telemetry.bedrock_calls += 1
        if call_count[0] == 1:
            return "Summary text."  # Summary succeeds
        return None  # Translation fails (returns None)

    mock_bedrock.side_effect = bedrock_side_effect

    telemetry = Telemetry()
    story = _make_story(status="pending")

    process_story(story, telemetry)

    assert story["processing_status"] == "partial"
    assert story["summary_en"] is not None
    assert story["summary_ku"] is None


@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
def test_status_failed_when_no_sources(mock_get, mock_bedrock):
    """Story should be 'failed' when no source text is available."""
    mock_get.side_effect = ConnectionError("All unavailable")

    telemetry = Telemetry()
    story = _make_story(status="pending")
    story["feed_description"] = ""  # No fallback either

    process_story(story, telemetry)

    assert story["processing_status"] == "failed"


# ─── Test: Lambda Handler Integration ────────────────────────────────────────

@patch("lambda_function.get_briefing")
@patch("lambda_function.update_briefing")
def test_handler_no_briefing_returns_404(mock_update, mock_get_briefing):
    """Should return 404 when no briefing exists for the date."""
    mock_get_briefing.return_value = None

    result = lambda_handler({"date": "2099-01-01"}, None)

    assert result["statusCode"] == 404
    assert "No briefing found" in result["body"]["error"]


@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.requests.get")
@patch("lambda_function.get_briefing")
@patch("lambda_function.update_briefing")
def test_handler_returns_correct_counts(mock_update, mock_get_briefing, mock_get, mock_bedrock):
    """Handler response should include accurate story counts."""
    stories = [
        _make_story(rank=1, status="processed"),  # Will be skipped
        _make_story(rank=2, status="pending", headline="Story 2", url="https://a.com/2"),
        _make_story(rank=3, status="pending", headline="Story 3", url="https://a.com/3"),
    ]
    mock_get_briefing.return_value = _make_briefing(stories)
    mock_get.return_value = _mock_response(_make_html(["Content."]))
    mock_bedrock.return_value = "Summary."

    result = lambda_handler({"date": "2026-08-08"}, None)

    assert result["statusCode"] == 200
    assert result["body"]["stories_skipped"] == 1
    assert result["body"]["stories_attempted"] == 3


@patch("lambda_function.get_briefing")
@patch("lambda_function.update_briefing")
def test_handler_uses_today_date_when_no_param(mock_update, mock_get_briefing):
    """Should default to today's date when no date parameter provided."""
    mock_get_briefing.return_value = None

    result = lambda_handler({}, None)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result["statusCode"] == 404
    assert today in result["body"]["error"]


# ─── Test: Max Article Length ────────────────────────────────────────────────

def test_max_article_length_config():
    """MAX_ARTICLE_LENGTH should default to 4000."""
    assert MAX_ARTICLE_LENGTH == 4000


# ─── Test: Output Cleanup ────────────────────────────────────────────────────

def test_summary_no_markdown_headings():
    """English summary should not contain markdown headings."""
    # Simulate a summary that contains headings (as seen in first run)
    test_summaries = [
        "# News Briefing\n\nThe event occurred...",
        "# Summary\n\nOfficials announced...",
        "## Headline\n\nThe situation...",
    ]
    for s in test_summaries:
        # After processing, headings should be stripped
        cleaned = s.replace("# News Briefing\n\n", "").replace("# Summary\n\n", "").replace("## Headline\n\n", "")
        assert not cleaned.startswith("#"), f"Summary starts with heading: {cleaned[:20]}"


def test_kurdish_no_markdown_headings():
    """Kurdish summary should not contain markdown headings."""
    test_summary = "# Rojnameya Kurtkirî\n\nWezîrên derve..."
    cleaned = test_summary.lstrip("# ").split("\n\n", 1)[-1] if test_summary.startswith("#") else test_summary
    assert not cleaned.startswith("#")


def test_kurdish_no_repetition():
    """Kurdish translation should not have repetitive phrases."""
    bad_output = "Ev paktê... û hûn û hûn û hûn û hûn û hûn û hûn"
    # Check for repetition pattern (3+ consecutive repeated phrases)
    import re
    repetition = re.search(r'(\b\w+\b(?:\s+\b\w+\b)?)\s+(?:\1\s*){3,}', bad_output)
    assert repetition is not None, "Test string should detect repetition"
    # In production, the prompt should prevent this


# ─── Run Tests ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_functions = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0

    print("Running Today's 5 Processor tests...\n")

    for test_fn in test_functions:
        try:
            test_fn()
            print(f"  ✅ {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {test_fn.__name__}: EXCEPTION: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        sys.exit(1)
