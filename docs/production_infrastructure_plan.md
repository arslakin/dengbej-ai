# Dengbêj AI — Production Infrastructure Hardening Plan (Phase 1)

Status: **PLAN ONLY.** No `terraform apply`, no deployment, no live AWS change
was performed. This document is the design + safe-apply sequence for a later,
separately reviewed rollout.

Account: `387276719593` · Region: `us-east-1` · Verified against the Terraform
in `infrastructure/*.tf` and the backend code (not just the earlier audit).

---

## 0. Important preconditions discovered

- **No Terraform state is available locally and no backend is configured.**
  `infrastructure/.terraform/` contains only provider plugins; there is no
  `terraform.tfstate` and no `backend "s3"` block. Consequently `terraform plan`
  reports **"58 to add, 0 to change, 0 to destroy"** — every existing resource
  looks like a *create* because Terraform has no record that they already
  exist. This is a state-absence artifact, **not** a proposal to rebuild live
  infrastructure.
  - **Do NOT `terraform apply` from this working copy.** Applying with no state
    against already-live resources would attempt to create duplicates / collide
    with existing names — the exact destructive risk to avoid.
  - **Blocker for any real apply:** obtain/point Terraform at the real state
    (configure the remote S3 backend and `terraform init`, or `terraform import`
    the existing resources) so a plan shows a true diff before anything is
    applied.
- The frontend HTML is **not** managed by Terraform at all (no CloudFront,
  website, Route53, or ACM resources exist). The `dengbej-audio` S3 bucket
  stores **audio files only**, not the site.

---

## 1. CURRENT ARCHITECTURE (verified)

Public (internet-facing):
- **News API** — `aws_lambda_function_url.news_api`, `authorization_type = NONE`,
  CORS `allow_origins = ["*"]`, methods `["GET"]`. Read-only; the frontend
  (`frontend/index.html`) calls this. IAM: DynamoDB `Query`/`GetItem` on
  `briefings`/`programs` only.
- **Legacy summary API** — `aws_lambda_function_url.dengbej_ai`
  (`dengbej-summary`), `authorization_type = NONE`, CORS `["*"]`, methods
  `["POST"]`. The old "paste text" prototype. Its code is unmanaged
  (`lifecycle { ignore_changes = [filename, source_code_hash] }`).
- **S3 `dengbej-audio`** — Block Public Access all `false`; bucket policy
  `Principal = "*"`, `s3:GetObject` on `/*`. Audio objects are world-readable.

Private (invoked only by EventBridge or other Lambdas):
- Lambdas: `news_ingester`, `curator`, `processor`, `daily_audio`,
  `program_generator`.
- DynamoDB (all `PAY_PER_REQUEST`): `articles` (hash `article_id`, no GSI),
  `briefings` (`briefing_date` + `generated_at`), `programs` (`program_id` +
  `briefing_date`), `events` (`event_id` + `slug-index` GSI).

Pipeline data flow:
```
EventBridge (rate 6h)          → news_ingester → articles (PutItem)
EventBridge (cron 0 6,18)      → curator       → scan articles, Bedrock, PutItem briefings
EventBridge (cron 15 6,18)     → processor     → Bedrock summarize/translate → briefings
EventBridge (cron 20 6,18)     → daily_audio   → Bedrock script + Polly (English) → S3 + briefings
EventBridge (cron 30 6,18)     → program_generator → scan articles, Bedrock → programs
Frontend (browser) ─ GET ─────→ news_api Function URL → Query briefings/programs
```
AI/speech scope:
- Bedrock `InvokeModel` is scoped to the specific inference-profile and
  foundation-model ARNs in each per-function policy (good).
- Polly `SynthesizeSpeech` uses `Resource = "*"` (Polly has no resource-level
  permissions, so this is normal and required).
- **Kurdish TTS is not scheduled** and is disabled by default
  (`KURDISH_TTS_ENABLED = "false"`); English narration via Polly runs on the
  daily-audio schedule.

Log retention: 14 days on all pipeline log groups; **legacy `lambda_logs` is
`0` (never expires)**.

---

## 2. TARGET ARCHITECTURE (Phase 1 scope)

Phase 1 is deliberately small and low-risk. It does **not** build CloudFront or
change S3 public access yet (those are later phases). Target after Phase 1:
- Legacy shared role uses a **scoped** Bedrock/Polly inline policy instead of
  the `*FullAccess` managed policies.
- S3 audio has a **transition-only** lifecycle rule (cheaper storage for old
  objects; no deletion).
- Legacy log group gains a finite retention (documented; applied in its own
  step).
- (Documented, later phases) CloudFront + private S3 for audio; DynamoDB TTL and
  a `pub_date` GSI; hardcoded account-id replaced with a data source.

---

## 3. IAM CHANGES

### 3.1 Legacy shared role — replace Full-access managed policies with scoped inline

- **CURRENT:** `aws_iam_role.lambda_role` attaches `AmazonPollyFullAccess` and
  `AmazonBedrockFullAccess` (AWS-managed, full-service); inline `DengbejS3Upload`
  grants `s3:PutObject` on the audio bucket.
- **PROPOSED:** add inline `DengbejLegacyScopedAiSpeech`
  (`bedrock:InvokeModel` on the specific model/inference-profile ARNs;
  `polly:SynthesizeSpeech` on `*`), then detach the two managed policies in the
  **same** apply. (Represented in `hardening.tf`, flag
  `manage_least_privilege_legacy_role`, default off. The detach is done by
  removing the two `aws_iam_role_policy_attachment` resources in that apply.)
- **WHY REQUIRED:** least privilege; the legacy Lambda only needs InvokeModel +
  SynthesizeSpeech, not full Polly/Bedrock control-plane access.
- **RESOURCE ARNs NEEDED:**
  `arn:aws:bedrock:us-east-1:*:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0`,
  `arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`,
  Polly `*`.
- **RISK OF BREAKAGE:** Medium — if the legacy Lambda uses a Bedrock action or
  model not covered by the scoped policy, it would get AccessDenied. Mitigate by
  reviewing CloudTrail / IAM Access Analyzer last-accessed data for the role
  **before** detaching. The current news pipeline does not use this role, so
  blast radius is limited to the legacy summary endpoint.
- **ROLLBACK:** re-attach `AmazonPollyFullAccess` + `AmazonBedrockFullAccess`
  (re-add the two `aws_iam_role_policy_attachment` resources) and remove the
  inline policy. Fast and complete.

### 3.2 Per-function pipeline roles — no change

Verified already scoped (specific table ARNs, specific Bedrock ARNs, scoped
Secrets Manager ARN). No least-privilege change needed. Do not remove
permissions that code actually uses (e.g. `dynamodb:Scan` on `articles` for the
curator/program_generator — required until the GSI migration below).

---

## 4. S3 / CLOUDFRONT CHANGES

### Phase 1 (represented in code, flag-gated, disabled)
- **S3 audio lifecycle (transition only):**
  `aws_s3_bucket_lifecycle_configuration.audio_lifecycle` transitions objects to
  `STANDARD_IA` after `s3_audio_transition_days` (default 90). **No expiration,
  no delete.** Flag `enable_s3_audio_lifecycle`, default off.
  - RISK: negligible; IA has slightly higher per-GB retrieval cost but far lower
    storage cost. Reversible by removing the lifecycle configuration.

### Later phase (documented only — NOT built this phase)
- **CloudFront + private S3 (OAC) for audio:**
  - Target: create a CloudFront distribution with an **Origin Access Control**,
    add a bucket policy allowing only that distribution to read, then enable S3
    Block Public Access and remove the public `s3:GetObject` policy.
  - **Migration without downtime:** (1) create CloudFront + OAC alongside the
    still-public bucket; (2) add the OAC-scoped bucket policy *in addition to*
    the existing public policy; (3) update stored/generated audio URLs to the
    CloudFront domain and let new records use it; (4) once traffic is served via
    CloudFront and old URLs have aged out, enable Block Public Access and remove
    the public policy. Each step is independently reversible.
  - **Risk:** existing audio URLs stored in DynamoDB point at
    `https://dengbej-audio.s3.amazonaws.com/...`. Flipping S3 private **before**
    those URLs are migrated would break playback of older records. Hence the
    additive, staged order above.
  - Note: the frontend site hosting is out of Terraform scope; if the site
    should also move behind CloudFront, that is a separate decision requiring
    knowledge of where the HTML is currently served.

---

## 5. API CHANGES

The API is intentionally public (a listener application). We do **not** add
authentication. Proposed public-read protections, simplest first:

- **Narrow CORS (Phase 1-friendly, cheap, low risk):** change
  `allow_origins = ["*"]` on the `news_api` Function URL to the known site
  origin(s). RISK: if the site origin is misconfigured, the browser blocks API
  calls; easily rolled back to `["*"]`. *(Not changed in code yet — requires the
  confirmed production site origin, which is a HUMAN-REVIEW input.)*
- **Confirm methods:** `news_api` already restricts to `GET` (good). Legacy
  `dengbej_ai` allows `POST` with `allow_headers = ["*"]`; if the legacy
  endpoint is unused, **decommission it** rather than harden it (human decision).
- **Rate limiting / WAF / API Gateway:** evaluated and **not recommended** for
  Phase 1. They add cost and complexity disproportionate to a small
  non-commercial read API. Lambda Function URLs cannot attach WAF directly; that
  would require fronting with CloudFront or API Gateway. Defer unless abuse is
  observed.

---

## 6. DATA RETENTION

Conservative; nothing deletes existing data.

| DATA TYPE | CURRENT RETENTION | PROPOSED RETENTION | WHY | RISK | ROLLBACK |
|---|---|---|---|---|---|
| S3 audio objects | Indefinite, STANDARD | Transition to STANDARD_IA after 90d; **no delete** | Lower storage cost for old audio | Negligible (slightly higher retrieval cost) | Remove lifecycle config |
| Legacy `lambda_logs` (`/aws/lambda/dengbej-summary`) | Never expires (`0`) | 14 days (match other groups) | Bound log growth/cost | Low (older legacy logs age out) | Set retention back to `0` |
| `articles` table | Indefinite | Optional TTL on `expires_at` (attribute-only; deletes only items that carry a past epoch) | Bound growth of transient article rows | Medium — must confirm nothing needs old articles; deletes only once app writes the attribute | Disable TTL; DynamoDB stops expiring |
| `briefings` / `programs` / `events` | Indefinite | **Keep indefinite** (archive/SEO value) | Historical editions are intentionally retained | — | — |

TTL is **not** represented as Terraform in Phase 1 (it is an in-place edit to the
`articles` table block). Applied in its own reviewed step; and only after the
ingester is updated to populate `expires_at`, so no existing item is ever
expired unexpectedly.

---

## 7. DYNAMODB OPTIMIZATION

Two `Scan` operations, both on `articles`, filtering `pub_date > cutoff`:

| Scan | Function | Volume | Filter | Query instead? | GSI required? |
|---|---|---|---|---|---|
| `articles_table.scan` (~line 168) | `todays_five_curator` | ~200 items (per code comment) | `pub_date > :cutoff` | Yes, with a GSI | Yes — GSI hash on a partition key + range `pub_date` |
| `articles_table.scan` (~line 189) | `program_generator` | same table | `pub_date > :cutoff` | Yes, with a GSI | Yes — same GSI |

- **Recommendation:** LOW urgency. At ~200 items the scans are cheap and
  reliable. A `pub_date` GSI (or a fixed partition + `pub_date` sort key) would
  let both convert `Scan`→`Query`, worth doing before the table grows large.
- **Not built this phase:** adding a GSI is an in-place `articles` table edit;
  represented as a proposal only. Adding a GSI is online/non-destructive in
  DynamoDB, but changing the table block warrants its own reviewed apply plus a
  matching code change (Scan→Query). Do **not** remove the `dynamodb:Scan` IAM
  permission until the code no longer scans.

---

## 8. HARDCODED INFRASTRUCTURE VALUES

| Value | Location | Classification | Action |
|---|---|---|---|
| Account id `387276719593` in managed-policy ARN | `main.tf` ~L110 | SHOULD BECOME TERRAFORM REFERENCE | Replace with `data.aws_caller_identity.current.account_id` (later phase; cosmetic, low risk) |
| Function URL in frontend | `frontend/index.html` ~L412 | SHOULD BECOME OUTPUT / ENV VALUE | Already emitted as a TF output; long-term move site to a stable custom domain/CDN (human decision) |
| `aws_region` | `variables.tf` (default `us-east-1`) | SAFE CONSTANT (variable) | Keep |
| Bucket/table/function names | `variables.tf` | SAFE CONSTANT (variable) | Keep |
| Bedrock model id | `variables.tf` | SAFE CONSTANT (variable) | Keep |

No change made in Phase 1 (all cosmetic/low-risk; grouped into a later apply).

---

## 9. COST IMPACT

| Change | Direction | Notes |
|---|---|---|
| Scoped IAM policy (legacy role) | No cost change | IAM is free |
| S3 audio lifecycle → IA (no delete) | **Decreases cost** | IA storage cheaper; small retrieval fee on old objects |
| Legacy log retention 0→14d | **Decreases cost** | Bounds CloudWatch Logs storage |
| DynamoDB TTL (later) | **Decreases cost** | Fewer stored items; TTL deletes are free |
| `pub_date` GSI (later) | **Small increase** | GSI has its own read/write/storage; offset by cheaper Queries vs Scans; on-demand billing keeps it modest |
| CloudFront + private S3 (later) | **Small increase** | CloudFront request/transfer cost; often offset by S3 transfer savings; adds TLS/caching |
| WAF / API Gateway | Would **increase** cost | **Rejected for Phase 1** |

Overall Phase 1 is cost-neutral-to-negative. No new paid component is
introduced. The project stays inexpensive.

---

## 10. MIGRATION ORDER — SAFE APPLY SEQUENCE

Derived from the actual infrastructure. **Precondition for ALL applies:**
configure the real Terraform backend/state and confirm `terraform plan` shows a
true diff (see §0). Each apply below is small and independently reviewable.

- **Apply 0 — State reconciliation (prerequisite, no resource change):**
  configure remote state backend and `terraform init`; `terraform import` or
  refresh so a plan reports `0 to add/change/destroy` for existing resources.
  Do not proceed until this is clean.
- **Apply 1 — Legacy log retention:** set `lambda_logs` retention `0 → 14`.
  Trivial, reversible. (Represented as a documented edit; smallest first.)
- **Apply 2 — IAM least privilege (legacy role):** set
  `manage_least_privilege_legacy_role = true` (adds scoped inline) **and** remove
  the two `*FullAccess` attachments in the same apply, after CloudTrail/Access
  Analyzer review.
- **Apply 3 — S3 audio lifecycle:** set `enable_s3_audio_lifecycle = true`
  (transition-only, no delete).
- **Apply 4 — CloudFront + private S3 (staged, its own mini-sequence):** create
  CloudFront+OAC → add OAC bucket policy alongside public → migrate audio URLs →
  enable Block Public Access + remove public policy. Reversible at each step.
- **Apply 5 — DynamoDB TTL:** update ingester to write `expires_at`, deploy code,
  then add the `ttl{}` block to the `articles` table.
- **Apply 6 — DynamoDB GSI + Scan→Query:** add `pub_date` GSI, deploy the
  curator/program_generator code that Queries, then (optionally) tighten the
  `dynamodb:Scan` IAM permission.
- **Apply 7 — Cosmetic:** replace hardcoded account id with
  `aws_caller_identity` data source.

This exact ordering is a recommendation; re-derive/confirm against the real
state before executing. Never batch multiple applies together.

---

## 11. ROLLBACK PLAN (per change)

- IAM: re-attach the managed policies, remove the scoped inline.
- S3 lifecycle: remove the lifecycle configuration (objects unaffected).
- Log retention: set back to `0`.
- CloudFront/private S3: re-add the public bucket policy and disable Block Public
  Access (kept until step 4 completes, so rollback is immediate); leave/disable
  the distribution.
- TTL: disable TTL on the table (stops expiry immediately).
- GSI: delete the GSI (online) and revert code to Scan.
- Every Phase-1 coded change is flag-gated: setting the flag back to `false`
  removes the resource on the next apply.

---

## 12. VERIFICATION EVIDENCE (this phase)

- `terraform fmt` — clean (formatted `hardening.tf`).
- `terraform validate` — **Success** (after generating gitignored placeholder
  layer zips locally to satisfy a **pre-existing** `filebase64sha256()`
  reference in `todays_five_processor.tf`; these zips are build artifacts, not
  committed).
- `terraform plan -refresh=false` (no apply) — **"58 to add, 0 to change, 0 to
  destroy."** Zero destroy, zero replace. The 58 adds are a no-state artifact
  (§0), not a live-infra proposal. The flag-gated hardening resources do **not**
  appear in the plan (they are inert while disabled).
- Application tests — `run_tests.py`: **391 passed**. MVP contract: **passed**.
  No product behavior changed (infrastructure-only edits).

---

## Explicit answers

- **DOES THIS PLAN MODIFY LIVE AWS?** **NO.** No apply, no deploy, no live
  mutation. `plan`/`validate` are read-only; the only local side effects were
  gitignored placeholder zips.
- **IS IT SAFE TO APPLY (as-is)?** **Not yet, and not from this working copy.**
  With all flags `false`, the *code* change is inert, but the missing Terraform
  state means a blind apply would try to (re)create existing resources. The
  prerequisite is Apply 0 (state reconciliation) so a plan shows a true diff.
  After that, each flag-gated change is individually safe and reversible.
- **Unresolved questions / human input needed:** (1) real Terraform state/backend
  location; (2) the production site origin(s) for CORS narrowing; (3) whether the
  legacy `dengbej-summary` endpoint is still needed (harden vs decommission);
  (4) where the frontend HTML is hosted (for any future CDN move).
