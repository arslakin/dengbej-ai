# Dengbej AI — News Source Documentation

This document describes the news sources used by the Dengbej AI ingestion pipeline, their RSS feed URLs, verification status, and usage/attribution considerations.

---

## Editorial Principles

- Always preserve and display the original source URL.
- Do not present AI-generated summaries as original reporting.
- Summaries must stay grounded in source material.
- Clearly distinguish generated summaries from source articles.
- Never republish full article text from any source.
- Always attribute the source by name.
- Do not introduce unsupported facts during summarization or translation.

---

## Sources

### 1. BBC News World

| Field | Value |
|-------|-------|
| Feed URL | `https://feeds.bbci.co.uk/news/world/rss.xml` |
| Format | RSS 2.0 |
| Verified | 2026-08-07 (live, returning current articles) |
| Update frequency | ~15 min TTL |

**Usage policy:**
- RSS is free for personal and non-commercial use.
- Business/commercial use requires BBC permission and may incur a fee.
- Must attribute as "BBC News" or "bbc.co.uk/news".
- Must NOT use the BBC logo or other BBC trademarks.
- Must link to the original article.
- Must NOT republish full article text.

**What we store:** Headline, source name, original URL, publication date, RSS description (short summary provided in the feed), ingestion timestamp, processing status.

**What we do NOT store:** Full article body text.

**Source:** [BBC Terms — RSS Feeds](https://www.bbc.co.uk/terms/can-i-use-bbc-metadata-and-rss-feeds/)

---

### 2. Deutsche Welle (DW) English

| Field | Value |
|-------|-------|
| Feed URL | `https://rss.dw.com/rdf/rss-en-all` |
| Format | RSS 1.0 (RDF) |
| Verified | 2026-08-07 (live, returning current articles) |
| Update frequency | ~4 times/hour |

**Usage policy:**
- DW RSS feed is publicly accessible.
- DW does NOT permit republishing full articles without written permission.
- Written permission required for any commercial content use.
- Private use is permitted.
- Attribution: "Deutsche Welle" with link to original.

**What we store:** Headline, source name, original URL, publication date, RSS description/title, ingestion timestamp, processing status.

**What we do NOT store:** Full article body text.

**Source:** [DW — Use of DW Content](https://corporate.dw.com/en/use-of-dw-content/a-6532839), [DW — Sharing and Adapting](https://corporate.dw.com/en/sharing-re-posting-and-adapting-dw-content/a-68754795)

---

### 3. Al Jazeera English

| Field | Value |
|-------|-------|
| Feed URL | `https://www.aljazeera.com/xml/rss/all.xml` |
| Format | RSS 2.0 |
| Verified | 2026-08-07 (feed responds with content-type `application/rss+xml`) |
| Update frequency | Continuous |

**Usage policy:**
- All Al Jazeera content is copyrighted by Al Jazeera Media Network.
- Terms of use prohibit reproduction without permission.
- No explicit RSS reuse licence found in public documentation.
- Most restrictive of the three sources.

**What we store:** Headline, source name, original URL, publication date, RSS description (feed summary), ingestion timestamp, processing status.

**What we do NOT store:** Full article body text.

**Our approach:** Use RSS metadata for discovery only. Never display Al Jazeera's article text directly. Always link to the original. If we later generate AI summaries, they will be clearly labelled as AI-generated and will link to the source.

**Source:** [Al Jazeera Terms and Conditions](https://www.aljazeera.com/terms-and-conditions/)

---

## Adding or Disabling Sources

Sources are configured in `backend/news_ingester/feeds_config.json`. Each source has an `enabled` flag that can be set to `false` to disable ingestion without changing Lambda code.

To add a new source:
1. Verify the RSS/Atom feed URL is accessible and returns valid XML.
2. Review the source's terms of use regarding RSS syndication and content reuse.
3. Document the source in this file with attribution requirements.
4. Add an entry to `feeds_config.json` with `enabled: true`.

---

## Attribution Display (Future Frontend)

When displaying content from these sources, the frontend must:
- Show the source name prominently (e.g., "Source: BBC News").
- Provide a clickable link to the original article.
- Label any AI-generated summary clearly (e.g., "AI-generated summary").
- Never present summaries as original journalism.
