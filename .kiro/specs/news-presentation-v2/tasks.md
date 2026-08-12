# Implementation Plan

## Overview

This plan implements News Presentation V2 in 5 phases following the data flow: Ingestion → Events → Enrichment → Editions → Frontend. Each phase is independently deployable with zero downtime. The plan introduces event-centric architecture with ULID-based identity, canonical Kurdish headlines, quality-threshold edition selection, clean URL routing, and a headline discovery rail.

## Tasks

- [ ] 1. Add `source_image_url` extraction to News Ingester
  - [ ] 1.1. Implement `extract_source_image_url(entry)` with priority chain: media:content (medium="image") → media:thumbnail → enclosure (type=image/*) → null
  - [ ] 1.2. Implement `_is_valid_image_url(url)` validating absolute http/https ≤ 2048 chars
  - [ ] 1.3. Add `source_image_url` and `source_image_source` fields to article record in `store_article`
  - [ ] 1.4. Write tests: priority order, video-only fallthrough, oversized URLs, relative URLs, no-image entry
- [ ] 2. Create `dengbej-events` DynamoDB table and Terraform infrastructure
  - [ ] 2.1. Define `dengbej-events` table in `infrastructure/events.tf` with PK `event_id` (S), GSI `slug-index` on `slug` field
  - [ ] 2.2. Add `events_table_name` variable to `infrastructure/variables.tf`
  - [ ] 2.3. Run `terraform plan` to verify the table creation (do not apply until approved)
- [ ] 3. Implement Event Clusterer Lambda
  - [ ] 3.1. Create `backend/event_clusterer/lambda_function.py` with deterministic clustering logic: scan 48h articles → match against existing events (Jaccard ≥ 0.40) → create new events for unmatched clusters
  - [ ] 3.2. Implement ULID-based `event_id` generation (stable opaque identity, set once)
  - [ ] 3.3. Implement slug generation from `headline_en`: lowercase → strip special → hyphens → truncate 60 chars → collision check via slug-index GSI
  - [ ] 3.4. Implement `compute_fingerprint(source_article_ids)` using SHA-256 of sorted article IDs (content versioning separate from identity)
  - [ ] 3.5. Implement article → existing event matching: check `event_id` on article, compare headline similarity against recent events, assign to existing event if ≥ 0.40
  - [ ] 3.6. Implement event update flow: add article to event → update fingerprint → update sources/URLs → update `updated_at` → preserve slug/event_id
  - [ ] 3.7. Implement program classification for events using existing deterministic keyword classifier
  - [ ] 3.8. Implement `compute_editorial_score(event)`: cross_source_count + freshness bonus (+1 if article < 12h) + state bonus (+1 if new/updated)
  - [ ] 3.9. Write tests: initial creation, article addition, fingerprint change, slug stability, ULID uniqueness, Jaccard threshold, program classification, editorial scoring
- [ ] 4. Create Event Clusterer Terraform resources
  - [ ] 4.1. Define Event Clusterer Lambda function, IAM role/policy (articles: Scan/GetItem/UpdateItem, events: PutItem/GetItem/Query/UpdateItem) in `infrastructure/events.tf`
  - [ ] 4.2. Define EventBridge rule `cron(15 0,6,12,18 * * ? *)` targeting Event Clusterer
  - [ ] 4.3. Run `terraform plan` (do not apply until approved)
- [ ] 5. Implement Event Enricher (canonical headline_ku + context generation)
  - [ ] 5.1. Create `backend/event_enricher/lambda_function.py` that queries events needing enrichment (enriched_at IS NULL OR fingerprint != enriched_fingerprint)
  - [ ] 5.2. Implement single Bedrock call per event generating `headline_ku` + `context_summary_en` + `context_summary_ku` in one JSON response
  - [ ] 5.3. Implement idempotency: skip events where fingerprint matches enriched_fingerprint (no re-generation for unchanged events)
  - [ ] 5.4. Implement canonical reuse: once headline_ku is generated for an event, ALL programs referencing that event reuse it without additional calls
  - [ ] 5.5. Persist enrichment results back to `dengbej-events` table with `enriched_at` and `enriched_fingerprint`
  - [ ] 5.6. Write tests: enrichment call count (1 per new/updated event), idempotency (skip unchanged), canonical reuse (same event in multiple programs), graceful failure (null fields preserved)
- [ ] 6. Create Event Enricher Terraform resources
  - [ ] 6.1. Define Event Enricher Lambda, IAM (events: GetItem/Query/UpdateItem, Bedrock: InvokeModel), EventBridge rule `cron(20 0,6,12,18 * * ? *)`
  - [ ] 6.2. Run `terraform plan` (do not apply until approved)
- [ ] 7. Evolve Program Generator into Edition Generator
  - [ ] 7.1. Refactor `backend/program_generator/lambda_function.py` to select from `dengbej-events` instead of raw articles
  - [ ] 7.2. Implement `compute_edition_rank_score(event, program_id, previous_edition_event_ids)` with unified ranking: base editorial_score + program_affinity + freshness + corroboration + new_bonus(+1.5) + updated_bonus(+0.75) + repetition_penalty(-1.0)
  - [ ] 7.3. Implement quality threshold gate: `editorial_score >= 2` before ranking; max 10; no minimum; no padding
  - [ ] 7.4. Implement edition fingerprint: SHA-256 of sorted selected event_ids for idempotency
  - [ ] 7.5. Modify script generation to use pre-enriched event data (headline_ku, context summaries) instead of raw article descriptions
  - [ ] 7.6. Store edition with `event_ids`, `events` (denormalized), `edition_fingerprint`, `edition_cycle`
  - [ ] 7.7. Preserve existing script retry behavior (fingerprint unchanged + script missing → retry)
  - [ ] 7.8. Write tests: ranking model behavior, threshold enforcement, max 10 cap, repetition penalty, unchanged idempotency, script retry
- [ ] 8. Update Edition Generator EventBridge schedule
  - [ ] 8.1. Change program generation schedule from `cron(30 6,18 * * ? *)` to `cron(30 0,6,12,18 * * ? *)` (4x daily)
  - [ ] 8.2. Update IAM to add events table read access
  - [ ] 8.3. Run `terraform plan` (do not apply until approved)
- [ ] 9. Add event API endpoints to News API Lambda
  - [ ] 9.1. Add `GET /news/events/latest` endpoint returning recent events (48h, sorted by updated_at) for headline rail
  - [ ] 9.2. Add `GET /news/event/{slug}` endpoint with GSI lookup returning full event detail
  - [ ] 9.3. Enhance `GET /news/program/{id}` to return `events[]` alongside existing `stories[]` for backward compatibility
  - [ ] 9.4. Update News API IAM to allow GetItem/Query on dengbej-events table + slug-index GSI
  - [ ] 9.5. Write tests: event detail response shape, latest events ordering, program backward compat, null field handling for old records, 404 for unknown slug
- [ ] 10. Configure Amplify clean URL rewrites
  - [ ] 10.1. Add rewrite rule: `/news/<slug>` → `/index.html` (status 200) in Amplify configuration
  - [ ] 10.2. Verify `/news/test-slug` serves index.html without 404
- [ ] 11. Implement frontend headline rail
  - [ ] 11.1. Add "Nûçeyên Dawî / Latest" section above program selector with horizontal scrollable container
  - [ ] 11.2. Implement `overflow-x: auto` with `scroll-snap-type: x mandatory` for smooth item snapping
  - [ ] 11.3. Each headline links to `/news/{slug}` (not hash route)
  - [ ] 11.4. Kurdish mode → headline_ku; English mode → headline_en; fallback to available
  - [ ] 11.5. Keyboard accessible (focusable items, tabindex); reduced-motion friendly (no auto-scroll)
  - [ ] 11.6. Mobile responsive: full-width swipeable; no horizontal page overflow
- [ ] 12. Implement frontend event detail page
  - [ ] 12.1. Add path-based routing: read `window.location.pathname`, if `/news/{slug}` → load event page
  - [ ] 12.2. Fetch event data from `/news/event/{slug}` API endpoint
  - [ ] 12.3. Render: Kurdish headline (h1), English headline (h2), image with attribution and onerror fallback, context summary (language-switched), sources with original links, programs, timestamps
  - [ ] 12.4. Set `document.title` and meta description dynamically for the event
  - [ ] 12.5. Structure DOM with semantic sections for future ad compatibility (no ad code added)
  - [ ] 12.6. Add "← Back to Dengbej" navigation
  - [ ] 12.7. Handle 404: unknown slug → friendly error with homepage link
- [ ] 13. Update frontend program view for event-based rendering
  - [ ] 13.1. Update `renderProgramView` to use `events[]` from API response (fall back to `stories[]` for old data)
  - [ ] 13.2. Event cards: image (with onerror collapse), headline (language-switched), source count, category, link to `/news/{slug}`
  - [ ] 13.3. Maintain radio card hierarchy: Program → Bêje! + script → event cards below
- [ ] 14. Update frontend image handling and bilingual display
  - [ ] 14.1. Add CSS for `.event-image-wrap`, `.event-image` (width 100%, max-height 400px, object-fit cover), `.event-image-credit`
  - [ ] 14.2. Implement `onerror="this.parentElement.style.display='none'"` on all images
  - [ ] 14.3. Language toggle updates all visible headlines/summaries; `document.documentElement.lang` syncs with selection
  - [ ] 14.4. Dengbej narration (script_ku) always remains Kurmanji regardless of UI language mode
- [ ] 15. End-to-end integration tests and final verification
  - [ ] 15.1. Run complete backend test suite (target ≥ 235 passing tests)
  - [ ] 15.2. Verify pipeline end-to-end: ingestion with image → clustering → enrichment → edition selection → API → frontend
  - [ ] 15.3. Verify backward compatibility: old programs/briefings still render correctly
  - [ ] 15.4. Verify Today's 5 remains exactly 5 and unaffected by event architecture
  - [ ] 15.5. Verify clean URL routing: `/news/{slug}` resolves correctly on Amplify preview

## Task Dependency Graph

```json
{
  "waves": [
    [1, 2],
    [3, 4],
    [5, 6],
    [7, 8, 9, 10],
    [11, 12, 13, 14],
    [15]
  ]
}
```

## Notes

- Wave 1 (Ingester images + Events table) has no dependencies and can start immediately
- Wave 2 (Event Clusterer) depends on the events table and image-enriched articles
- Wave 3 (Event Enricher) depends on clustered events existing in the table
- Wave 4 (Edition Generator + API + Amplify) depends on enriched events; these are parallelizable
- Wave 5 (Frontend) depends on API endpoints being available
- Wave 6 (Integration tests) depends on everything
- Today's 5 pipeline (Curator + Processor) is NOT modified in this plan
- Terraform apply requires explicit approval at each infrastructure task
- Each phase can be deployed and verified independently before proceeding
