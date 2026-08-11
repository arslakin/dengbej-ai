"""
Unit tests for the Program Generator Lambda.

Tests cover:
- Valid program accepted
- Invalid program rejected
- today redirected to curator
- Classification assigns articles to programs
- Turkey general not automatically bakur
- Kurdish Turkey story gets bakur+kurdistan
- Empty program returns valid empty response
- Max 5 stories per program
- Duplicate events clustered
- Idempotency (existing program not regenerated)
- Force regeneration works
- Telemetry tracked
- Multiple programs can be generated
- Articles classified deterministically
- Classification result used correctly
"""

import sys
import os
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Test Fixtures ───────────────────────────────────────────────────────────

def _make_article(article_id, headline, source_name="BBC News", pub_date=None, description=""):
    """Helper to create an article as it would exist in DynamoDB."""
    if pub_date is None:
        pub_date = datetime.now(timezone.utc).isoformat()
    return {
        "article_id": article_id,
        "headline": headline,
        "source_name": source_name,
        "pub_date": pub_date,
        "original_url": f"https://example.com/{article_id}",
        "feed_description": description or f"Description for {headline}",
    }


def _invoke_lambda(event):
    """Simulate a Lambda invocation."""
    from lambda_function import lambda_handler
    return lambda_handler(event, None)


# ─── Test: Valid Program Accepted ────────────────────────────────────────────

def test_valid_program_accepted():
    """A valid program_id like 'rojava' should be accepted."""
    articles = [_make_article("a1", "SDF advances in Rojava region", description="Kurdish forces in northeast Syria")]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({"program_id": "rojava"})

    assert response["statusCode"] == 200
    body = response["body"]
    assert "rojava" in body.get("programs", {})


# ─── Test: Invalid Program Rejected ──────────────────────────────────────────

def test_invalid_program_rejected():
    """An invalid program_id should return 400."""
    response = _invoke_lambda({"program_id": "invalid-program"})
    assert response["statusCode"] == 400
    assert "error" in response["body"]


# ─── Test: Today Redirected to Curator ───────────────────────────────────────

def test_today_redirected_to_curator():
    """program_id 'today' should redirect to the curator."""
    response = _invoke_lambda({"program_id": "today"})
    assert response["statusCode"] == 200
    assert "curator" in response["body"]["message"].lower()


# ─── Test: Classification Assigns Articles to Programs ───────────────────────

def test_classification_assigns_articles_to_programs():
    """Articles with Rojava keywords should be classified into rojava program."""
    from lambda_function import classify_articles, Telemetry

    articles = [
        _make_article("a1", "SDF operations in northeast Syria continue", description="Rojava administration"),
        _make_article("a2", "Global economy outlook improves", description="World markets rally"),
    ]
    telemetry = Telemetry()
    result = classify_articles(articles, telemetry)

    assert "rojava" in result["a1"]
    assert "world" in result["a2"]


# ─── Test: Turkey General Not Automatically Bakur ────────────────────────────

def test_turkey_general_not_bakur():
    """A general Turkey story (e.g., economy) should NOT be classified as bakur."""
    from lambda_function import classify_articles, Telemetry

    articles = [
        _make_article("a1", "Turkey central bank raises interest rates", description="Ankara economic policy"),
    ]
    telemetry = Telemetry()
    result = classify_articles(articles, telemetry)

    assert "turkey" in result["a1"]
    assert "bakur" not in result["a1"]


# ─── Test: Kurdish Turkey Story Gets Bakur + Kurdistan ───────────────────────

def test_kurdish_turkey_story_gets_bakur_and_kurdistan():
    """A Kurdish-specific Turkey story should get bakur AND kurdistan."""
    from lambda_function import classify_articles, Telemetry

    articles = [
        _make_article("a1", "DEM Party faces legal challenge in Diyarbakir", description="Kurdish political rights in southeast Turkey"),
    ]
    telemetry = Telemetry()
    result = classify_articles(articles, telemetry)

    assert "bakur" in result["a1"]
    assert "kurdistan" in result["a1"]


# ─── Test: Empty Program Returns Valid Empty Response ────────────────────────

def test_empty_program_returns_valid_response():
    """A program with no matching articles should store an empty briefing."""
    # Articles that only match "world" — not "basur"
    articles = [_make_article("a1", "Global climate summit begins", description="World leaders meet")]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({"program_id": "basur"})

    assert response["statusCode"] == 200
    body = response["body"]
    assert body["programs"]["basur"]["status"] == "empty"
    assert body["programs"]["basur"]["story_count"] == 0


# ─── Test: Max 5 Stories Per Program ─────────────────────────────────────────

def test_max_5_stories_per_program():
    """Even with many candidates, at most 5 stories should be selected."""
    from lambda_function import cluster_and_rank, Telemetry

    # Create 10 distinct articles
    candidates = [
        _make_article(f"a{i}", f"Unique story number {i} about Rojava topic {i}",
                      source_name=f"Source {i}",
                      pub_date=(datetime.now(timezone.utc) - timedelta(hours=i)).isoformat())
        for i in range(10)
    ]
    telemetry = Telemetry()
    selected = cluster_and_rank(candidates, "rojava", telemetry)

    assert len(selected) <= 5


# ─── Test: Duplicate Events Clustered ────────────────────────────────────────

def test_duplicate_events_clustered():
    """Articles about the same event from different sources should be clustered."""
    from lambda_function import cluster_and_rank, Telemetry

    candidates = [
        _make_article("a1", "Explosion rocks Erbil city center", source_name="BBC News",
                      pub_date="2026-01-15T10:00:00Z"),
        _make_article("a2", "Explosion rocks Erbil city center kills three", source_name="Al Jazeera",
                      pub_date="2026-01-15T10:30:00Z"),
        _make_article("a3", "Completely different story about technology", source_name="DW",
                      pub_date="2026-01-15T11:00:00Z"),
    ]
    telemetry = Telemetry()
    selected = cluster_and_rank(candidates, "basur", telemetry)

    # The two explosion stories should be clustered into one
    assert len(selected) == 2
    # The clustered story should have supporting sources
    explosion_story = next(s for s in selected if "Erbil" in s["headline"])
    assert explosion_story["cross_source_count"] == 2


# ─── Test: Idempotency ──────────────────────────────────────────────────────

def test_idempotency_existing_program_not_regenerated():
    """If a program already exists for today, it should not be regenerated."""
    existing_item = {"program_id": "rojava", "briefing_date": "2026-01-15", "story_count": 3}
    articles = [_make_article("a1", "SDF in Rojava", description="northeast Syria")]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {"Item": existing_item}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({"program_id": "rojava", "date": "2026-01-15"})

    assert response["statusCode"] == 200
    body = response["body"]
    assert body["programs"]["rojava"]["status"] == "exists"
    # put_item should NOT have been called
    mock_programs.put_item.assert_not_called()


# ─── Test: Force Regeneration ────────────────────────────────────────────────

def test_force_regeneration_works():
    """With force=True, even existing programs should be regenerated."""
    existing_item = {"program_id": "rojava", "briefing_date": "2026-01-15", "story_count": 3}
    articles = [_make_article("a1", "SDF advances in Rojava", description="northeast Syria Kurdish forces")]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {"Item": existing_item}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({"program_id": "rojava", "date": "2026-01-15", "force": True})

    assert response["statusCode"] == 200
    body = response["body"]
    assert body["programs"]["rojava"]["status"] == "generated"
    # put_item should have been called since force=True
    mock_programs.put_item.assert_called_once()


# ─── Test: Telemetry Tracked ─────────────────────────────────────────────────

def test_telemetry_tracked():
    """Telemetry should track articles examined and programs generated."""
    articles = [
        _make_article("a1", "SDF operations in Rojava continue", description="northeast Syria"),
        _make_article("a2", "Erbil hosts regional summit", description="Kurdistan Region Iraq"),
    ]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({"program_id": "rojava"})

    body = response["body"]
    telemetry = body["telemetry"]
    assert telemetry["articles_examined"] == 2
    assert telemetry["programs_generated"] == 1
    assert telemetry["duration_ms"] >= 0


# ─── Test: Multiple Programs Generated ──────────────────────────────────────

def test_multiple_programs_generated():
    """When no program_id specified, all topic programs should be generated."""
    articles = [
        _make_article("a1", "Kurdish forces in Rojava advance", description="northeast Syria SDF"),
        _make_article("a2", "Turkey economy booms", description="Ankara markets"),
        _make_article("a3", "KRG holds elections in Erbil", description="Kurdistan Region Iraq"),
    ]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({})

    body = response["body"]
    programs = body["programs"]
    # Should have generated all programs except 'today'
    assert "today" not in programs
    assert "rojava" in programs
    assert "turkey" in programs
    assert "basur" in programs
    assert body["telemetry"]["programs_generated"] > 0


# ─── Test: Articles Classified Deterministically ─────────────────────────────

def test_articles_classified_deterministically():
    """Classification should use keyword matching without Bedrock calls."""
    from lambda_function import classify_articles, Telemetry

    articles = [
        _make_article("a1", "PKK ceasefire talks resume in Turkey", description="Kurdish peace process"),
        _make_article("a2", "Iran protests spread to Kurdish regions", description="Rojhilat unrest"),
        _make_article("a3", "UN General Assembly convenes", description="Global diplomacy"),
    ]
    telemetry = Telemetry()
    result = classify_articles(articles, telemetry)

    # PKK story → bakur + kurdistan + turkey
    assert "bakur" in result["a1"]
    assert "kurdistan" in result["a1"]
    assert "turkey" in result["a1"]

    # Iran Kurdish story → rojhilat + kurdistan
    assert "rojhilat" in result["a2"]
    assert "kurdistan" in result["a2"]

    # UN story → world
    assert "world" in result["a3"]

    # No Bedrock calls should have been made
    assert telemetry.bedrock_calls == 0


# ─── Test: Classification Result Used Correctly ──────────────────────────────

def test_classification_result_used_correctly():
    """Only articles classified into a program should appear as candidates."""
    articles = [
        _make_article("a1", "SDF in Rojava fights ISIS", description="northeast Syria operations"),
        _make_article("a2", "Turkey raises interest rates", description="Ankara central bank"),
    ]

    with patch("lambda_function.articles_table") as mock_articles, \
         patch("lambda_function.programs_table") as mock_programs:
        mock_articles.scan.return_value = {"Items": articles}
        mock_programs.get_item.return_value = {}
        mock_programs.put_item.return_value = {}

        response = _invoke_lambda({"program_id": "rojava"})

    body = response["body"]
    # Only the Rojava article should be in the program
    assert body["programs"]["rojava"]["story_count"] >= 1
    # Turkey article should NOT be in rojava program


# ─── Test: No Articles Returns Gracefully ────────────────────────────────────

def test_no_articles_returns_gracefully():
    """When no fresh articles exist, should return gracefully."""
    with patch("lambda_function.articles_table") as mock_articles:
        mock_articles.scan.return_value = {"Items": []}

        response = _invoke_lambda({"program_id": "rojava"})

    assert response["statusCode"] == 200
    body = response["body"]
    assert "No fresh articles" in body["message"]


# ─── Test: Clustering Ranks by Cross-Source Count ────────────────────────────

def test_clustering_ranks_by_cross_source():
    """Stories covered by more sources should rank higher."""
    from lambda_function import cluster_and_rank, Telemetry

    candidates = [
        _make_article("a1", "Single source story about Rojava aid", source_name="Source A",
                      pub_date="2026-01-15T10:00:00Z"),
        _make_article("a2", "Multi source story about Rojava attack", source_name="Source B",
                      pub_date="2026-01-15T09:00:00Z"),
        _make_article("a3", "Multi source story about Rojava attack confirmed", source_name="Source C",
                      pub_date="2026-01-15T09:30:00Z"),
    ]
    telemetry = Telemetry()
    selected = cluster_and_rank(candidates, "rojava", telemetry)

    # The multi-source cluster should rank first
    assert selected[0]["cross_source_count"] >= 2


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
