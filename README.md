# Dengbêj AI — Kurdish News Radio

Dengbêj AI is an experimental, no-login **Kurdish news radio** inspired by the
dengbêj oral storytelling tradition. It automatically curates world news,
retells it as short Kurmanji Kurdish broadcasts, and plays it back as a
continuous radio experience.

> Developed through the **AWS Builder Challenges**.
> Article: [Dengbej AI – Kurdish Storytelling with Generative AI](https://builder.aws.com/content/3AtwFZmEnbM4cs3I7y25DHJyJlo/aideas-dengbej-ai-kurdish-storytelling-with-generative-ai)

---

## The Bêje Experience

The homepage is built around a single interaction:

**Choose a program → Bêje! / Tell me! → the program appears and plays**

- **Bilingual UI** — English and Kurmanji (`Kurdî`), toggled live.
- **Programs** — Today's News plus regional/topic programs (World, Middle East,
  Turkey, and the Kurdish regions: Bakur, Rojava, Başûr, Rojhilat, and a
  cross-regional Kurdistan program).
- **Kurmanji narration** — Selected programs are narrated in Kurmanji via
  KurdishTTS, with English (Amazon Polly) narration as a fallback when Kurmanji
  audio is not yet available.
- **Continuous radio** — Play, pause, next, previous, and automatic advancement
  through programs.
- **Freshness** — Each briefing shows whether it was updated recently, X hours
  ago, or is an archive edition, based on the record timestamp (not the browser
  clock).

## What is a Dengbêj?

For centuries, dengbêjs have preserved Kurdish history through oral
storytelling — sharing news, memories, and culture through spoken narratives
that connect communities. Dengbêj AI reimagines that tradition with generative
AI and serverless AWS technology.

---

## Architecture

A fully serverless pipeline. Each stage is an independent AWS Lambda function,
orchestrated by Amazon EventBridge schedules.

```
RSS Feeds (BBC, DW, Al Jazeera)
    │  every 6 hours
    ▼
News Ingester (Lambda) ──────────────► dengbej-articles (DynamoDB)
    │  06:00 / 18:00 UTC
    ▼
Today's 5 Curator (Lambda + Bedrock) ─► dengbej-briefings (DynamoDB)
    │  ~15 min later
    ▼
Story Processor (Lambda + Bedrock)     summaries + Kurmanji translation
    │
    ▼
Program Generator (Lambda + Bedrock)  ─► dengbej-programs (DynamoDB)
    │                                     classification + Kurmanji scripts + headline_ku
    ▼
Daily Audio (Lambda + Bedrock + KurdishTTS / Polly)
    │  Kurmanji WAV (KurdishTTS), English MP3 fallback (Polly)
    ▼
Audio Storage (S3, public read) ──────► News API (Lambda, Function URL)
                                             │
                                             ▼
                                   Frontend (AWS Amplify)
```

### AWS services

| Service | Role |
|---------|------|
| Amazon Bedrock (Claude Haiku) | Summarization, Kurmanji translation, broadcast scripts, headline translation |
| KurdishTTS | Kurmanji (Kurdî) speech synthesis |
| Amazon Polly | English narration fallback |
| AWS Lambda | All compute (ingester, curator, processor, program generator, daily audio, news API) |
| Amazon DynamoDB | Articles, briefings, programs, and the monthly TTS quota record |
| Amazon EventBridge | Scheduled pipeline triggers |
| Amazon S3 | Audio storage (public read) |
| AWS Amplify | Static frontend hosting + previews |

### Data model highlights

- `dengbej-briefings` — Today's 5 briefing per day; `daily_audio_meta` holds
  `audio_url` (legacy = English), `audio_url_en`, and `audio_url_ku`.
- `dengbej-programs` — Per-program briefings with `script_ku`, `headline_ku`,
  and `audio_url_ku`. The synthetic `tts-quota` / `YYYY-MM` record tracks monthly
  KurdishTTS character usage.

The News API returns `url`, `url_en`, and `url_ku` for both briefings and
programs so the frontend can select audio by language. Legacy `url` always
points to English so older/frozen clients keep working.

---

## KurdishTTS Integration & Quota Safeguards

Kurmanji narration is generated via the [KurdishTTS](https://www.kurdishtts.com)
API (`POST /api/tts-proxy`, WAV output, `kurmanji_…` speaker).

- **Disabled by default in scheduled runs** — `KURDISH_TTS_ENABLED=false`. Kurdish
  audio is produced only via a controlled batch event.
- **API key** — read server-side from AWS Secrets Manager
  (`dengbej-ai/kurdish-tts-api-key`). Never in source, logs, or the frontend.
- **Monthly budget** — `KURDISH_TTS_MONTHLY_BUDGET_CHARS` (default 18,000, a
  safety margin below the free-tier allowance). Tracked atomically in DynamoDB.
- **Fail closed** — synthesis never begins unless a character reservation is
  confirmed persisted in DynamoDB; any error → skip (with refund).
- **Dry run** — `generate_kurdish_batch` with `dry_run:true` reports candidates
  and character totals while making **zero** synthesis calls, quota writes, S3
  writes, or DynamoDB updates.
- **WAV assembly** — long scripts are chunked at sentence boundaries (≤480 chars
  free-tier / configurable) and reassembled into one valid WAV via the standard
  `wave` module.
- **Speed** — `KURDISH_TTS_SPEED` (default `1.1`), validated against the API
  range and safely defaulted.

Kurdish narration is a **beta**. English Polly narration remains the reliable
fallback and is never overwritten.

---

## Branches

| Branch | Purpose |
|--------|---------|
| `feature/beje-radio-v2` | Current Bêje radio app (Kurmanji + English) — the working line |
| `feature/kurmanji-tts` | KurdishTTS integration development branch |
| `feature/public-beta-polish` | Public-beta improvements (audio selection, freshness, copy) |
| `feature/aws-builder-challenge` | Frozen challenge submission — **do not modify** |
| `feature/aws-builder-release` | Frozen release snapshot — **do not modify** |
| `backup/kiro-experimental-api-processor` | Archived experimental approach |

---

## Testing

All backend Lambdas and the frontend have test suites. Each Lambda uses the same
`lambda_function.py` filename, so tests run per-directory to avoid import
collisions.

```bash
python -m venv .venv && source .venv/bin/activate
pip install boto3 requests beautifulsoup4 feedparser pytest
python run_tests.py            # runs every suite
python run_tests.py -v         # verbose
```

Frontend tests (in `frontend/tests/`) validate HTML/CSS/JS structure, public
copy, the freshness indicator, and language-aware audio selection. The audio
logic is executed with Node when available.

Tests never make live Bedrock, Polly, or KurdishTTS calls — external clients are
mocked (see the autouse `conftest.py` fixtures). Running the suite consumes **no**
TTS quota.

---

## Safety Boundaries

- No authentication, subscriptions, ads, or personalization.
- Kurdish TTS is off in scheduled runs; audio is generated only through the
  controlled, budgeted batch event.
- The API key is confined to Secrets Manager and never logged or shipped.
- Frozen challenge branches are never modified.
- The stable V2 deployment is only changed through reviewed branch merges.

---

## Roadmap (near-term)

- Evaluate and finalize the Kurmanji speaker for naturalness and pronunciation.
- Harden the quota reservation counter before enabling scheduled Kurdish synthesis.
- Convert long WAV output to a compressed format (e.g. Opus) to cut bandwidth.
- Expand Kurmanji narration coverage across all programs once quota allows.
- Backfill Kurdish audio for daily briefings on a controlled cadence.
