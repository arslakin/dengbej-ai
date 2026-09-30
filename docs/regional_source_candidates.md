# Dengbej AI — Regional Source Candidates (Research Only)

Status: **research / candidate list — NOT approved for ingestion**

This document is a research backlog of *possible* news sources for the four
Kurdish regional programs (Bakur, Rojhilat, Rojava, Başûr). It exists so that
source expansion can be discussed and reviewed safely.

## What this document is NOT

- It is **not** production configuration. Production feeds live only in
  `backend/news_ingester/feeds_config.json`. Nothing here is wired into
  ingestion.
- Listing a publisher here does **not** approve it, endorse it, or grant
  permission to ingest it.
- The fields below (region, language, feed URL, etc.) are best-effort research
  notes. Where a value is unknown it is marked as such rather than guessed.

## Approval gate (both conditions required)

A candidate may only be promoted to production ingestion when **BOTH** of the
following are true and have been signed off by a human maintainer:

1. **RSS/feed availability verified** — the feed URL has been confirmed to
   exist, return valid XML/Atom, and carry current articles.
2. **Reuse/republishing terms reviewed and approved** — the publisher's terms
   for RSS syndication, metadata reuse, and attribution have been read and are
   compatible with this project's editorial principles (see
   `docs/sources.md` → *Editorial Principles*).

Until both are met, a candidate stays in this file with its status fields
unchanged. Promotion is a deliberate, separate change — not part of adding a
row here.

## Status legend

- **RSS status:** `verified` · `unverified` · `unavailable`
- **Reuse/licensing status:** `verified` · `requires review` · `unknown`

All rows below are currently `unverified` for RSS and `requires review` or
`unknown` for licensing, because no feed has been fetched and no terms have
been reviewed as part of creating this backlog. These MUST be confirmed by a
human before any promotion.

---

## Bakur (Kurdish news in Turkey / Northern Kurdistan)

### Candidate: Bianet (English service)
| Field | Value |
|-------|-------|
| Publisher | Bianet (Bağımsız İletişim Ağı) |
| Region | Turkey (Bakur-relevant coverage) |
| Language(s) | English, Turkish |
| Homepage | https://bianet.org/english |
| Possible RSS/feed URL | Unknown — needs research (check for `/rss` or category feeds) |
| RSS status | unverified |
| Reuse/licensing status | requires review |
| Notes | Independent outlet with regular Kurdish-rights coverage. Confirm feed existence and syndication terms before any use. Not all Bianet content is Kurdish-specific — classifier must still distinguish Bakur from general Turkey. |

### Candidate: Mezopotamya Ajansı (MA)
| Field | Value |
|-------|-------|
| Publisher | Mezopotamya Ajansı |
| Region | Turkey / Bakur |
| Language(s) | Turkish, Kurdish (Kurmanji) |
| Homepage | Needs verification (agency domains have changed over time) |
| Possible RSS/feed URL | Unknown — needs research |
| RSS status | unverified |
| Reuse/licensing status | unknown |
| Notes | Domain stability and legal status must be checked carefully before consideration. Do not ingest without verified feed and reviewed, approved terms. |

---

## Rojhilat (Kurdish news in Iran / Eastern Kurdistan)

### Candidate: Kurdistan Human Rights Network (KHRN)
| Field | Value |
|-------|-------|
| Publisher | Kurdistan Human Rights Network |
| Region | Iran / Rojhilat |
| Language(s) | English (also Kurdish, Farsi) |
| Homepage | https://kurdistanhumanrights.org |
| Possible RSS/feed URL | Unknown — likely a WordPress feed (`/feed/`) but must be confirmed |
| RSS status | unverified |
| Reuse/licensing status | requires review |
| Notes | Rights-focused, not general newswire. Coverage is Rojhilat-relevant. Confirm feed and licensing; check whether attribution/reuse terms are published. |

### Candidate: Rudaw (Rojhilat desk)
| Field | Value |
|-------|-------|
| Publisher | Rudaw Media Network |
| Region | Based in Başûr; covers Rojhilat among other regions |
| Language(s) | English, Kurdish (Sorani/Kurmanji), Arabic |
| Homepage | https://www.rudaw.net/english |
| Possible RSS/feed URL | Unknown — check for section/category feeds |
| RSS status | unverified |
| Reuse/licensing status | requires review |
| Notes | Broad regional outlet; a general Iran story from Rudaw must NOT be auto-classified as Rojhilat. Editorial independence considerations should be part of the review. |

---

## Rojava (Kurdish news in NE Syria)

### Candidate: North Press Agency
| Field | Value |
|-------|-------|
| Publisher | North Press Agency |
| Region | Northeast Syria / Rojava |
| Language(s) | English, Arabic, Kurdish |
| Homepage | https://npasyria.com |
| Possible RSS/feed URL | Unknown — needs research |
| RSS status | unverified |
| Reuse/licensing status | requires review |
| Notes | Focused on NE Syria. Confirm feed availability and syndication/attribution terms before any use. |

### Candidate: ANHA / Hawar News Agency
| Field | Value |
|-------|-------|
| Publisher | Hawar News Agency (ANHA) |
| Region | Northeast Syria / Rojava |
| Language(s) | Kurdish, Arabic, English |
| Homepage | Needs verification (domain has varied) |
| Possible RSS/feed URL | Unknown — needs research |
| RSS status | unverified |
| Reuse/licensing status | unknown |
| Notes | Verify domain, feed, and terms. Do not ingest without both verifications and human approval. |

---

## Başûr (Kurdistan Region of Iraq)

### Candidate: Rudaw (Başûr / KRG desk)
| Field | Value |
|-------|-------|
| Publisher | Rudaw Media Network |
| Region | Kurdistan Region of Iraq (Başûr) |
| Language(s) | English, Kurdish (Sorani/Kurmanji), Arabic |
| Homepage | https://www.rudaw.net/english |
| Possible RSS/feed URL | Unknown — check for section/category feeds |
| RSS status | unverified |
| Reuse/licensing status | requires review |
| Notes | Same publisher appears under Rojhilat; a single feed may span regions, so per-story classification still applies. Review terms once. |

### Candidate: Kurdistan24
| Field | Value |
|-------|-------|
| Publisher | Kurdistan24 |
| Region | Kurdistan Region of Iraq (Başûr) |
| Language(s) | English, Kurdish (Sorani/Kurmanji), Arabic, Turkish |
| Homepage | https://www.kurdistan24.net/en |
| Possible RSS/feed URL | Unknown — needs research |
| RSS status | unverified |
| Reuse/licensing status | requires review |
| Notes | Broad KRG-region outlet. Confirm feed and reuse terms; editorial-independence context should inform the review. |

---

## Cross-cutting notes

- **Classification still applies per story.** Even after a regional publisher is
  approved, each article is classified individually. A general Turkey story from
  a Bakur-oriented outlet is still general Turkey, and a general Iran story from
  a Rojhilat-oriented outlet is still general Iran. The program classifier
  (`backend/program_classifier/programs.py`) enforces this and is covered by
  tests in `backend/program_classifier/tests/test_classification.py`.
- **No full-text republishing.** Any approved source is subject to the same
  editorial rules as existing sources: store metadata only, always link to the
  original, attribute by name, never present summaries as original reporting.
- **Verification is a human step.** Feed reachability and licensing review are
  intentionally not automated here; they require human judgement and sign-off.
