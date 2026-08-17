# Implementation Plan: AWS Builder Release

## Overview

Frontend-only release polish sprint for the AWS Builder Weekend Challenge. All changes are to static HTML/CSS/JS files served by Amplify. No backend, Lambda, or Terraform modifications. Tasks are ordered by dependency: branch setup → homepage enhancements → new pages → footer consistency → routing → validation.

## Tasks

- [ ] 1. Branch setup and header/footer shared structure
  - [ ] 1.1 Create feature branch and update shared header with site navigation
    - Create branch `feature/aws-builder-release` from `feature/program-backend-v1`
    - Update the header in `frontend/index.html` to include site navigation links (Home, About, How It Works)
    - Make the DENGBEJ wordmark a link to `/`
    - _Requirements: 6.7, 7.6, 8.6_

  - [ ] 1.2 Implement the shared footer component in index.html
    - Replace the existing minimal footer with the full footer containing: nav links (Home, About, How It Works, GitHub, AWS Builder Article), AWS service badges (Lambda, Bedrock, Polly, S3, DynamoDB, Amplify), and tagline
    - Add footer CSS styles for `.footer-nav`, `.footer-services`, `.service-badge`, `.footer-tagline`
    - _Requirements: 2.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [ ] 2. Homepage content enhancements
  - [ ] 2.1 Add cultural context and Builder Article link sections
    - Add a `.builder-link-banner` section above the stories area with a prominent link to the AWS Builder Article URL opening in a new tab
    - Add a `.cultural-context` section with "What is Dengbej AI?" description and "What is a Dengbêj?" cultural context paragraphs
    - Position the builder link banner before stories so it's visible without scrolling to content
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2_

  - [ ] 2.2 Implement audio placeholder replacing disabled button
    - Modify `updateBejeState()` to replace the disabled `Bêje!` button with a textual placeholder message when audio is unavailable
    - Display "🎙️ Kurdish audio — coming soon" (English) or "🎙️ Dengê Kurdî — zû tê" (Kurdish) based on active language
    - Keep the button only when audio is actually available
    - Add `.audio-placeholder` CSS styling
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ]* 2.3 Write property tests for audio placeholder behavior
    - **Property 3: Audio placeholder replaces disabled button**
    - **Property 4: Audio placeholder language matches active language**
    - **Validates: Requirements 4.1, 4.2, 4.3**

- [ ] 3. Story card enhancements
  - [ ] 3.1 Add image rendering and Kurdish headline support to story cards
    - Add `story.source_image_url` image rendering with `<img class="story-image">`, `loading="lazy"`, and `onerror="this.style.display='none'"` for graceful failure
    - Update headline rendering to use `story.headline_ku` when Kurdish language is active and the field is populated
    - Add `.story-image` CSS (full-width, max-height 200px, object-fit cover, border-radius)
    - _Requirements: 5.1, 5.2, 5.5_

  - [ ] 3.2 Ensure source attribution and original article links are present
    - Verify and enhance `renderBriefing` to always show primary source name attribution
    - Ensure original article links have `target="_blank"` and `rel="noopener noreferrer"`
    - Apply same enhancements to `renderProgramView` story cards
    - _Requirements: 5.3, 5.4_

  - [ ]* 3.3 Write property tests for story card rendering
    - **Property 5: Story image conditional rendering**
    - **Property 6: Kurdish headline substitution**
    - **Property 7: Source attribution presence**
    - **Property 8: Original article link opens in new tab**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

- [ ] 4. Checkpoint - Verify homepage changes
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Create About page
  - [ ] 5.1 Create frontend/about.html with full page structure
    - Create `frontend/about.html` with the shared CSS variables, header with navigation, and footer
    - Include sections: Hero (title + description), What is a Dengbêj? (cultural context), Motivation, AWS Services (with service roles), Roadmap (planned features)
    - Implement language toggle with `.lang-en` / `.lang-ku` class toggling for bilingual content
    - Provide bilingual content for all sections (English and Kurdish)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [ ] 6. Create Architecture page
  - [ ] 6.1 Create frontend/how-it-works.html with pipeline diagram
    - Create `frontend/how-it-works.html` with shared CSS variables, header, and footer
    - Build a pure CSS/HTML architecture diagram using flexbox stages: RSS Feeds → Lambda (Ingest) → Bedrock (Summarize) → DynamoDB (Store) → Amplify (Serve)
    - Label each stage with its AWS service name and role
    - Describe the data flow from news ingestion to frontend delivery
    - Make diagram responsive: horizontal on desktop, vertical stack below 600px
    - Implement language toggle for bilingual content
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 7. Footer consistency and story.html update
  - [ ] 7.1 Add the shared footer to story.html
    - Open `frontend/story.html` and replace or add the full footer component (nav links, AWS badges, tagline)
    - Ensure the footer matches the exact structure used in index.html, about.html, and how-it-works.html
    - _Requirements: 8.6_

  - [ ]* 7.2 Write property test for footer consistency
    - **Property 1: Footer consistency across all pages**
    - **Validates: Requirements 2.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**

- [ ] 8. Amplify URL rewrites
  - [ ] 8.1 Create frontend/_redirects file for clean URLs
    - Create `frontend/_redirects` with rewrite rules: `/about` → `/about.html` (200), `/how-it-works` → `/how-it-works.html` (200)
    - Verify all internal navigation links use clean URLs (`/about`, `/how-it-works`) not `.html` extensions
    - _Requirements: 9.7_

- [ ] 9. Checkpoint - Full integration check
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Release validation
  - [ ] 10.1 Validate frontend rendering and API connectivity
    - Verify no JavaScript console errors on all pages (index.html, about.html, how-it-works.html, story.html)
    - Confirm `/news/today` API returns HTTP 200 with valid JSON
    - Confirm `/news/program/today` returns valid JSON
    - Verify mobile viewport (375px) renders without horizontal overflow on all pages
    - Verify all program selections load data or empty state without errors
    - Confirm all pages use root-relative paths compatible with Amplify hosting
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [ ]* 10.2 Write property tests for program selection and API responses
    - **Property 9: Program selection renders data or empty state without errors**
    - **Property 10: All pages use relative asset paths**
    - **Property 11: API program endpoint returns valid JSON**
    - **Validates: Requirements 9.3, 9.5, 9.7**

- [ ] 11. Final checkpoint - Release ready
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- No backend/Lambda/Terraform changes in this sprint — frontend only
- The existing 194 backend tests must continue to pass (no backend code is touched)
- All pages use inline CSS and inline JS — no external stylesheets or build step
- Shared design is achieved through duplicated CSS variables per page (acceptable for 4 pages)
- Property tests validate universal correctness properties from the design document
- The branch is created from `feature/program-backend-v1` to include all existing backend work

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "3.1", "3.2"] },
    { "id": 3, "tasks": ["2.3", "3.3", "5.1", "6.1"] },
    { "id": 4, "tasks": ["7.1", "8.1"] },
    { "id": 5, "tasks": ["7.2"] },
    { "id": 6, "tasks": ["10.1"] },
    { "id": 7, "tasks": ["10.2"] }
  ]
}
```
