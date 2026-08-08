"""
Dengbej AI — Today's 5 Curator Lambda

Selects the five most important stories from the last 24 hours of ingested
news articles. Uses a hybrid approach:
  1. Deterministic freshness filter
  2. Deterministic + Bedrock-assisted story clustering
  3. Bedrock-powered importance/relevance scoring
  4. Deterministic source-diversity enforcement
  5. Final selection of exactly 5 stories

Scoring formula:
  international_significance (45%) +
  cross_source_coverage (30%) +
  kurdish_audience_relevance (15%) +
  freshness (10%)

Source diversity is enforced during selection (not in the score).
"""

import json
import os
import hashlib
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import boto3
from botocore.exceptions import ClientError


# ─── Configuration ───────────────────────────────────────────────────────────

ARTICLES_TABLE = os.environ.get("ARTICLES_TABLE", "dengbej-articles")
BRIEFINGS_TABLE = os.environ.get("BRIEFINGS_TABLE", "dengbej-briefings")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
FRESHNESS_WINDOW_HOURS = int(os.environ.get("FRESHNESS_WINDOW_HOURS", "24"))
MAX_STORIES = 5
MAX_PRIMARY_PER_SOURCE = 2
DIVERSITY_PENALTY = 0.15  # Score penalty for 3rd+ story from same source

# Scoring weights
WEIGHT_SIGNIFICANCE = 0.55
WEIGHT_CROSS_SOURCE = 0.20
WEIGHT_KURDISH_RELEVANCE = 0.15
WEIGHT_FRESHNESS = 0.10


# ─── AWS Clients ─────────────────────────────────────────────────────────────

dynamodb = boto3.resource("dynamodb")
articles_table = dynamodb.Table(ARTICLES_TABLE)
briefings_table = dynamodb.Table(BRIEFINGS_TABLE)
bedrock_runtime = boto3.client("bedrock-runtime")


# ─── Telemetry ───────────────────────────────────────────────────────────────

class Telemetry:
    """Tracks cost/usage metrics for each curator run."""

    def __init__(self):
        self.articles_considered = 0
        self.articles_after_freshness = 0
        self.clusters_created = 0
        self.bedrock_calls = 0
        self.bedrock_input_tokens = 0
        self.bedrock_output_tokens = 0
        self.selected_count = 0
        self.start_time = datetime.now(timezone.utc)
        self.duration_ms = 0

    def finish(self):
        self.duration_ms = int(
            (datetime.now(timezone.utc) - self.start_time).total_seconds() * 1000
        )

    def to_dict(self):
        return {
            "articles_considered": self.articles_considered,
            "articles_after_freshness": self.articles_after_freshness,
            "clusters_created": self.clusters_created,
            "bedrock_calls": self.bedrock_calls,
            "bedrock_input_tokens": self.bedrock_input_tokens,
            "bedrock_output_tokens": self.bedrock_output_tokens,
            "selected_count": self.selected_count,
            "duration_ms": self.duration_ms,
        }


# Module-level telemetry instance (reset per invocation)
telemetry = Telemetry()


# ─── Main Handler ────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """Curate Today's 5 briefing."""
    global telemetry
    telemetry = Telemetry()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=FRESHNESS_WINDOW_HOURS)

    print(f"Curating Today's 5. Window: {cutoff.isoformat()} to {now.isoformat()}")

    # Stage 1: Get fresh articles
    candidates = get_fresh_articles(cutoff)
    telemetry.articles_after_freshness = len(candidates)
    print(f"Stage 1 — Fresh articles: {len(candidates)}")

    if len(candidates) < 5:
        telemetry.finish()
        print(f"Telemetry: {json.dumps(telemetry.to_dict())}")
        return {"statusCode": 200, "body": json.dumps({
            "message": "Not enough fresh articles for curation",
            "candidates": len(candidates),
            "telemetry": telemetry.to_dict(),
        })}

    # Stage 2: Cluster related stories
    clusters = cluster_stories(candidates)
    telemetry.clusters_created = len(clusters)
    print(f"Stage 2 — Story clusters: {len(clusters)}")

    # Stage 3: Score clusters
    scored_clusters = score_clusters(clusters, now)
    print(f"Stage 3 — Scored clusters: {len(scored_clusters)}")

    # Stage 4: Select with diversity
    selected, diversity_log = select_with_diversity(scored_clusters)
    telemetry.selected_count = len(selected)
    print(f"Stage 4 — Selected: {len(selected)}, Diversity actions: {len(diversity_log)}")

    # Stage 4b: Final duplicate guard
    selected, dedup_log = deduplicate_selection(selected, scored_clusters)
    print(f"Stage 4b — After dedup: {len(selected)} stories, dedup actions: {len(dedup_log)}")

    # Stage 5: Store briefing
    briefing = store_briefing(selected, now)

    telemetry.finish()
    print(f"Telemetry: {json.dumps(telemetry.to_dict())}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "briefing_date": briefing["briefing_date"],
            "generated_at": briefing["generated_at"],
            "stories_selected": len(selected),
            "clusters_total": len(clusters),
            "candidates_total": len(candidates),
            "diversity_log": diversity_log,
            "dedup_log": dedup_log,
            "telemetry": telemetry.to_dict(),
        })
    }


# ─── Stage 1: Freshness Filter ──────────────────────────────────────────────

def get_fresh_articles(cutoff):
    """Scan articles table for items published after cutoff."""
    cutoff_iso = cutoff.isoformat()
    items = []

    # Full scan with filter (acceptable for ~200 items)
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

    # Track total scanned for telemetry
    telemetry.articles_considered = response.get("ScannedCount", len(items))
    return items


# ─── Stage 2: Story Clustering ───────────────────────────────────────────────

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
    "for", "of", "and", "or", "but", "with", "by", "from", "as", "its",
    "has", "have", "had", "be", "been", "will", "would", "could", "should",
    "that", "this", "it", "not", "no", "can", "do", "does", "did", "says",
    "said", "after", "over", "new", "more", "about", "into", "up", "out",
}

ENTITY_INDICATORS = {
    "saudi", "arabia", "turkey", "turkiye", "pakistan", "iran", "iraq", "syria",
    "israel", "palestine", "ukraine", "russia", "china", "india", "lebanon",
    "yemen", "egypt", "jordan", "qatar", "kuwait", "oman", "bahrain",
    "erdogan", "putin", "zelenskyy", "netanyahu", "trump", "biden",
    "nato", "who", "hamas", "hezbollah", "houthi",
    "pact", "treaty", "agreement", "ceasefire", "summit", "election",
}


def normalize_headline(headline):
    """Lowercase, split hyphenated words, remove punctuation, remove stopwords."""
    # Split hyphenated/compound words BEFORE removing punctuation
    text = headline.lower()
    text = re.sub(r"[-–—/]", " ", text)  # Split on hyphens, dashes, slashes
    text = re.sub(r"[^a-z0-9\s]", "", text)
    tokens = [w for w in text.split() if w not in STOPWORDS and len(w) > 2]
    return tokens


def token_similarity(tokens_a, tokens_b):
    """Jaccard similarity on token sets with entity-aware boosting."""
    set_a, set_b = set(tokens_a), set(tokens_b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    jaccard = len(intersection) / len(union)

    # Boost: if intersection contains proper-noun-like tokens (countries, names)
    # that typically identify specific events, increase similarity
    entity_tokens = intersection & ENTITY_INDICATORS
    if len(entity_tokens) >= 2:
        jaccard = min(1.0, jaccard * 1.3)

    return jaccard


def cluster_stories(articles):
    """Group articles about the same event using improved similarity + Bedrock."""
    tokenized = [(art, normalize_headline(art.get("headline", ""))) for art in articles]

    clusters = []
    assigned = set()

    # Pass 1: Deterministic merge at higher confidence (sim >= 0.40)
    for i, (art_i, tokens_i) in enumerate(tokenized):
        if i in assigned:
            continue
        cluster = [art_i]
        assigned.add(i)
        for j, (art_j, tokens_j) in enumerate(tokenized):
            if j in assigned or j <= i:
                continue
            sim = token_similarity(tokens_i, tokens_j)
            if sim >= 0.40:
                cluster.append(art_j)
                assigned.add(j)
        clusters.append(cluster)

    # Pass 2: Bedrock verification for ambiguous candidate pairs (sim 0.20 - 0.39)
    single_clusters = [c for c in clusters if len(c) == 1]
    multi_clusters = [c for c in clusters if len(c) > 1]

    if len(single_clusters) > 3:
        # Find candidate pairs with moderate similarity
        candidate_pairs = find_ambiguous_pairs(single_clusters, tokenized_lookup={
            id(art): tokens for art, tokens in tokenized
        })
        if candidate_pairs:
            merged_singles = bedrock_verify_pairs(single_clusters, candidate_pairs)
            clusters = multi_clusters + merged_singles
        else:
            clusters = multi_clusters + single_clusters
    else:
        clusters = multi_clusters + single_clusters

    return [build_cluster_info(c) for c in clusters]


def find_ambiguous_pairs(single_clusters, tokenized_lookup=None):
    """Find pairs of single-article clusters with moderate similarity (0.20-0.39)."""
    pairs = []
    for i in range(len(single_clusters)):
        art_i = single_clusters[i][0]
        tokens_i = normalize_headline(art_i.get("headline", ""))
        for j in range(i + 1, len(single_clusters)):
            art_j = single_clusters[j][0]
            tokens_j = normalize_headline(art_j.get("headline", ""))
            sim = token_similarity(tokens_i, tokens_j)
            if 0.20 <= sim < 0.40:
                pairs.append((i, j, sim))
    # Limit to top 15 most similar pairs to control Bedrock cost
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:15]


def bedrock_verify_pairs(single_clusters, candidate_pairs):
    """Use Bedrock to verify whether candidate pairs describe the same event."""
    if not candidate_pairs:
        return single_clusters

    # Build the verification prompt with ONLY the candidate pairs
    pair_descriptions = []
    for idx, (i, j, sim) in enumerate(candidate_pairs):
        h_i = single_clusters[i][0].get("headline", "")
        h_j = single_clusters[j][0].get("headline", "")
        pair_descriptions.append(f"Pair {idx+1}: \"{h_i}\" vs \"{h_j}\"")

    prompt = f"""You are a news editor determining whether headline pairs describe the SAME specific news event.

RULES:
- Same specific event = YES (different reports about the same incident/development)
- Same general topic/country/region but different events = NO
- Shared keywords or entities alone do NOT mean same event
- Analysis/follow-up about the same specific development = YES
- Return false when uncertain — missed merges are safer than false merges

For each pair, determine if they describe the SAME specific news event.

{chr(10).join(pair_descriptions)}

Return a JSON array with one object per pair:
[{{"pair": 1, "same_event": true, "confidence": 0.95}}]

Only mark same_event=true when confidence >= 0.80.

JSON:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=500)
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            verdicts = json.loads(json_match.group())

            # Process merges
            merge_map = {}  # index -> merge_target_index
            for verdict in verdicts:
                if not isinstance(verdict, dict):
                    continue
                pair_num = verdict.get("pair", 0) - 1
                same = verdict.get("same_event", False)
                confidence = verdict.get("confidence", 0)

                if same and confidence >= 0.80 and 0 <= pair_num < len(candidate_pairs):
                    i, j, _ = candidate_pairs[pair_num]
                    # Merge j into i's cluster
                    if j not in merge_map and i not in merge_map:
                        merge_map[j] = i
                    elif j not in merge_map:
                        merge_map[j] = merge_map.get(i, i)

            # Build merged clusters
            merged_indices = set()
            result_clusters = []

            for target_i, source_j_list in _group_merges(merge_map).items():
                merged = list(single_clusters[target_i])
                for j in source_j_list:
                    merged.extend(single_clusters[j])
                    merged_indices.add(j)
                merged_indices.add(target_i)
                result_clusters.append(merged)

            # Keep unmerged singles
            for i, c in enumerate(single_clusters):
                if i not in merged_indices:
                    result_clusters.append(c)

            return result_clusters
    except Exception as e:
        print(f"Bedrock pair verification failed (non-fatal): {e}")

    return single_clusters


def _group_merges(merge_map):
    """Group merge targets: {target_i: [j1, j2, ...]}"""
    groups = defaultdict(list)
    for j, i in merge_map.items():
        groups[i].append(j)
    return groups


def build_cluster_info(article_list):
    """Build cluster metadata from a list of articles about the same event."""
    sources = list(set(art.get("source_name", "") for art in article_list))
    # Pick the article with most recent pub_date as primary
    sorted_arts = sorted(article_list, key=lambda a: a.get("pub_date", ""), reverse=True)
    primary = sorted_arts[0]

    return {
        "primary_article": primary,
        "all_articles": article_list,
        "sources": sources,
        "cross_source_count": len(sources),
        "headline": primary.get("headline", ""),
        "primary_source": primary.get("source_name", ""),
        "original_url": primary.get("original_url", ""),
        "pub_date": primary.get("pub_date", ""),
        "feed_description": primary.get("feed_description", ""),
    }


# ─── Stage 3: Scoring ────────────────────────────────────────────────────────

def score_clusters(clusters, now):
    """Score each cluster on significance, Kurdish relevance, cross-source, freshness."""
    if not clusters:
        return []

    # Get Bedrock scores for all clusters in one batch call
    headlines_for_scoring = [c["headline"] for c in clusters[:50]]  # Cap at 50
    bedrock_scores = get_bedrock_scores(headlines_for_scoring)

    scored = []
    for i, cluster in enumerate(clusters[:50]):
        # Cross-source score (normalized to 0-1)
        cross_source_normalized = min(cluster["cross_source_count"] / 3.0, 1.0)

        # Bedrock scores (1-5, normalized to 0-1)
        significance_raw = bedrock_scores.get(i, {}).get("significance", 3)
        kurdish_relevance_raw = bedrock_scores.get(i, {}).get("kurdish_relevance", 2)
        significance_normalized = significance_raw / 5.0
        kurdish_normalized = kurdish_relevance_raw / 5.0

        # Freshness score (0-1, decays linearly over the window)
        freshness_normalized = calculate_freshness(cluster["pub_date"], now)

        # Final weighted score
        final_score = (
            significance_normalized * WEIGHT_SIGNIFICANCE +
            cross_source_normalized * WEIGHT_CROSS_SOURCE +
            kurdish_normalized * WEIGHT_KURDISH_RELEVANCE +
            freshness_normalized * WEIGHT_FRESHNESS
        )

        cluster["international_significance_score"] = significance_raw
        cluster["kurdish_relevance_score"] = kurdish_relevance_raw
        cluster["freshness_score"] = round(freshness_normalized, 3)
        cluster["final_score"] = round(final_score, 4)
        cluster["selection_reason"] = bedrock_scores.get(i, {}).get("reason", "")
        cluster["category"] = bedrock_scores.get(i, {}).get("category", "world")

        scored.append(cluster)

    # Sort by final score descending
    scored.sort(key=lambda c: c["final_score"], reverse=True)
    return scored


def calculate_freshness(pub_date_str, now):
    """Linear freshness decay: 1.0 for just published, 0.0 for FRESHNESS_WINDOW_HOURS old."""
    if not pub_date_str:
        return 0.0
    try:
        pub_date = datetime.fromisoformat(pub_date_str)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        age_hours = (now - pub_date).total_seconds() / 3600
        freshness = max(0.0, 1.0 - (age_hours / FRESHNESS_WINDOW_HOURS))
        return freshness
    except (ValueError, TypeError):
        return 0.0


def get_bedrock_scores(headlines):
    """Ask Bedrock to score headlines on significance and Kurdish relevance."""
    if not headlines:
        return {}

    prompt = f"""You are an experienced international news editor curating for a Kurdish-audience global news platform.

Score each headline on two dimensions (1-5 scale) and assign a category.

INTERNATIONAL SIGNIFICANCE (1-5):
5 = Major world event affecting millions (wars, disasters, major policy shifts)
4 = Significant international development
3 = Noteworthy regional/international story
2 = Moderate-interest story
1 = Minor/local story with limited global impact

KURDISH-AUDIENCE RELEVANCE (1-5):
5 = Directly involves Kurdish regions, Kurdish people, or Kurdish diaspora
4 = Involves Turkey, Iraq, Iran, Syria in ways relevant to Kurdish populations
3 = Major global event with indirect Kurdish relevance (Middle East, migration, human rights)
2 = International news of general interest to any audience
1 = No particular Kurdish connection

CATEGORY: One of: conflict, politics, economy, climate, health, technology, culture, human-rights, migration, world

Headlines:
{chr(10).join(f"{i+1}. {h}" for i, h in enumerate(headlines))}

Return a JSON array with one object per headline:
[{{"significance": 4, "kurdish_relevance": 2, "category": "politics", "reason": "brief explanation"}}]

JSON:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=3000)
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            scores_list = json.loads(json_match.group())
            scores_dict = {}
            for i, score in enumerate(scores_list):
                if isinstance(score, dict):
                    scores_dict[i] = {
                        "significance": min(5, max(1, score.get("significance", 3))),
                        "kurdish_relevance": min(5, max(1, score.get("kurdish_relevance", 2))),
                        "category": score.get("category", "world"),
                        "reason": score.get("reason", ""),
                    }
            return scores_dict
    except Exception as e:
        print(f"Bedrock scoring failed: {e}")

    # Fallback: default scores
    return {i: {"significance": 3, "kurdish_relevance": 2, "category": "world", "reason": "scoring unavailable"} for i in range(len(headlines))}


# ─── Stage 4: Selection with Source Diversity ────────────────────────────────

def select_with_diversity(scored_clusters):
    """
    Select top 5 stories with soft source-diversity enforcement.

    Rules:
    - First 2 stories from any source: no penalty.
    - 3rd+ story from the same source: apply DIVERSITY_PENALTY to its effective score.
    - A story can still be selected despite the penalty if it remains competitive.
    - Ensure at least 2 different primary sources when suitable candidates exist.
    - Log all diversity decisions for transparency.
    """
    selected = []
    diversity_log = []
    source_count = defaultdict(int)

    # Apply diversity penalty and re-rank
    adjusted_clusters = []
    for cluster in scored_clusters:
        adjusted_clusters.append({
            **cluster,
            "_effective_score": cluster["final_score"],
            "_penalty_applied": False,
        })

    # Iterative greedy selection
    remaining = list(adjusted_clusters)

    while len(selected) < MAX_STORIES and remaining:
        # Recalculate effective scores based on current source_count
        for c in remaining:
            source = c["primary_source"]
            if source_count[source] >= MAX_PRIMARY_PER_SOURCE:
                c["_effective_score"] = c["final_score"] - DIVERSITY_PENALTY
                c["_penalty_applied"] = True
            else:
                c["_effective_score"] = c["final_score"]
                c["_penalty_applied"] = False

        # Sort remaining by effective score
        remaining.sort(key=lambda c: c["_effective_score"], reverse=True)

        # Pick the top candidate
        best = remaining.pop(0)
        source = best["primary_source"]

        # Log diversity action if penalty was applied
        if best["_penalty_applied"]:
            diversity_log.append({
                "headline": best["headline"],
                "primary_source": source,
                "original_score": best["final_score"],
                "effective_score": best["_effective_score"],
                "action": f"Selected despite diversity penalty (source already has {source_count[source]} stories)",
            })

        selected.append(best)
        source_count[source] += 1

    # Check minimum source diversity (at least 2 sources if possible)
    unique_sources = len(set(s["primary_source"] for s in selected))
    if unique_sources < 2 and len(scored_clusters) >= 5:
        diversity_log.append({
            "headline": "",
            "primary_source": "",
            "original_score": 0,
            "effective_score": 0,
            "action": f"Warning: Only {unique_sources} source(s) represented in Today's 5",
        })

    return selected, diversity_log


# ─── Stage 4b: Final Duplicate Guard ─────────────────────────────────────────

def deduplicate_selection(selected, scored_clusters):
    """
    Final safety net: verify no two selected stories are the same event.
    If duplicates found, keep higher-ranked and promote next distinct candidate.
    """
    if len(selected) < 2:
        return selected, []

    dedup_log = []

    # Check pairs within the selection
    pairs_to_check = []
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            tokens_i = normalize_headline(selected[i].get("headline", ""))
            tokens_j = normalize_headline(selected[j].get("headline", ""))
            sim = token_similarity(tokens_i, tokens_j)
            if sim >= 0.20:  # Even moderate similarity warrants checking
                pairs_to_check.append((i, j, sim))

    if not pairs_to_check:
        return selected, dedup_log

    # Ask Bedrock to verify
    pair_descriptions = []
    for idx, (i, j, sim) in enumerate(pairs_to_check):
        pair_descriptions.append(
            f"Pair {idx+1}: \"{selected[i]['headline']}\" vs \"{selected[j]['headline']}\""
        )

    prompt = f"""Are these headline pairs about the SAME specific news event?
Same event = different coverage of the same incident/development.
Same topic/country but different events = NO.

{chr(10).join(pair_descriptions)}

Return JSON: [{{"pair": 1, "same_event": true, "confidence": 0.95}}]
Only same_event=true when confidence >= 0.80.

JSON:"""

    try:
        result = invoke_bedrock(prompt, max_tokens=300)
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            verdicts = json.loads(json_match.group())

            indices_to_remove = set()
            for verdict in verdicts:
                if not isinstance(verdict, dict):
                    continue
                pair_num = verdict.get("pair", 0) - 1
                same = verdict.get("same_event", False)
                confidence = verdict.get("confidence", 0)

                if same and confidence >= 0.80 and 0 <= pair_num < len(pairs_to_check):
                    i, j, _ = pairs_to_check[pair_num]
                    # Remove the lower-ranked (higher index) duplicate
                    indices_to_remove.add(j)
                    dedup_log.append({
                        "removed": selected[j]["headline"],
                        "duplicate_of": selected[i]["headline"],
                        "confidence": confidence,
                    })

            if indices_to_remove:
                # Remove duplicates and promote replacements
                cleaned = [s for idx, s in enumerate(selected) if idx not in indices_to_remove]

                # Promote from remaining scored clusters
                selected_headlines = set(s["headline"] for s in cleaned)
                for cluster in scored_clusters:
                    if len(cleaned) >= 5:
                        break
                    if cluster["headline"] not in selected_headlines:
                        # Verify this promotion is not ALSO a duplicate
                        is_dup = False
                        for existing in cleaned:
                            t1 = normalize_headline(existing["headline"])
                            t2 = normalize_headline(cluster["headline"])
                            if token_similarity(t1, t2) >= 0.40:
                                is_dup = True
                                break
                        if not is_dup:
                            cleaned.append(cluster)
                            selected_headlines.add(cluster["headline"])
                            dedup_log.append({
                                "promoted": cluster["headline"],
                                "reason": "Replaced duplicate event",
                            })

                return cleaned, dedup_log
    except Exception as e:
        print(f"Dedup verification failed (non-fatal): {e}")

    return selected, dedup_log


# ─── Stage 5: Store Briefing ─────────────────────────────────────────────────

def store_briefing(selected_clusters, now):
    """Store the briefing in DynamoDB."""
    briefing_date = now.strftime("%Y-%m-%d")
    generated_at = now.isoformat()

    stories = []
    for rank, cluster in enumerate(selected_clusters, 1):
        supporting_sources = [
            {"source_name": art.get("source_name", ""), "url": art.get("original_url", "")}
            for art in cluster.get("all_articles", [])
            if art.get("original_url") != cluster["original_url"]
        ]

        story = {
            "rank": rank,
            "headline": cluster["headline"],
            "category": cluster.get("category", "world"),
            "primary_source": cluster["primary_source"],
            "original_url": cluster["original_url"],
            "pub_date": cluster["pub_date"],
            "supporting_sources": supporting_sources,
            "international_significance_score": cluster.get("international_significance_score", 0),
            "kurdish_relevance_score": cluster.get("kurdish_relevance_score", 0),
            "cross_source_count": cluster.get("cross_source_count", 1),
            "freshness_score": cluster.get("freshness_score", 0),
            "raw_score": cluster.get("final_score", 0),
            "diversity_adjusted_score": cluster.get("_effective_score", cluster.get("final_score", 0)),
            "final_score": cluster.get("final_score", 0),
            "selection_reason": cluster.get("selection_reason", ""),
            "feed_description": cluster.get("feed_description", ""),
            "summary_en": None,
            "summary_ku": None,
            "audio_url": None,
            "processing_status": "pending",
        }
        stories.append(story)

    briefing = {
        "briefing_date": briefing_date,
        "generated_at": generated_at,
        "stories": stories,
        "status": "published",
    }

    briefings_table.put_item(Item=json.loads(json.dumps(briefing), parse_float=str))
    print(f"Briefing stored: {briefing_date}")
    return briefing


# ─── Bedrock Helper ──────────────────────────────────────────────────────────

def invoke_bedrock(prompt, max_tokens=1000):
    """Invoke Bedrock Claude model and track token usage."""
    global telemetry
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
    telemetry.bedrock_calls += 1
    usage = response_body.get("usage", {})
    telemetry.bedrock_input_tokens += usage.get("input_tokens", 0)
    telemetry.bedrock_output_tokens += usage.get("output_tokens", 0)

    return response_body["content"][0]["text"].strip()
