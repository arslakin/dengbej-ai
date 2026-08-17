# Design Document: AWS Builder Release

## Architecture Overview

This is a frontend-only polish sprint targeting an existing vanilla HTML/CSS/JS static site hosted on AWS Amplify. The architecture remains unchanged: static HTML pages served by Amplify, with client-side JavaScript calling a Lambda Function URL API.

```
┌─────────────────────────────────────────────────────────┐
│  AWS Amplify (Static Hosting)                           │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐   │
│  │index.html│  │about.html│  │how-it-works.html   │   │
│  └──────────┘  └──────────┘  └────────────────────┘   │
│  ┌──────────┐                                          │
│  │story.html│  (existing, unchanged)                   │
│  └──────────┘                                          │
└─────────────────────────────────────────────────────────┘
          │
          │ fetch() — client-side JS
          ▼
┌─────────────────────────────────────────────────────────┐
│  Lambda Function URL (existing, no changes)             │
│  /news/today, /news/program/{id}, /news/YYYY-MM-DD     │
└─────────────────────────────────────────────────────────┘
```

**Key constraint:** No build tools, no framework, no SPA routing. Each page is a standalone `.html` file with inline CSS and inline JavaScript. Shared design is achieved through consistent CSS variable definitions duplicated per page (no external stylesheet needed for 3-4 pages).

## Components

### 1. Page Structure

Each HTML page follows this template structure:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <!-- meta, title, inline <style> with shared CSS variables -->
</head>
<body>
  <header><!-- shared header: wordmark + lang toggle + nav --></header>
  <main><!-- page-specific content --></main>
  <footer><!-- shared footer: nav links, AWS badges, builder link --></footer>
  <script><!-- page-specific JS (if any) --></script>
</body>
</html>
```

### 2. Shared Header Component

The header is duplicated HTML across all pages (acceptable for 4 pages with no build step):

```html
<header>
  <div class="container">
    <div class="header-inner">
      <a href="/" class="wordmark-link"><h1 class="wordmark">DENGBEJ</h1></a>
      <nav class="site-nav" aria-label="Main navigation">
        <a href="/">Home</a>
        <a href="/about">About</a>
        <a href="/how-it-works">How It Works</a>
      </nav>
      <nav class="lang-toggle" aria-label="Language selection">
        <button type="button" id="btn-en" aria-pressed="true">English</button>
        <button type="button" id="btn-ku" aria-pressed="false">Kurdî</button>
      </nav>
    </div>
  </div>
</header>
```

### 3. Shared Footer Component

```html
<footer>
  <div class="container">
    <nav class="footer-nav" aria-label="Footer navigation">
      <a href="/">Home</a>
      <a href="/about">About</a>
      <a href="/how-it-works">How It Works</a>
      <a href="https://github.com/akinarslan/dengbej-ai" target="_blank" rel="noopener noreferrer">GitHub</a>
      <a href="https://builder.aws.com/content/3AtwFZmEnbM4cs3I7y25DHJyJlo/aideas-dengbej-ai-kurdish-storytelling-with-generative-ai" target="_blank" rel="noopener noreferrer">AWS Builder Article</a>
    </nav>
    <div class="footer-services">
      <span class="service-badge">Lambda</span>
      <span class="service-badge">Bedrock</span>
      <span class="service-badge">Polly</span>
      <span class="service-badge">S3</span>
      <span class="service-badge">DynamoDB</span>
      <span class="service-badge">Amplify</span>
    </div>
    <p class="footer-tagline">Inspired by the dengbêj tradition · Built on AWS</p>
  </div>
</footer>
```

### 4. Homepage (index.html) — Modifications

#### 4.1 Cultural Context Section

Added above the stories section, below the radio area:

```html
<section class="cultural-context" aria-labelledby="what-is-heading">
  <div class="builder-link-banner">
    <a href="https://builder.aws.com/content/3AtwFZmEnbM4cs3I7y25DHJyJlo/aideas-dengbej-ai-kurdish-storytelling-with-generative-ai"
       target="_blank" rel="noopener noreferrer">
      Read the full project story on AWS Builder →
    </a>
  </div>
  <h2 id="what-is-heading">What is Dengbej AI?</h2>
  <p><!-- project description --></p>
  <h3>What is a Dengbêj?</h3>
  <p><!-- cultural context about Kurdish oral tradition --></p>
</section>
```

The Builder Article Link banner is placed above the fold, before stories load, ensuring visibility without scrolling.

#### 4.2 Audio Placeholder Logic

Replace the disabled `Bêje!` button pattern with a text-only placeholder when audio is unavailable:

```javascript
function updateBejeState() {
  var bejeRow = document.getElementById("beje-row");
  // ...
  if (!audioAvailable) {
    // Remove button, show text placeholder
    bejeRow.innerHTML = '<p class="audio-placeholder" id="audio-placeholder">' +
      (currentLang === "ku"
        ? "🎙️ Dengê Kurdî — zû tê"
        : "🎙️ Kurdish audio — coming soon") +
      '</p>';
  } else {
    // Show the play button
    bejeRow.innerHTML = '<button class="beje-btn" ...>Bêje!</button>' +
      '<p class="audio-status">...</p>';
  }
}
```

#### 4.3 Story Card Image & Kurdish Headline

Enhanced `renderBriefing` function to support images and Kurdish headlines:

```javascript
function renderStoryCard(story, index) {
  var headline = currentLang === "ku" && story.headline_ku
    ? story.headline_ku
    : story.headline;
  var imageHtml = "";
  if (story.source_image_url) {
    imageHtml = '<img class="story-image" src="' + escapeHtml(story.source_image_url) +
      '" alt="" loading="lazy" onerror="this.style.display=\'none\'">';
  }
  // ... rest of card rendering
}
```

CSS for story images:
```css
.story-image {
  width: 100%;
  max-height: 200px;
  object-fit: cover;
  border-radius: 6px;
  margin-bottom: 0.75rem;
}
```

### 5. About Page (about.html)

A static informational page with the following sections:

| Section | Content |
|---------|---------|
| Hero | Project title + one-line description |
| What is a Dengbêj? | Cultural context about Kurdish oral storytelling tradition |
| Motivation | Why this project was built |
| AWS Services | List of services with brief role descriptions |
| Roadmap | Planned features (TTS improvements, more languages, etc.) |

No JavaScript required beyond the language toggle (for bilingual content).

### 6. Architecture Page (how-it-works.html)

Displays the AWS pipeline using a pure CSS/HTML diagram (no external images, no SVG dependencies):

```html
<div class="architecture-diagram">
  <div class="pipeline-stage">
    <div class="stage-icon">📡</div>
    <div class="stage-label">RSS Feeds</div>
    <div class="stage-desc">BBC, DW, Al Jazeera</div>
  </div>
  <div class="pipeline-arrow">→</div>
  <div class="pipeline-stage">
    <div class="stage-icon">⚡</div>
    <div class="stage-label">Lambda</div>
    <div class="stage-desc">Ingest & process</div>
  </div>
  <!-- ... more stages ... -->
</div>
```

The diagram uses CSS flexbox/grid with responsive stacking on mobile (vertical flow below 600px).

### 7. URL Routing Strategy

Amplify naturally serves `about.html` at `/about.html`. For clean URLs (`/about` without extension), add rewrites to `amplify.yml` or the Amplify console:

```yaml
customHeaders: []
redirects:
  - source: /about
    target: /about.html
    status: '200'
  - source: /how-it-works
    target: /how-it-works.html
    status: '200'
```

Alternatively, if using `_redirects` file in the frontend folder:

```
/about    /about.html    200
/how-it-works    /how-it-works.html    200
```

Both approaches work with Amplify static hosting. Internal links use the clean URLs (`/about`, `/how-it-works`).

## Data Flow

### API Response Shape (existing, no changes)

The frontend consumes two endpoints:

**GET /news/today** returns:
```json
{
  "date": "2025-01-15",
  "generated_at": "...",
  "story_count": 5,
  "stories": [
    {
      "rank": 1,
      "headline": "...",
      "headline_ku": "...",
      "category": "politics",
      "summary_en": "...",
      "summary_ku": "...",
      "source_image_url": "https://...",
      "primary_source": { "name": "BBC", "url": "https://..." },
      "supporting_sources": [{ "name": "DW", "url": "..." }],
      "published_at": "..."
    }
  ],
  "daily_audio": {
    "available": false,
    "script_available": true,
    "url": null
  }
}
```

**GET /news/program/{id}** returns:
```json
{
  "program_id": "today",
  "label_ku": "Nûçeyên Îro",
  "label_en": "Today's News",
  "story_count": 5,
  "stories": [...],
  "script_ku": "...",
  "audio": { "available": false, "url": null }
}
```

The frontend uses `headline_ku` and `source_image_url` fields that may or may not be present in the API response. The rendering logic handles missing fields gracefully with fallbacks.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| API returns 404/500 | Show "briefing unavailable" with retry button |
| Image URL fails to load | `onerror` handler hides the `<img>` element |
| Program returns 0 stories | Show bilingual empty state message |
| `headline_ku` missing | Fall back to English headline |
| `source_image_url` missing | No image rendered, no layout shift |
| JavaScript disabled | Page structure visible but no dynamic content |

## Interfaces

### Language Toggle Interface

All pages share the language toggle behavior:

```javascript
// Minimal language toggle for static pages (about, how-it-works)
var currentLang = sessionStorage.getItem("dengbej-lang") || "en";

function setLanguage(lang) {
  currentLang = lang;
  sessionStorage.setItem("dengbej-lang", lang);
  document.getElementById("btn-en").setAttribute("aria-pressed", lang === "en");
  document.getElementById("btn-ku").setAttribute("aria-pressed", lang === "ku");
  document.documentElement.lang = lang === "ku" ? "ku" : "en";
  // Toggle visibility of .lang-en / .lang-ku elements
  document.querySelectorAll(".lang-en").forEach(function(el) {
    el.style.display = lang === "en" ? "" : "none";
  });
  document.querySelectorAll(".lang-ku").forEach(function(el) {
    el.style.display = lang === "ku" ? "" : "none";
  });
}
```

Static pages use CSS class toggling for bilingual content:
```html
<p class="lang-en">English text here</p>
<p class="lang-ku">Nivîsa Kurdî li vir</p>
```

### Story Card Rendering Interface

```javascript
// Enhanced story card renderer
function renderStoryCard(story, index) {
  // Input: story object from API, 0-based index
  // Output: HTML string for one story article

  var headline = currentLang === "ku" && story.headline_ku
    ? story.headline_ku : story.headline;
  var summary = currentLang === "ku"
    ? (story.summary_ku || story.summary_en)
    : story.summary_en;
  var imageUrl = story.source_image_url || null;
  var source = story.primary_source ? story.primary_source.name : "";
  var sourceUrl = story.primary_source ? story.primary_source.url : "";

  // Returns complete <article> HTML string
}
```

## File Structure (after sprint)

```
frontend/
├── index.html          (modified — homepage with all enhancements)
├── about.html          (new — About page)
├── how-it-works.html   (new — Architecture/How It Works page)
├── story.html          (existing — unchanged, gets new footer)
└── _redirects          (new — Amplify URL rewrites)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Footer consistency across all pages

*For any* page in the application (index.html, about.html, how-it-works.html, story.html), the rendered footer SHALL contain navigation links to Home, About, How It Works, GitHub, and the AWS Builder Article.

**Validates: Requirements 2.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**

### Property 2: Empty program displays bilingual empty state

*For any* program selection that returns zero stories from the API, the Radio UI SHALL render an empty state message containing text in both Kurdish and English.

**Validates: Requirements 3.2**

### Property 3: Audio placeholder replaces disabled button

*For any* program state where audio is not available, the Radio UI SHALL NOT render a disabled button element, and SHALL instead render a textual placeholder message.

**Validates: Requirements 4.1, 4.2**

### Property 4: Audio placeholder language matches active language

*For any* language setting (English or Kurdish), when audio is unavailable the placeholder text SHALL be displayed in the corresponding language.

**Validates: Requirements 4.3**

### Property 5: Story image conditional rendering

*For any* story object with a non-empty `source_image_url` field, the rendered story card SHALL contain an `<img>` element with its `src` attribute set to that URL.

**Validates: Requirements 5.1**

### Property 6: Kurdish headline substitution

*For any* story object with a non-empty `headline_ku` field, when the active language is Kurdish, the rendered story card SHALL display `headline_ku` as the headline text instead of the English headline.

**Validates: Requirements 5.2**

### Property 7: Source attribution presence

*For any* story object with a primary source name, the rendered story card SHALL include text identifying that source.

**Validates: Requirements 5.3**

### Property 8: Original article link opens in new tab

*For any* story object with an original article URL, the rendered story card SHALL contain an anchor element with `target="_blank"` pointing to that URL.

**Validates: Requirements 5.4**

### Property 9: Program selection renders data or empty state without errors

*For any* program identifier in the PROGRAMS array, selecting that program SHALL result in either story cards being rendered or the empty state message being displayed, without throwing JavaScript errors.

**Validates: Requirements 9.5**

### Property 10: All pages use relative asset paths

*For any* page in the application, all internal navigation links and asset references SHALL use relative paths (starting with `/` for root-relative) compatible with Amplify static hosting, not absolute filesystem paths.

**Validates: Requirements 9.7**

### Property 11: API program endpoint returns valid JSON

*For any* valid program identifier from the PROGRAMS array, calling `/news/program/{id}` SHALL return a parseable JSON response.

**Validates: Requirements 9.3**
