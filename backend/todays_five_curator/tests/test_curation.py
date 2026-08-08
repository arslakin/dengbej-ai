"""
Unit tests for the Today's 5 curation pipeline.

Tests cover:
- Headline normalization and token similarity
- Story clustering (deterministic)
- Freshness calculation
- Source diversity enforcement
- Final selection logic
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lambda_function import (
    normalize_headline,
    token_similarity,
    calculate_freshness,
    select_with_diversity,
    build_cluster_info,
    WEIGHT_SIGNIFICANCE,
    WEIGHT_CROSS_SOURCE,
    WEIGHT_KURDISH_RELEVANCE,
    WEIGHT_FRESHNESS,
    DIVERSITY_PENALTY,
    MAX_PRIMARY_PER_SOURCE,
)


# ─── Test: Headline Normalization ────────────────────────────────────────────

def test_normalize_headline_basic():
    tokens = normalize_headline("Turkey and Saudi Arabia sign defence pact")
    assert "turkey" in tokens
    assert "saudi" in tokens
    assert "arabia" in tokens
    assert "defence" in tokens
    assert "pact" in tokens
    # Stopwords removed
    assert "and" not in tokens
    assert "the" not in tokens


def test_normalize_headline_punctuation():
    tokens = normalize_headline("Meta fined $567m — largest child-safety ruling!")
    assert "meta" in tokens
    assert "fined" in tokens
    assert "567m" in tokens
    # Punctuation stripped
    assert "—" not in tokens
    assert "!" not in tokens


def test_normalize_headline_empty():
    tokens = normalize_headline("")
    assert tokens == []


# ─── Test: Token Similarity ──────────────────────────────────────────────────

def test_token_similarity_identical():
    tokens = ["turkey", "saudi", "arabia", "defence", "pact"]
    sim = token_similarity(tokens, tokens)
    assert sim == 1.0


def test_token_similarity_same_event_different_wording():
    a = normalize_headline("Saudi Arabia, Turkey and Pakistan sign defence pact")
    b = normalize_headline("Turkey, Saudi Arabia, Pakistan sign joint defence agreement")
    sim = token_similarity(a, b)
    # Should be high — same key entities
    assert sim >= 0.3, f"Expected >= 0.3, got {sim}"


def test_token_similarity_different_stories():
    a = normalize_headline("Meta fined $567m in largest child safety ruling")
    b = normalize_headline("Seven killed after Thai student opens fire at school")
    sim = token_similarity(a, b)
    # Should be low — completely different stories
    assert sim < 0.2, f"Expected < 0.2, got {sim}"


def test_token_similarity_empty():
    assert token_similarity([], ["hello"]) == 0.0
    assert token_similarity(["hello"], []) == 0.0
    assert token_similarity([], []) == 0.0


# ─── Test: Freshness Calculation ─────────────────────────────────────────────

def test_freshness_just_published():
    now = datetime.now(timezone.utc)
    pub_date = now.isoformat()
    freshness = calculate_freshness(pub_date, now)
    assert freshness >= 0.99, f"Expected ~1.0, got {freshness}"


def test_freshness_12_hours_old():
    now = datetime.now(timezone.utc)
    pub_date = (now - timedelta(hours=12)).isoformat()
    freshness = calculate_freshness(pub_date, now)
    # 12h out of 24h window = 0.5
    assert 0.45 <= freshness <= 0.55, f"Expected ~0.5, got {freshness}"


def test_freshness_24_hours_old():
    now = datetime.now(timezone.utc)
    pub_date = (now - timedelta(hours=24)).isoformat()
    freshness = calculate_freshness(pub_date, now)
    assert freshness <= 0.01, f"Expected ~0.0, got {freshness}"


def test_freshness_older_than_window():
    now = datetime.now(timezone.utc)
    pub_date = (now - timedelta(hours=48)).isoformat()
    freshness = calculate_freshness(pub_date, now)
    assert freshness == 0.0


def test_freshness_empty_string():
    now = datetime.now(timezone.utc)
    assert calculate_freshness("", now) == 0.0
    assert calculate_freshness(None, now) == 0.0


# ─── Test: Source Diversity ──────────────────────────────────────────────────

def _make_cluster(headline, source, score):
    """Helper to create a scored cluster for testing."""
    return {
        "headline": headline,
        "primary_source": source,
        "original_url": f"https://example.com/{headline[:10]}",
        "pub_date": "2026-08-08T10:00:00+00:00",
        "final_score": score,
        "all_articles": [{"source_name": source, "original_url": f"https://example.com/{headline[:10]}"}],
        "international_significance_score": 4,
        "kurdish_relevance_score": 3,
        "cross_source_count": 1,
        "freshness_score": 0.8,
        "selection_reason": "test",
        "category": "world",
        "feed_description": "",
    }


def test_diversity_prevents_source_domination():
    """DW should not easily get more than 2 stories when alternatives with reasonable scores exist."""
    clusters = [
        _make_cluster("DW Story 1", "Deutsche Welle", 0.85),
        _make_cluster("DW Story 2", "Deutsche Welle", 0.83),
        _make_cluster("DW Story 3", "Deutsche Welle", 0.80),
        _make_cluster("DW Story 4", "Deutsche Welle", 0.78),
        _make_cluster("BBC Story 1", "BBC News", 0.79),
        _make_cluster("BBC Story 2", "BBC News", 0.74),
        _make_cluster("AJ Story 1", "Al Jazeera English", 0.72),
    ]

    selected, diversity_log = select_with_diversity(clusters)

    assert len(selected) == 5
    dw_count = sum(1 for s in selected if s["primary_source"] == "Deutsche Welle")
    # DW Story 3 at 0.80 - 0.15 = 0.65 should lose to BBC (0.79) and AJ (0.72)
    assert dw_count <= 2, f"DW got {dw_count} stories, expected <= 2 with soft penalty"


def test_diversity_allows_dominant_story_through():
    """A clearly superior 3rd story from the same source should still be selected."""
    clusters = [
        _make_cluster("DW Story 1", "Deutsche Welle", 0.95),
        _make_cluster("DW Story 2", "Deutsche Welle", 0.90),
        _make_cluster("DW Story 3 (major)", "Deutsche Welle", 0.88),  # 0.88 - 0.15 = 0.73, still beats 0.50
        _make_cluster("BBC Story 1", "BBC News", 0.50),
        _make_cluster("AJ Story 1", "Al Jazeera English", 0.45),
        _make_cluster("AJ Story 2", "Al Jazeera English", 0.40),
    ]

    selected, diversity_log = select_with_diversity(clusters)

    assert len(selected) == 5
    dw_count = sum(1 for s in selected if s["primary_source"] == "Deutsche Welle")
    # DW Story 3 at 0.73 effective still beats BBC at 0.50 and AJ at 0.45
    assert dw_count == 3, f"DW should get 3 stories when clearly stronger, got {dw_count}"


def test_diversity_allows_mixed_sources():
    """When sources are balanced, top 5 by score should be selected."""
    clusters = [
        _make_cluster("BBC Story 1", "BBC News", 0.95),
        _make_cluster("DW Story 1", "Deutsche Welle", 0.90),
        _make_cluster("AJ Story 1", "Al Jazeera English", 0.85),
        _make_cluster("BBC Story 2", "BBC News", 0.80),
        _make_cluster("DW Story 2", "Deutsche Welle", 0.75),
    ]

    selected, diversity_log = select_with_diversity(clusters)

    assert len(selected) == 5
    # No penalty should apply since no source exceeds 2
    penalty_actions = [l for l in diversity_log if "penalty" in l.get("action", "")]
    assert len(penalty_actions) == 0


def test_diversity_logs_penalty_when_applied():
    """Diversity log should record when penalty affects selection."""
    clusters = [
        _make_cluster("DW Story 1", "Deutsche Welle", 0.95),
        _make_cluster("DW Story 2", "Deutsche Welle", 0.90),
        _make_cluster("DW Story 3", "Deutsche Welle", 0.88),
        _make_cluster("BBC Story 1", "BBC News", 0.50),
        _make_cluster("AJ Story 1", "Al Jazeera English", 0.45),
        _make_cluster("AJ Story 2", "Al Jazeera English", 0.40),
    ]

    selected, diversity_log = select_with_diversity(clusters)

    # DW Story 3 should have a penalty logged
    penalty_entries = [l for l in diversity_log if "penalty" in l.get("action", "").lower()]
    assert len(penalty_entries) >= 1, f"Expected penalty log entry, got {diversity_log}"


def test_diversity_minimum_two_sources():
    """Should warn if fewer than 2 sources represented."""
    clusters = [
        _make_cluster("DW Story 1", "Deutsche Welle", 0.95),
        _make_cluster("DW Story 2", "Deutsche Welle", 0.90),
        _make_cluster("DW Story 3", "Deutsche Welle", 0.85),
        _make_cluster("DW Story 4", "Deutsche Welle", 0.80),
        _make_cluster("DW Story 5", "Deutsche Welle", 0.75),
    ]

    selected, diversity_log = select_with_diversity(clusters)

    # All DW because no alternatives — should produce a warning
    warning_entries = [l for l in diversity_log if "Warning" in l.get("action", "")]
    assert len(warning_entries) >= 1


def test_diversity_penalty_value():
    """Confirm DIVERSITY_PENALTY is reasonable (not too harsh, not too mild)."""
    assert 0.05 <= DIVERSITY_PENALTY <= 0.25, f"Penalty {DIVERSITY_PENALTY} seems unreasonable"
    # Penalty should be less than the difference between a major and minor story
    # A 5/5 significance story scores ~0.45 more than a 1/5 story in that dimension alone
    assert DIVERSITY_PENALTY < 0.45


# ─── Test: Scoring Weights ───────────────────────────────────────────────────

def test_scoring_weights_sum_to_one():
    total = WEIGHT_SIGNIFICANCE + WEIGHT_CROSS_SOURCE + WEIGHT_KURDISH_RELEVANCE + WEIGHT_FRESHNESS
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_scoring_formula():
    """Verify the scoring formula produces expected results."""
    # Perfect scores: significance=5, cross_source=3, kurdish=5, freshness=1.0
    significance_norm = 5 / 5.0
    cross_source_norm = 3 / 3.0
    kurdish_norm = 5 / 5.0
    freshness_norm = 1.0

    score = (
        significance_norm * WEIGHT_SIGNIFICANCE +
        cross_source_norm * WEIGHT_CROSS_SOURCE +
        kurdish_norm * WEIGHT_KURDISH_RELEVANCE +
        freshness_norm * WEIGHT_FRESHNESS
    )

    assert abs(score - 1.0) < 0.001, f"Perfect score should be 1.0, got {score}"


def test_scoring_low_kurdish_high_significance():
    """A globally significant story with no Kurdish relevance should still score well."""
    significance_norm = 5 / 5.0  # Max
    cross_source_norm = 2 / 3.0  # 2 sources
    kurdish_norm = 1 / 5.0       # Minimal
    freshness_norm = 0.8         # Recent

    score = (
        significance_norm * WEIGHT_SIGNIFICANCE +
        cross_source_norm * WEIGHT_CROSS_SOURCE +
        kurdish_norm * WEIGHT_KURDISH_RELEVANCE +
        freshness_norm * WEIGHT_FRESHNESS
    )

    # Should still be a competitive score
    assert score > 0.6, f"High-significance story scored too low: {score}"


# ─── Test: Cluster Building ──────────────────────────────────────────────────

def test_build_cluster_single_article():
    art = {
        "headline": "Test headline",
        "source_name": "BBC News",
        "original_url": "https://bbc.co.uk/test",
        "pub_date": "2026-08-08T10:00:00+00:00",
        "feed_description": "A test description",
    }
    cluster = build_cluster_info([art])
    assert cluster["headline"] == "Test headline"
    assert cluster["primary_source"] == "BBC News"
    assert cluster["cross_source_count"] == 1
    assert cluster["sources"] == ["BBC News"]


def test_build_cluster_multi_source():
    arts = [
        {"headline": "Event A", "source_name": "BBC News", "original_url": "https://bbc.co.uk/a", "pub_date": "2026-08-08T10:00:00+00:00", "feed_description": "desc"},
        {"headline": "Event A coverage", "source_name": "Deutsche Welle", "original_url": "https://dw.com/a", "pub_date": "2026-08-08T11:00:00+00:00", "feed_description": "desc"},
    ]
    cluster = build_cluster_info(arts)
    assert cluster["cross_source_count"] == 2
    assert set(cluster["sources"]) == {"BBC News", "Deutsche Welle"}
    # Primary should be most recent
    assert cluster["primary_source"] == "Deutsche Welle"


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
