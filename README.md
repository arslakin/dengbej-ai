# Dengbej AI

Dengbej AI is an experimental storytelling platform inspired by the Kurdish dengbêj oral tradition. The project explores how AI can transform written articles into short narrated audio stories, making content more accessible and engaging through the power of voice.

## About Dengbêj

Dengbêj is a traditional Kurdish oral storytelling art form where storytellers (dengbêjs) narrate historical events, legends, and cultural tales. This project honors that tradition by using modern AI to help preserve and extend the art of oral storytelling.

## What It Does

Dengbej AI takes any text input and:
1. Summarizes it into a compelling short story using AI
2. Translates the summary into Kurdish (Kurmanji dialect)
3. Converts the English summary into natural-sounding speech
4. Delivers both text versions and audio you can listen to immediately

Perfect for turning long articles, blog posts, or documents into bilingual audio summaries.

## Features

- **AI-Powered Summarization** – Intelligent text condensation using Amazon Bedrock (Claude 3.5 Haiku)
- **Bilingual Output** – Get both English and Kurdish (Kurmanji) text versions
- **Natural Voice Narration** – High-quality English text-to-speech with Amazon Polly
- **Instant Audio Generation** – Get your story in seconds
- **Serverless Architecture** – Scalable, cost-effective AWS infrastructure
- **Simple Web Interface** – No installation required, just paste and listen

## Architecture

```
┌─────────────────┐
│  Web Frontend   │
│   (HTML/JS)     │
└────────┬────────┘
         │ HTTPS POST
         ↓
┌─────────────────┐
│  AWS Lambda     │
│  Function URL   │
└────────┬────────┘
         │
         ├──→ Amazon Bedrock (Claude 3.5 Haiku)
         │    • Text summarization
         │    • Kurdish translation
         │
         ├──→ Amazon Polly
         │    • English text-to-speech
         │    • Audio generation
         │
         └──→ Amazon S3
              • Audio file storage
              • Public URL generation
```

## Tech Stack

### Frontend
- HTML5
- Vanilla JavaScript
- CSS3

### Backend (AWS)
- **AWS Lambda** – Serverless compute
- **Amazon Bedrock** – AI/ML models (Claude 3.5 Haiku)
- **Amazon Polly** – Neural text-to-speech
- **Amazon S3** – Object storage
- **Lambda Function URLs** – Public HTTP endpoint

### Language
- Python 3.x (Lambda runtime)

## Getting Started

### Prerequisites
- AWS Account with access to:
  - Amazon Bedrock (Claude 3.5 Haiku model enabled)
  - AWS Lambda
  - Amazon Polly
  - Amazon S3
- Basic knowledge of AWS services

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/dengbej-ai.git
   cd dengbej-ai
   ```

2. **Deploy the Lambda function**
   - Create a new Lambda function in AWS Console
   - Upload the backend code (Python)
   - Configure IAM role with permissions for Bedrock, Polly, and S3
   - Enable Lambda Function URL with CORS

3. **Create S3 bucket**
   - Create a bucket for audio storage
   - Enable public read access for generated audio files
   - Configure CORS settings

4. **Update frontend configuration**
   - Open `frontend/index.html`
   - Replace the `lambdaURL` with your Lambda Function URL

5. **Open the frontend**
   - Open `frontend/index.html` in a web browser
   - Or deploy to any static hosting service

## Usage

1. Open the Dengbej AI web interface
2. Paste any text into the text area (article, blog post, story, etc.)
3. Click "Generate Dengbej Story"
4. Wait a few seconds for AI processing
5. Read both the English summary and Kurdish translation
6. Listen to the English audio narration

## Project Structure

```
dengbej-ai/
├── frontend/           # Web interface
│   └── index.html     # Single-page application
├── backend/           # AWS Lambda function code
├── infrastructure/    # Infrastructure as Code (future)
├── docs/             # Documentation and progress logs
│   └── progress.md   # Development timeline
├── mp3/              # Sample audio files
└── README.md         # This file
```

## Roadmap

- [ ] Add multilingual translation support
- [ ] Implement voice selection options
- [ ] Add story length customization
- [ ] Create Infrastructure as Code (Terraform/CloudFormation)
- [ ] Add user authentication
- [ ] Implement story history and favorites
- [ ] Support multiple AI models
- [ ] Add batch processing capabilities

## Development

This project is being developed for the **AWS 10,000 AIdeas Competition** and explores how modern AI tools can support storytelling and accessible media.

See [docs/progress.md](docs/progress.md) for detailed development timeline.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

See [LICENSE](LICENSE) file for details.

## Acknowledgments

- Inspired by the Kurdish dengbêj oral storytelling tradition
- Built with AWS AI/ML services
- Developed for AWS 10,000 AIdeas Competition

## Contact

For questions or feedback about this project, please open an issue on GitHub.
