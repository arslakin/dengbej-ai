# Dengbej AI Architecture

Dengbej AI is an experimental storytelling platform inspired by the Kurdish **dengbêj** oral storytelling tradition. The system explores how artificial intelligence can transform written articles into short narrated audio stories.

This project is being developed as part of the **AWS 10,000 AIdeas Competition** and demonstrates how serverless cloud services and AI models can be combined to create accessible storytelling experiences.

The application allows users to paste written text or provide the URL of an online article. The system retrieves the content, summarizes it using artificial intelligence, translates the summary into Kurdish, and generates an audio narration that can be played directly in the browser.

⚠️ Note: The architecture described here represents the current design and may evolve as new features are added during development.

---

## System Architecture

Dengbej AI uses a **serverless architecture on AWS**.

The platform consists of:

User Input (Frontend)  
↓  
AWS Lambda (Backend Processing)  
↓  
Amazon Bedrock (AI Summarization and Translation)  
↓  
Amazon Polly (Text-to-Speech Narration)  
↓  
Amazon S3 (Audio File Storage)  
↓  
Audio URL returned to the browser

This pipeline allows the system to convert written content into narrated audio stories with minimal infrastructure management.

---

## Core AWS Services

The prototype currently uses the following AWS services:

**Amazon Bedrock**  
Used for AI-powered text generation, including article summarization and Kurdish translation.

**AWS Lambda**  
Acts as the backend processing layer. Lambda orchestrates the AI pipeline by receiving requests from the frontend, processing the input text or article URL, and coordinating calls to Bedrock and Polly.

**Amazon Polly**  
Converts generated text into speech to produce the narrated storytelling experience.

**Amazon S3**  
Stores generated audio files and returns a public or signed URL so the frontend can play the narration.

---

## Application Workflow

The Dengbej AI workflow follows these steps:

1. A user pastes text or submits an article URL through the web interface.
2. The frontend sends a request to an AWS Lambda Function URL.
3. Lambda processes the input and retrieves article content if a URL is provided.
4. Amazon Bedrock generates a summarized version of the content.
5. The summary can optionally be translated into Kurdish.
6. Amazon Polly converts the generated text into speech.
7. The audio file is stored in Amazon S3.
8. Lambda returns the summary and audio URL to the frontend.
9. The browser loads the audio player and plays the narrated story.

---

## Project Structure

```
dengbej-ai
├── backend
├── docs
│   ├── architecture.md
│   └── progress.md
├── frontend
│   └── index.html
├── infrastructure
├── mp3
└── README.md
```

**frontend/**  
Contains the HTML and JavaScript interface where users paste text or submit article URLs.

**backend/**  
Contains the AWS Lambda logic responsible for processing requests and coordinating the AI pipeline.

**docs/**  
Contains project documentation including architecture notes and development progress.

**infrastructure/**  
Reserved for infrastructure-as-code configuration.

**mp3/**  
Contains sample Dengbej storytelling audio files used for testing.

---

## Design Goals

The architecture of Dengbej AI focuses on several key goals:

- Accessibility – transform written content into audio storytelling experiences  
- Cultural preservation – explore AI-assisted storytelling inspired by the Kurdish dengbêj tradition  
- Serverless simplicity – use AWS managed services to minimize operational overhead  
- Extensibility – allow new features such as article URL ingestion and multilingual narration  

---

## Future Improvements

Planned improvements to the architecture include:

- Article content extraction from URLs  
- Kurdish-first storytelling mode  
- Additional narration voices  
- Improved frontend user interface  
- Infrastructure-as-code deployment  

---

## Summary

Dengbej AI demonstrates how modern AI models and serverless cloud architecture can be combined to support cultural storytelling and accessible media. By connecting summarization, translation, and speech synthesis services, the platform transforms written content into narrated stories that can be experienced directly in a web browser.