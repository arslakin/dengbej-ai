# Dengbêj AI — Production Readiness Audit

Phase: production-readiness (branch `feature/production-readiness`)
Scope: code + configuration audit only. No AWS changes, no deployment, no TTS
invocation, no new publishers. Items are marked READY only when verified in
this pass (by reading the code, running the test suite, or a direct check).

Legend:
- **READY** — verified working / safe for launch as-is
- **NEEDS WORK BEFORE DEPLOYMENT** — should be addressed before going public
- **POST-LAUNCH / OPTIONAL** — safe to launch without; improve later
- **REQUIRES AWS CHANGE** — needs an infrastructure/console/Terraform change (out of scope here)
- **REQUIRES HUMAN REVIEW** — a person must decide (policy, licensing, risk acceptance)

---

## Release-candidate status — `release/public-product-v1`

Branch `release/public-product-v1` is based on `feature/production-readiness`
(`73a535a`) and adds the two completed production-readiness code changes below.
This is a **reviewable release candidate only**: no deployment, no AWS change,
no TTS usage occurred.

### Completed in this release candidate (with test evidence)

- **Desktop listener layout (DONE)** — a bounded, desktop-only CSS enhancement
  in `frontend/index.html`: at viewport widths ≥ 1100px the listening column
  widens and the story list becomes a two-column reading grid, with the lead
  story full width and the program card plus all loading/error/empty state
  containers spanning the full grid. Mobile (<599px), tablet (600–899px), the
  900px rule, reduced-motion, bilingual switching, source links, Bêje!/Tell me!,
  player controls, and audio selection are all preserved (CSS-only; no markup or
  JS change). *Evidence:* 8 focused tests in `frontend/tests/test_frontend.py`
  (desktop breakpoint, two-column grid, full-width lead/state/card, and guards
  that mobile/tablet breakpoints and core behavior hooks remain). Frontend suite
  **126 passed**.

- **News API failure safety (DONE)** — both previously-deferred fixes in
  `backend/news_api/lambda_function.py` are now implemented:
  1. A **top-level exception boundary** wraps routing and returns a generic JSON
     HTTP 500 (`{"error": "Internal server error"}`) on any unexpected failure.
     No exception text, stack trace, table name, AWS identifier, or credential
     is exposed to the client; only a short, non-sensitive context line is
     logged server-side. Existing CORS and response format are unchanged.
  2. **DynamoDB `ClientError` is no longer presented as a successful empty
     program.** `handle_program` and `get_processed_briefing` no longer swallow
     `ClientError`; a data-store failure now reaches the controlled 5xx path,
     while a genuinely valid zero-story program still returns its honest empty
     200 and existing 200/404 behavior is preserved.
  *Evidence:* 8 focused tests in `backend/news_api/tests/test_api.py` (normal
  routing unchanged; unexpected exception → controlled JSON 500 with no leak;
  DynamoDB `ClientError` → 500 not empty 200; genuine zero-story program → valid
  empty 200; CORS headers present on both the 500 and the empty-200). news_api
  suite **30 passed**. These two items supersede the matching entries under
  *NEEDS WORK BEFORE DEPLOYMENT* and *Deferred* below (now resolved).

### Explicit gates that remain open (human / AWS — NOT done in this release)

- **Source licensing review** — confirm BBC / DW / Al Jazeera attribution and
  reuse compliance (metadata-only, link to original, no full-text republish).
- **Acceptance of the public unauthenticated API** — a human must accept the
  risk of the public, unauthenticated, unthrottled read API.
- **Custom domain / CDN decision** — decide whether to keep the hardcoded Lambda
  Function URL or move the site behind a stable custom domain / CDN.
- **Terraform state reconciliation** — a real backend/state must be configured
  before any infrastructure apply (see `docs/production_infrastructure_plan.md`;
  with no state a plan shows every resource as "to create").
- **Infrastructure apply & deployment approval** — IAM least-privilege, S3/
  CloudFront, TTL/lifecycle, and the actual deploy all require explicit human
  approval and are out of scope for this release candidate.

### Explicit confirmations for this release candidate

- **No deployment occurred** (not to Amplify, AWS, or anywhere).
- **No new regional publisher was added** — `feeds_config.json` still contains
  only the approved publishers (BBC, DW, Al Jazeera); no candidate was promoted.
- **Kurdish TTS scheduling remains disabled** — `KURDISH_TTS_ENABLED` default
  `false`; no EventBridge schedule invokes the Kurdish batch; batch path remains
  `dry_run`-by-default and fail-closed.
- **No TTS quota was consumed** — no Kurdish audio was generated.
- **No ads, tracking/analytics, subscriptions, authentication, podcast
  publishing, or ten-story expansion** were added. The release stays
  privacy-respecting and free of advertising/tracking.
- **No `terraform apply`, no production Lambda invocation, no AWS mutation.**
- `feature/production-infra-hardening` was **not** merged into this release
  branch; its Terraform plan stays separate until state is reconciled.

---

## Summary of changes made in this phase

- **Fixed (frontend, in-scope):** source-article links now pass through a new
  `safeUrl()` scheme allow-list (http/https only). Previously a story
  `original_url` was escaped for HTML but its URL *scheme* was not checked, so a
  `javascript:`/`data:` URL coming from an external RSS feed could render as a
  clickable link. `safeUrl()` is applied in both the Today and program render
  paths. Covered by new tests.
- No backend, infrastructure, AWS, or TTS code was changed.

---

## READY (verified this pass)

- **Regional program selectability** — Bakur, Rojhilat, Rojava, Başûr (and all
  programs) stay selectable even with zero stories; verified by frontend tests
  (`test_frontend.py`: program-button / navigation / empty-state tests).
- **Empty-state honesty** — an empty program shows "No current stories" /
  "Niha çîrok nînin" and never substitutes unrelated stories. Verified by tests.
- **Classifier safeguards** — generic Turkey news is not classified as Bakur and
  generic Iran news is not classified as Rojhilat, while genuine Kurdish-region
  stories still classify correctly and Rojava/Başûr/world behaviour is intact.
  Verified by 42 classifier tests (incl. 11 regional guards).
- **Bilingual EN/KU** — language toggle, persisted preference, and balanced
  EN/KU translation maps on all trust pages. Verified by tests.
- **Source attribution in API output** — `format_briefing`/`format_program`
  emit `primary_source {name, url}` and `supporting_sources`; Today's-5
  supporting sources are filtered to require both name and url.
- **HTML escaping of story text** — headline/summary/source/category rendered
  through `escapeHtml()`; source URL now additionally scheme-checked via
  `safeUrl()`. Verified by tests.
- **Source-URL scheme hardening** — `javascript:`/`data:`/blank schemes are
  neutralized to an empty href. Verified by node-executed tests.
- **No committed secrets** — no hardcoded API keys/credentials in source; the
  KurdishTTS key is stored in AWS Secrets Manager and never logged.
- **Kurdish TTS is not auto-triggered** — `KURDISH_TTS_ENABLED` defaults to
  `false`; the batch path defaults to `dry_run=True`; no EventBridge schedule
  invokes the Kurdish batch. Quota reservation is atomic and fail-closed with a
  monthly budget below the free tier.
- **MVP news/audio contract intact** — `test_mvp_contract.py` passes; the
  language-aware audio selection contract is unchanged.
- **Full test suite** — all suites pass (see Testing section).

---

## NEEDS WORK BEFORE DEPLOYMENT

- **API top-level error handler — RESOLVED in `release/public-product-v1`.**
  `news_api/lambda_function.py` now wraps routing in a top-level exception
  boundary returning a generic JSON 500 (no leaks). See the release-candidate
  status section above. Verified by tests.
- **DynamoDB errors masked as "empty" — RESOLVED in `release/public-product-v1`.**
  `handle_program`/`get_processed_briefing` no longer swallow `ClientError`; a
  data-store failure now reaches the controlled 5xx path while a genuine
  zero-story program still returns its honest empty 200. Verified by tests.

---

## POST-LAUNCH / OPTIONAL

- **Empty vs. nonexistent program both return 200** — acceptable for a public
  read API (the frontend treats both as "no current stories"), but a future
  cleanup could return 404 for unknown program ids.
- **Date route validates format only** — `^/news/\d{4}-\d{2}-\d{2}$` accepts
  impossible dates (e.g. `9999-99-99`); harmless (returns 404 "no briefing").
- **Dependency pinning** — most requirements use open lower bounds (`>=`);
  pin/lock for reproducible Lambda builds. Only `feedparser` is exact-pinned.
- **Stale `tts_provider.py` factory** — `get_tts_provider()` returns a
  no-op provider; the real provider lives in `kurdish_tts.py`. Dead code to tidy.
- **Duplicate `get_existing_program` read** in program generation (once for the
  fingerprint check, once inside script generation) — minor extra `get_item`.

---

## REQUIRES AWS CHANGE (do not perform in this phase)

- **Least-privilege IAM** — the shared lambda role attaches AWS-managed
  `AmazonPollyFullAccess` and `AmazonBedrockFullAccess` (`infrastructure/main.tf`
  ~lines 114–122). Scope these to the specific actions/resources actually used.
- **Public S3 bucket** — `infrastructure/main.tf` (~lines 31–56) disables all
  public-access blocks and grants `s3:GetObject` to `Principal="*"`. Audio is
  meant to be public, but consider serving via CloudFront and re-enabling
  bucket-level public-access blocks with a bucket policy scoped to the audio
  prefix.
- **CORS wildcard on public Function URLs** — `allow_origins=["*"]`
  (`news_api.tf` ~line 104; legacy `main.tf` ~line 186). Low risk for an
  unauthenticated read-only API, but tightening to the known site origin is
  cleaner. No rate limiting / WAF is configured.
- **Storage growth / no lifecycle** — no TTL on events/programs/briefings and no
  S3 lifecycle policy on audio objects; data grows unbounded. Add TTL and/or S3
  lifecycle rules.
- **Full-table DynamoDB scans** — curator and program generator scan the
  articles table on every scheduled run; cost scales with table size. Consider a
  GSI on `pub_date` or a query pattern instead of `scan`.
- **Hardcoded AWS account ID** — `infrastructure/main.tf` (~line 110) embeds a
  real account id in a managed-policy ARN. Prefer a data source / variable.
- **Legacy Lambda code unmanaged** — the legacy `dengbej_ai` function has
  `ignore_changes=[filename, source_code_hash]`; deployed code can drift from
  the repo.

*All of the above require infrastructure/console/Terraform apply and were
intentionally not modified. Nothing here was applied.*

---

## REQUIRES HUMAN REVIEW

- **Regional source candidates** — `docs/regional_source_candidates.md` lists
  research-only publishers for Bakur/Rojhilat/Rojava/Başûr. None are approved.
  A human must verify feed availability AND review/approve reuse terms before any
  is added to `backend/news_ingester/feeds_config.json`.
- **Public-facing description** — the site may be described as a "free,
  non-commercial public-interest project." Confirm this remains accurate. Do NOT
  describe Dengbêj AI as a registered nonprofit.
- **Source licensing** — existing production feeds (BBC, DW, Al Jazeera) carry
  attribution/reuse constraints documented in `docs/sources.md`; confirm current
  compliance (metadata-only, always link to original, no full-text republish).
- **Hardcoded public Lambda URL in `frontend/index.html`** — expected for a
  static client, but it ties the site to a specific Function URL/region and
  exposes the account's endpoint. Confirm this is acceptable or move behind a
  stable custom domain / CDN.
- **Accepting the public unauthenticated API surface** — confirm risk acceptance
  for a public, unauthenticated, unthrottled read API.

---

## Audit coverage by area

**A. Frontend** — responsive breakpoints present (`@media` for <599 / 600–899 /
reduced-motion); nav + footer nav with `aria-label`s; program selector renders
all programs; empty/loading/error states exist (`showEmpty`/`showLoading`/
`showError`); audio controls (play/pause/prev/next/seek) present; source
attribution + "Read original" links present and now scheme-checked; bilingual
EN/KU with `escapeHtml`; semantic `<article>/<h3>/<nav>` markup; keyboard focus
styles (`:focus-visible`). No external asset/CDN dependencies; no tracking/ad
scripts (enforced by tests).

**B. API / Backend** — routing, status codes, attribution shape, dedup
(clustering + fingerprint), stale cutoff (`FRESHNESS_HOURS`), ordering (rank /
cross-source), classifier boundaries verified. Gaps documented above (top-level
error handling; ClientError masking).

**C. Audio** — URL selection (`selectAudioUrl`), missing-audio status text,
program switching and next/prev verified via tests; MVP contract passes. Kurdish
TTS untouched and confirmed default-disabled + dry-run-by-default + fail-closed
quota.

**D. Security** — no committed secrets; XSS surface reduced via `safeUrl()`;
remaining IAM/S3/CORS/account-id items are AWS-side (documented). Server-side
fetch of feed URLs (processor) and unvalidated stored article-link scheme noted;
frontend link scheme is now allow-listed.

**E. Privacy / Transparency** — transparency page states summaries are
AI-assisted, not original reporting; publishers attributed; originals linked;
regional programs may be empty; unrelated country news is not substituted;
AI content can contain errors. No advertising/tracking. Verified in content +
tests.

**F. Cost / Operational** — schedules and invocation frequency mapped; no
Kurdish-TTS schedule; scan-based reads, missing TTL/lifecycle, and Bedrock call
counts documented as AWS-side improvements. No code changed.

---

## Deferred (follow-up)

Items 1 and 2 below were **completed in `release/public-product-v1`** (see the
release-candidate status section). The remaining items are still deferred:

1. ~~Add a top-level try/except in `news_api` returning a 500 JSON body.~~ **DONE.**
2. ~~Distinguish DynamoDB errors from empty results in `handle_program`.~~ **DONE.**
3. Pin/lock backend dependencies.
4. Remove the dead `tts_provider.get_tts_provider()` path.

---

## Deployment checklist

Pre-deploy (must pass):
- [ ] Full test suite green (`python run_tests.py`)
- [ ] Static checks green (`node --check` on HTML JS; `py_compile` on Python)
- [ ] `git diff` reviewed; no secrets committed
- [ ] `backend/news_ingester/feeds_config.json` contains ONLY approved
      publishers (BBC, DW, Al Jazeera) — no candidate publisher added
- [ ] Regional empty-state behaviour intact ("No current stories")
- [ ] Generic Turkey/Iran stories cannot fill Bakur/Rojhilat (classifier guards)
- [ ] Kurdish/audio functionality preserved (MVP contract passes)

Human sign-off (REQUIRES HUMAN REVIEW):
- [ ] Public non-commercial wording confirmed accurate (not a registered nonprofit)
- [ ] Existing source licensing/attribution compliance confirmed
- [ ] Risk-acceptance for public unauthenticated read API
- [ ] Decision on hardcoded Function URL vs. custom domain/CDN

Recommended before public launch (REQUIRES AWS CHANGE):
- [ ] Tighten IAM to least privilege (drop Full-access managed policies)
- [ ] Front S3 audio with CloudFront and re-enable public-access blocks
- [ ] Add TTL / S3 lifecycle to bound storage growth
- [ ] Replace article-table `scan` with a query/GSI
- [ ] Consider rate limiting / WAF on the public Function URL

Post-launch (optional):
- [ ] Pin dependencies; add lockfiles
- [ ] Return 404 for unknown program ids
- [ ] Clean up dead TTS provider factory

---

## Explicit confirmations for this phase

- No AWS resources were changed.
- No deployment occurred.
- No production Lambda was invoked.
- No Kurdish TTS was generated; no TTS quota consumed.
- No new publisher was added to production ingestion.
- No tracking or advertising was added.
- Kurdish TTS behaviour was not modified.
