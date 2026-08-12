# Requirements Document

## Introduction

News Presentation V2 enhances how Dengbej AI presents program stories in the frontend. The feature adds Kurdish headlines generated at zero additional Bedrock cost, dynamic story counts for topic programs, source images extracted from RSS feeds, and a bilingual frontend presentation with story cards. The system preserves backward compatibility with existing DynamoDB records and maintains the Today's 5 program at exactly 5 stories.

## Glossary

- **Ingester**: The News Ingestion Lambda that fetches RSS/Atom feeds and stores article metadata in the dengbej-articles DynamoDB table
- **Processor**: The Today's 5 Processor Lambda that generates English summaries and Kurdish translations for Today's 5 stories via Bedrock
- **Program_Generator**: The Program Generator Lambda that classifies articles, clusters related stories, ranks by editorial significance, and stores program briefings in the dengbej-programs DynamoDB table
- **News_API**: The read-only public API Lambda that serves processed briefings and program data to the frontend
- **Frontend**: The vanilla HTML/CSS/JS single-page application that renders news stories and programs to users
- **headline_ku**: A Kurdish Kurmanji translation of the original English headline, generated during existing Bedrock processing
- **source_image_url**: An image URL extracted from RSS feed media fields (media:content, media:thumbnail, or enclosure) and hotlinked with attribution
- **topic_program**: Any of the 8 non-today programs (kurdistan, world, middle-east, turkey, bakur, rojava, basur, rojhilat) that display a quality-based variable number of stories
- **Today's_5**: The curated daily briefing program that always contains exactly 5 stories
- **Kurdish_mode**: The UI language state where the Frontend displays headline_ku and Kurdish summaries
- **English_mode**: The UI language state where the Frontend displays original English headlines and English summaries
- **story_card**: A frontend UI component that displays a single story with image, headline, summary, source attribution, and metadata

## Requirements

### Requirement 1: Source Image Extraction During Ingestion

**User Story:** As a user, I want to see images alongside news stories, so that the news presentation is visually engaging and easier to scan.

#### Acceptance Criteria

1. WHEN an RSS feed entry contains one or more media:content elements with a url attribute and medium="image" (or no medium attribute), THE Ingester SHALL extract the URL from the first such element and store it in the article record as the source_image_url field
2. WHEN an RSS feed entry contains a media:content element whose medium attribute is not "image" (e.g., "video") and no media:content element with medium="image" exists, THE Ingester SHALL fall through to the next priority source (media:thumbnail, then enclosure)
3. WHEN an RSS feed entry contains a media:thumbnail element with a url attribute but no qualifying media:content element, THE Ingester SHALL extract the media:thumbnail URL and store it as the source_image_url field
4. WHEN an RSS feed entry contains an enclosure element with type starting with "image/" but no qualifying media:content or media:thumbnail element, THE Ingester SHALL extract the enclosure URL and store it as the source_image_url field
5. WHEN an RSS feed entry contains none of a qualifying media:content, media:thumbnail, or image enclosure elements, THE Ingester SHALL store null as the source_image_url field
6. IF the extracted URL is not a valid absolute URL starting with http:// or https://, THEN THE Ingester SHALL discard it and treat the entry as having no image source for that priority level, falling through to the next source in priority order
7. THE Ingester SHALL NOT fetch, scrape, or download the image content from extracted URLs
8. THE Ingester SHALL NOT rehost images to S3 or any other storage service
9. THE Ingester SHALL store source_image_url values with a maximum length of 2048 characters, discarding and storing null for any URL exceeding this limit

### Requirement 2: Kurdish Headline Generation at Zero Additional Cost

**User Story:** As a Kurdish-speaking user, I want headlines displayed in Kurdish when I select Kurdî mode, so that the entire reading experience is in my language.

#### Acceptance Criteria

1. WHEN the Processor generates the Kurdish summary for a Today's 5 story, THE Processor SHALL include a Kurdish Kurmanji translation of the story's original English headline in the same Bedrock call that produces the Kurdish summary, storing the result as headline_ku (maximum 200 characters, truncated if exceeded) on the story record
2. WHEN the Program_Generator generates a Kurmanji script for a topic_program, THE Program_Generator SHALL include a Kurdish Kurmanji translation of each story's original English headline in the same Bedrock call that produces the script, storing each result as headline_ku (maximum 200 characters, truncated if exceeded) on the corresponding story record
3. THE Processor SHALL NOT make additional Bedrock API calls solely for headline_ku generation
4. THE Program_Generator SHALL NOT make additional Bedrock API calls solely for headline_ku generation
5. WHEN headline_ku generation fails or produces empty output (null, empty string, or whitespace-only) within the combined prompt, THE Processor SHALL still store the successfully generated summary_en and summary_ku fields with headline_ku set to null
6. WHEN headline_ku generation fails or produces empty output (null, empty string, or whitespace-only) within the combined prompt, THE Program_Generator SHALL still store the successfully generated script and summary fields for the topic_program with headline_ku set to null on the affected story records

### Requirement 3: Dynamic Story Counts for Topic Programs

**User Story:** As a listener, I want each topic program to contain only high-relevance stories rather than being padded to a fixed number, so that I receive quality-focused briefings.

#### Acceptance Criteria

1. THE Program_Generator SHALL select between 0 and 10 stories (inclusive) for each topic_program, choosing only candidates that the ranking step scores above the editorial significance threshold, and selecting the top-ranked candidates when more than 10 exceed the threshold
2. WHEN zero candidates score above the editorial significance threshold for a topic_program, THE Program_Generator SHALL produce an empty program with story_count of 0
3. THE Program_Generator SHALL NOT include stories that score below the editorial significance threshold in a topic_program to reach a minimum count
4. THE Today's_5 program SHALL always contain exactly 5 stories regardless of the dynamic count logic applied to topic programs
5. WHEN the Program_Generator stores a program briefing, THE Program_Generator SHALL record the actual story_count as an integer equal to the number of selected stories in that program
6. IF the Program_Generator encounters fewer available candidate articles than the number that scored above the editorial significance threshold (due to duplicates or filtering), THEN THE Program_Generator SHALL include only the remaining valid candidates and set story_count accordingly

### Requirement 4: News API Response Enhancement

**User Story:** As a frontend developer, I want the API to return source_image_url and headline_ku fields, so that the frontend can render story cards with images and bilingual headlines.

#### Acceptance Criteria

1. WHEN the News_API formats a Today's 5 briefing response, THE News_API SHALL include the headline_ku field in every story object as either a non-empty string value or null
2. WHEN the News_API formats a Today's 5 briefing response, THE News_API SHALL include the source_image_url field in every story object as either a valid URL string or null
3. WHEN the News_API formats a topic_program response, THE News_API SHALL include the headline_ku field in every story object as either a non-empty string value or null
4. WHEN the News_API formats a topic_program response, THE News_API SHALL include the source_image_url field in every story object as either a valid URL string or null
5. IF an existing DynamoDB record lacks the headline_ku attribute, THEN THE News_API SHALL return the story with headline_ku set to null and respond with HTTP 200 for the overall request
6. IF an existing DynamoDB record lacks the source_image_url attribute, THEN THE News_API SHALL return the story with source_image_url set to null and respond with HTTP 200 for the overall request
7. THE News_API SHALL never omit the headline_ku or source_image_url fields from a story object in the response, even when the underlying data has no value for these fields

### Requirement 5: Frontend Story Card Presentation

**User Story:** As a user, I want stories displayed as visually rich cards with images and clear typography, so that the news is easy to browse and understand.

#### Acceptance Criteria

1. WHEN a story has a non-null source_image_url, THE Frontend SHALL render a story_card with the image displayed via an img element whose src attribute hotlinks to the original source URL, with an alt attribute set to the story headline text
2. WHEN a story has a null source_image_url, THE Frontend SHALL render a story_card without an image element, occupying the same card width and preserving identical spacing, typography, and element ordering as cards with images
3. WHEN a story_card displays an image, THE Frontend SHALL render visible source attribution text directly below the image element indicating the source name from the story's primary_source field
4. THE Frontend SHALL render story_cards in a responsive layout that adapts to mobile (below 600px), tablet (600-899px), and desktop (900px and above) viewport widths
5. IF an image fails to load due to an HTTP error or does not complete loading within 5 seconds, THEN THE Frontend SHALL hide the img element and its source attribution text, and display the story_card in the same layout as cards with a null source_image_url
6. WHEN a story_card image is rendered, THE Frontend SHALL display the image at full card-content width with a maximum height of 400px, preserving the original aspect ratio via object-fit containment

### Requirement 6: Bilingual Headline and Summary Switching

**User Story:** As a bilingual user, I want to toggle between Kurdish and English presentation of headlines and summaries, so that I can read the news in my preferred language at any time.

#### Acceptance Criteria

1. WHILE the Frontend is in Kurdish_mode and a story has a non-null headline_ku, THE Frontend SHALL display headline_ku as the story headline
2. WHILE the Frontend is in Kurdish_mode and a story has a null headline_ku, THE Frontend SHALL fall back to displaying the original English headline
3. WHILE the Frontend is in Kurdish_mode and a story has a non-null summary_ku, THE Frontend SHALL display summary_ku as the story summary
4. WHILE the Frontend is in English_mode, THE Frontend SHALL display the original English headline regardless of headline_ku availability
5. WHILE the Frontend is in English_mode, THE Frontend SHALL display summary_en as the story summary
6. WHEN the user activates the language toggle, THE Frontend SHALL re-render all visible story_cards with the appropriate headline and summary for the selected language within 100 milliseconds and without a full page reload
7. IF the Frontend is in Kurdish_mode and a story has a null summary_ku, THEN THE Frontend SHALL fall back to displaying summary_en as the story summary
8. WHEN no prior language selection exists in the current browser session, THE Frontend SHALL default to English_mode and persist the user's subsequent language selection for the duration of the session
9. WHEN the user toggles the language, THE Frontend SHALL update the document lang attribute to reflect the selected language so that assistive technologies can identify the content language

### Requirement 7: Backward Compatibility with Existing Records

**User Story:** As a system operator, I want the new features to work alongside existing data, so that no migration is needed and historical briefings remain accessible.

#### Acceptance Criteria

1. WHEN the Ingester processes an RSS feed entry for an article that already exists in DynamoDB without a source_image_url field, THE Ingester SHALL treat the missing field as null and SHALL NOT overwrite other existing fields on that record
2. WHEN the News_API reads a DynamoDB story record that lacks the headline_ku attribute, THE News_API SHALL include headline_ku with an explicit null value in the JSON response without raising an error
3. WHEN the News_API reads a DynamoDB story record that lacks the source_image_url attribute, THE News_API SHALL include source_image_url with an explicit null value in the JSON response without raising an error
4. IF a story record has neither headline_ku nor source_image_url, THEN THE Frontend SHALL render the story_card without an image element and with the English headline as fallback, using the same card dimensions and spacing as a story_card that has those fields set to null
5. THE News_API SHALL NOT require a data migration or schema change to DynamoDB tables for the new fields to function
6. WHEN the News_API formats a response containing a mix of pre-existing records (without new fields) and new records (with headline_ku and source_image_url populated), THE News_API SHALL return all records in the same response structure with null values substituted for any missing attributes

### Requirement 8: Image Hotlinking and Attribution

**User Story:** As a content-responsible platform, I want images displayed via direct hotlinks with proper attribution, so that the system respects source ownership and avoids storage costs.

#### Acceptance Criteria

1. THE Frontend SHALL load images directly from the source_image_url (hotlink) without proxying through Dengbej infrastructure
2. THE Frontend SHALL NOT download, cache, or rehost source images on Dengbej-controlled storage
3. WHEN displaying a source image, THE Frontend SHALL show the source_name of the originating feed as visible attribution text positioned adjacent to or overlaid on the image
4. IF a source image fails to load, THEN THE Frontend SHALL hide both the broken image element and its associated attribution text
5. THE Frontend SHALL set the img element alt attribute to the story headline text (truncated to 125 characters if the headline exceeds that length) and set loading="lazy"

### Requirement 9: Test Coverage for New Behavior

**User Story:** As a developer, I want comprehensive tests for all new functionality, so that regressions are caught early and behavior is documented.

#### Acceptance Criteria

1. THE test suite SHALL include tests verifying source_image_url extraction from media:content, media:thumbnail, and enclosure RSS elements, including a test confirming the priority order (media:content preferred over media:thumbnail, media:thumbnail preferred over enclosure) and a test confirming null is stored when none of these elements are present
2. THE test suite SHALL include tests verifying headline_ku is produced within existing Bedrock calls by asserting that the total number of Bedrock invoke_model calls made by the Processor (for a Today's 5 story) and by the Program_Generator (for a topic_program script) does not increase compared to processing without headline_ku generation
3. THE test suite SHALL include tests verifying dynamic story counts for topic programs covering the boundary cases of 0 stories (no high-relevance candidates), 1 story (minimum non-empty), 10 stories (maximum), and a separate test asserting that the Today's_5 curator always produces exactly 5 stories regardless of candidate pool size
4. THE test suite SHALL include tests verifying the News_API returns headline_ku and source_image_url fields in both Today's 5 and topic_program response payloads, with at least one test where both fields contain non-null values and one test where both fields are null due to missing data in the underlying DynamoDB record
5. THE test suite SHALL include tests verifying Frontend story_card DOM output in all four combinations: Kurdish_mode with non-null source_image_url (asserts img element present and headline_ku text displayed), Kurdish_mode with null source_image_url (asserts no img element and headline_ku text displayed), English_mode with non-null source_image_url (asserts img element present and English headline displayed), and English_mode with null source_image_url (asserts no img element and English headline displayed)
6. THE test suite SHALL include tests verifying backward compatibility by confirming that the News_API returns records lacking headline_ku and source_image_url fields with those fields set to null without HTTP error, and that the Frontend renders story_cards for such records using the same layout as records with those fields explicitly set to null
