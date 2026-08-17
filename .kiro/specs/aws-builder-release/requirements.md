# Requirements Document

## Introduction

This specification defines the release polish sprint for Dengbej AI as a publicly shareable AWS Builder Weekend Challenge submission. The application already functions — this sprint adds presentation quality, informational pages, and release validation to make the project submission-ready. No new AWS services are introduced, no TTS implementation is added, and the existing vanilla HTML/CSS/JS architecture is preserved.

## Glossary

- **Frontend**: The set of static HTML/CSS/JS pages served by AWS Amplify that comprise the Dengbej AI user interface
- **Homepage**: The main entry page (index.html) that displays the daily briefing and project introduction
- **Radio_UI**: The "Çi bêjim?" program selection section on the Homepage that allows users to choose radio programs
- **Story_Card**: An individual article card rendered in the stories list showing headline, summary, image, source, and metadata
- **About_Page**: A dedicated informational page at the /about route explaining the project purpose, cultural context, AWS services, and roadmap
- **Architecture_Page**: A dedicated informational page at the /how-it-works route displaying the AWS pipeline architecture diagram
- **Footer**: The persistent page footer across all pages containing navigation links and AWS service attributions
- **Builder_Article_Link**: The permanent URL https://builder.aws.com/content/3AtwFZmEnbM4cs3I7y25DHJyJlo/aideas-dengbej-ai-kurdish-storytelling-with-generative-ai
- **Audio_Placeholder**: A textual message replacing the disabled Bêje! button indicating audio functionality is forthcoming
- **Release_Validation**: The set of checks confirming the application is ready for public sharing (tests pass, APIs respond, builds succeed, mobile renders correctly, programs load)

## Requirements

### Requirement 1: Homepage Cultural Context

**User Story:** As a visitor, I want to understand what Dengbej AI is and what a dengbêj is, so that I can appreciate the cultural significance of the project.

#### Acceptance Criteria

1. THE Homepage SHALL display a project description section explaining what Dengbej AI does
2. THE Homepage SHALL display a "What is a Dengbêj?" section providing cultural context about the Kurdish oral storytelling tradition
3. WHEN the Homepage loads, THE Homepage SHALL render the project description above the daily briefing stories
4. THE Homepage SHALL display the Builder_Article_Link as a permanent navigational element visible without scrolling to the stories section

### Requirement 2: Builder Article Link

**User Story:** As a reviewer or visitor, I want a permanent link to the AWS Builder article, so that I can read the full project write-up.

#### Acceptance Criteria

1. THE Homepage SHALL display a link to the Builder_Article_Link with descriptive anchor text identifying it as the AWS Builder article
2. WHEN a user activates the Builder_Article_Link, THE Frontend SHALL open the URL in a new browser tab
3. THE Footer SHALL include the Builder_Article_Link on every page of the application

### Requirement 3: Radio UI Polish

**User Story:** As a user, I want the radio program selection area to have clear visual states and responsive layout, so that I can interact with it comfortably on any device.

#### Acceptance Criteria

1. THE Radio_UI SHALL display program choices as visually distinct cards with clear selected, unselected, and disabled states
2. WHEN no program data is available for a selected program, THE Radio_UI SHALL display an empty state message in both Kurdish and English
3. WHILE the Radio_UI is rendered on a viewport narrower than 600 pixels, THE Radio_UI SHALL stack program cards vertically with full-width layout
4. THE Radio_UI SHALL use a typographic hierarchy distinguishing program titles from subtitles and status text
5. WHILE a program is loading data, THE Radio_UI SHALL display a loading indicator within the program area

### Requirement 4: Audio Placeholder

**User Story:** As a user, I want a clear indication that audio is coming soon rather than a disabled button, so that I understand the feature status without confusion.

#### Acceptance Criteria

1. THE Radio_UI SHALL NOT display a disabled Bêje! button when audio is unavailable
2. WHEN audio is not available for the selected program, THE Radio_UI SHALL display an "Audio coming soon" textual message in place of the play button
3. THE Audio_Placeholder message SHALL be displayed in both English and Kurdish based on the active language selection

### Requirement 5: Story Card Enhancements

**User Story:** As a reader, I want story cards to show images, Kurdish headlines, and source attribution, so that the briefing feels complete and professional.

#### Acceptance Criteria

1. WHEN a story has a source_image_url field populated, THE Story_Card SHALL display the image as a visual element within the card
2. WHEN a story has a headline_ku field populated and Kurdish language is active, THE Story_Card SHALL display the Kurdish headline instead of the English headline
3. THE Story_Card SHALL display source attribution identifying the primary source name
4. WHEN a story has an original article URL, THE Story_Card SHALL display a link to the original article that opens in a new tab
5. IF a source_image_url fails to load, THEN THE Story_Card SHALL hide the image element gracefully without layout disruption

### Requirement 6: About Page

**User Story:** As a visitor, I want a dedicated About page explaining the project context, so that I can learn about the dengbêj tradition, the motivation, and the technology.

#### Acceptance Criteria

1. THE Frontend SHALL provide an About_Page accessible at the /about URL path
2. THE About_Page SHALL contain a section explaining what a dengbêj is and the Kurdish oral storytelling tradition
3. THE About_Page SHALL contain a section explaining the motivation for building this project
4. THE About_Page SHALL contain a section listing the AWS services used (Lambda, Bedrock, Polly, S3, DynamoDB, Amplify)
5. THE About_Page SHALL contain a roadmap section outlining planned future features
6. THE About_Page SHALL use the same visual design language as the Homepage (typography, colors, layout)
7. THE About_Page SHALL include navigation back to the Homepage

### Requirement 7: Architecture Page

**User Story:** As a technically curious visitor, I want to see how the AWS pipeline works, so that I can understand the system design.

#### Acceptance Criteria

1. THE Frontend SHALL provide an Architecture_Page accessible at the /how-it-works URL path
2. THE Architecture_Page SHALL display a visual architecture diagram showing the AWS service pipeline
3. THE Architecture_Page SHALL label each AWS service in the diagram with its role in the pipeline
4. THE Architecture_Page SHALL describe the data flow from news ingestion through processing to frontend delivery
5. THE Architecture_Page SHALL use the same visual design language as the Homepage
6. THE Architecture_Page SHALL include navigation back to the Homepage

### Requirement 8: Footer Enhancement

**User Story:** As a visitor, I want a comprehensive footer with navigation and attribution, so that I can access project links and understand the technology stack.

#### Acceptance Criteria

1. THE Footer SHALL display a list or badges of AWS services used in the project
2. THE Footer SHALL include a link to the project GitHub repository
3. THE Footer SHALL include the Builder_Article_Link
4. THE Footer SHALL include a link to the About_Page
5. THE Footer SHALL include a link to the Architecture_Page
6. THE Footer SHALL be rendered consistently on every page of the application (Homepage, About_Page, Architecture_Page, story.html)

### Requirement 9: Release Validation

**User Story:** As the project owner, I want validation that the release candidate is stable and complete, so that I can share it publicly with confidence.

#### Acceptance Criteria

1. THE Frontend SHALL render without JavaScript errors in the browser console on all pages
2. WHEN the /news/today API endpoint is called, THE Backend SHALL return a valid JSON response with HTTP status 200
3. WHEN the /news/program/{id} API endpoint is called with a valid program identifier, THE Backend SHALL return a valid JSON response
4. THE Frontend SHALL render correctly on viewports of 375 pixels width (mobile) without horizontal overflow
5. WHEN each program in the program list is selected, THE Radio_UI SHALL load and display the program data or empty state without errors
6. THE Frontend SHALL build and deploy successfully through AWS Amplify without build errors
7. THE Frontend SHALL serve all pages using relative asset paths compatible with Amplify static hosting
