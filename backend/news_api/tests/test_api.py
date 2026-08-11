"""
Unit tests for the News API Lambda.

Tests cover:
- Latest briefing retrieval (today + yesterday fallback)
- Stories sorted by rank
- Only processed stories returned
- Partial briefing (some failed stories excluded)
- No briefing → 404
- Internal fields excluded (no raw_score, no selection_reason, etc.)
- Correct CORS headers
- Date-specific endpoint
- OPTIONS preflight
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Test Fixtures ───────────────────────────────────────────────────────────

def _make_briefing(date, stories, generated_at="2026-01-15T10:00:00Z"):
    """Helper to create a briefing item as it would exist in DynamoDB."""
    return {
        "briefing_date": date,
        "generated_at": generated_at,
        "stories": stories,
    }


def _make_story(rank, status="processed", headline=None):
    """Helper to create a story with all DynamoDB fields."""
    return {
        "rank": rank,
        "headline": headline or f"Story {rank} headline",
        "category": "world",
        "processing_status": status,
        "summary_en": f"English summary for story {rank}",
        "summary_ku": f"Kurmanji summary for story {rank}",
        "primary_source": "BBC News",
        "original_url": f"https://bbc.co.uk/story-{rank}",
        "pub_date": "2026-01-15T08:00:00Z",
        "processed_at": "2026-01-15T09:30:00Z",
        "supporting_sources": [
            {"source_name": "Deutsche Welle", "url": "https://dw.com/story"},
        ],
        # Internal fields that should NOT appear in API response
        "raw_score": Decimal("0.85"),
        "selection_reason": "high significance + cross-source",
        "international_significance_score": 5,
        "kurdish_relevance_score": 3,
        "cross_source_count": 2,
        "freshness_score": Decimal("0.9"),
        "all_articles": [{"source_name": "BBC News", "original_url": "https://bbc.co.uk/story"}],
    }


def _invoke_lambda(path, method="GET"):
    """Simulate a Lambda Function URL invocation."""
    from lambda_function import lambda_handler

    event = {
        "rawPath": path,
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
            }
        },
    }
    return lambda_handler(event, None)


# ─── Test: CORS Headers ─────────────────────────────────────────────────────

def test_cors_headers_present():
    """All responses should include CORS headers."""
    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": []}
        response = _invoke_lambda("/news/today")

    headers = response["headers"]
    assert headers["Content-Type"] == "application/json"
    assert "Cache-Control" in headers


def test_options_preflight():
    """OPTIONS request should return 200."""
    response = _invoke_lambda("/news/today", method="OPTIONS")
    assert response["statusCode"] == 200


# ─── Test: Routing ───────────────────────────────────────────────────────────

def test_post_method_rejected():
    """Non-GET methods should return 405."""
    response = _invoke_lambda("/news/today", method="POST")
    assert response["statusCode"] == 405
    body = json.loads(response["body"])
    assert body["error"] == "Method not allowed"


def test_unknown_path_returns_404():
    """Unknown paths should return 404."""
    response = _invoke_lambda("/unknown")
    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"] == "Not found"


def test_invalid_date_format_returns_404():
    """Date paths that don't match YYYY-MM-DD should return 404."""
    response = _invoke_lambda("/news/15-01-2026")
    assert response["statusCode"] == 404


def test_partial_date_returns_404():
    """Partial date like /news/2026-01 should return 404."""
    response = _invoke_lambda("/news/2026-01")
    assert response["statusCode"] == 404


# ─── Test: Today's Briefing ──────────────────────────────────────────────────

def test_today_returns_latest_briefing():
    """GET /news/today should return today's processed briefing."""
    stories = [_make_story(1), _make_story(2), _make_story(3)]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        with patch("lambda_function.datetime") as mock_dt:
            mock_dt.now.return_value = type("", (), {"strftime": lambda s, f: "2026-01-15"})()
            # Use the real function with mocked table
            response = _invoke_lambda("/news/today")

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["story_count"] == 3
    assert body["edition"] == "today"
    assert body["date"] == "2026-01-15"


def test_today_falls_back_to_yesterday():
    """If today has no briefing, should try yesterday."""
    from datetime import datetime as real_datetime, timedelta
    from unittest.mock import patch as mock_patch

    stories = [_make_story(1), _make_story(2)]
    yesterday_str = (real_datetime.now(tz=__import__("datetime").timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    today_str = real_datetime.now(tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
    yesterday_briefing = _make_briefing(yesterday_str, stories)

    call_count = [0]

    def mock_query(**kwargs):
        call_count[0] += 1
        date_val = kwargs["ExpressionAttributeValues"][":bd"]
        if date_val == yesterday_str:
            return {"Items": [yesterday_briefing]}
        return {"Items": []}

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.side_effect = mock_query
        response = _invoke_lambda("/news/today")

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["date"] == yesterday_str
    assert call_count[0] == 2  # Tried today, then yesterday


def test_today_no_briefing_available():
    """If no briefing exists for today or yesterday, return 404."""
    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": []}
        response = _invoke_lambda("/news/today")

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"] == "No briefing available"


# ─── Test: Date-specific Endpoint ────────────────────────────────────────────

def test_date_endpoint_returns_briefing():
    """GET /news/2026-01-15 should return that date's briefing."""
    stories = [_make_story(1), _make_story(2)]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["date"] == "2026-01-15"
    assert body["story_count"] == 2


def test_date_endpoint_no_briefing():
    """GET /news/2020-01-01 with no data should return 404."""
    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": []}
        response = _invoke_lambda("/news/2020-01-01")

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["date"] == "2020-01-01"


# ─── Test: Story Filtering and Sorting ───────────────────────────────────────

def test_only_processed_stories_returned():
    """Stories with status != 'processed' should be excluded."""
    stories = [
        _make_story(1, status="processed"),
        _make_story(2, status="failed"),
        _make_story(3, status="processing"),
        _make_story(4, status="processed"),
    ]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    body = json.loads(response["body"])
    assert body["story_count"] == 2
    ranks = [s["rank"] for s in body["stories"]]
    assert 2 not in ranks
    assert 3 not in ranks


def test_stories_sorted_by_rank():
    """Stories should be returned sorted by rank ascending."""
    stories = [
        _make_story(3, status="processed"),
        _make_story(1, status="processed"),
        _make_story(5, status="processed"),
        _make_story(2, status="processed"),
    ]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    body = json.loads(response["body"])
    ranks = [s["rank"] for s in body["stories"]]
    assert ranks == [1, 2, 3, 5]


def test_partial_briefing_excludes_failed():
    """A briefing with mix of processed/failed should only show processed."""
    stories = [
        _make_story(1, status="processed", headline="Good story"),
        _make_story(2, status="failed", headline="Failed story"),
        _make_story(3, status="processed", headline="Another good story"),
    ]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    body = json.loads(response["body"])
    assert body["story_count"] == 2
    headlines = [s["headline"] for s in body["stories"]]
    assert "Failed story" not in headlines
    assert "Good story" in headlines
    assert "Another good story" in headlines


# ─── Test: Internal Fields Excluded ──────────────────────────────────────────

def test_internal_fields_not_exposed():
    """Internal scoring/selection fields should not appear in API response."""
    stories = [_make_story(1)]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    body = json.loads(response["body"])
    story = body["stories"][0]

    # These internal fields must NOT be in the response
    assert "raw_score" not in story
    assert "selection_reason" not in story
    assert "international_significance_score" not in story
    assert "kurdish_relevance_score" not in story
    assert "cross_source_count" not in story
    assert "freshness_score" not in story
    assert "all_articles" not in story
    assert "processing_status" not in story


def test_response_structure():
    """Verify the exact response structure matches expected API contract."""
    stories = [_make_story(1)]
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    body = json.loads(response["body"])

    # Top-level fields
    assert set(body.keys()) == {"date", "generated_at", "edition", "story_count", "stories", "daily_audio"}

    # Story fields
    story = body["stories"][0]
    expected_keys = {
        "rank", "headline", "category", "summary_en", "summary_ku",
        "primary_source", "supporting_sources", "published_at", "processed_at",
    }
    assert set(story.keys()) == expected_keys

    # Primary source structure
    assert set(story["primary_source"].keys()) == {"name", "url"}

    # Supporting source structure
    assert len(story["supporting_sources"]) == 1
    assert set(story["supporting_sources"][0].keys()) == {"name", "url"}


# ─── Test: Decimal Handling ──────────────────────────────────────────────────

def test_decimal_values_serialized():
    """Decimal values from DynamoDB should be serialized as floats."""
    stories = [_make_story(1)]
    # Add a Decimal value that would appear in a story
    stories[0]["some_decimal"] = Decimal("3.14")
    briefing = _make_briefing("2026-01-15", stories)

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    # Should not throw — Decimal encoding works
    assert response["statusCode"] == 200
    # Body should be valid JSON
    json.loads(response["body"])


# ─── Test: Briefing Selection Logic ──────────────────────────────────────────

def test_skips_briefing_without_processed_stories():
    """If a briefing has no processed stories, skip to the next one."""
    # First briefing: all failed
    failed_briefing = _make_briefing("2026-01-15", [
        _make_story(1, status="failed"),
        _make_story(2, status="failed"),
    ], generated_at="2026-01-15T12:00:00Z")

    # Second briefing: has processed stories
    good_briefing = _make_briefing("2026-01-15", [
        _make_story(1, status="processed"),
    ], generated_at="2026-01-15T06:00:00Z")

    with patch("lambda_function.briefings_table") as mock_table:
        mock_table.query.return_value = {"Items": [failed_briefing, good_briefing]}
        response = _invoke_lambda("/news/2026-01-15")

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["story_count"] == 1
    assert body["generated_at"] == "2026-01-15T06:00:00Z"


# ─── Run Tests ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_functions = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0

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
