"""
KurdishTTS Provider — Kurmanji TTS via kurdishtts.com API.

Synthesizes Kurmanji Kurdish text to MP3 audio using the KurdishTTS.com API.
Handles chunking for texts exceeding the API character limit, retrieves the
API key from AWS Secrets Manager, and provides graceful fallback on failure.

API docs: https://www.kurdishtts.com/docs/api
Endpoint: POST https://www.kurdishtts.com/api/tts-proxy
Auth: x-api-key header
"""

import json
import os
import re
import time
from typing import Optional

import boto3
import requests
from botocore.exceptions import ClientError

from tts_provider import TTSProvider, TTSResult, TTSError


# ─── Configuration ───────────────────────────────────────────────────────────

KURDISH_TTS_ENDPOINT = "https://www.kurdishtts.com/api/tts-proxy"
KURDISH_TTS_SECRET_NAME = os.environ.get(
    "KURDISH_TTS_SECRET_NAME", "dengbej-ai/kurdish-tts-api-key"
)
KURDISH_TTS_SPEAKER = os.environ.get("KURDISH_TTS_SPEAKER", "kurmanji_236")
KURDISH_TTS_MODEL = os.environ.get("KURDISH_TTS_MODEL", "v4")
KURDISH_TTS_CHUNK_LIMIT = int(os.environ.get("KURDISH_TTS_CHUNK_LIMIT", "4800"))
KURDISH_TTS_TIMEOUT = int(os.environ.get("KURDISH_TTS_TIMEOUT", "30"))
KURDISH_TTS_MAX_RETRIES = int(os.environ.get("KURDISH_TTS_MAX_RETRIES", "2"))

# Minimum valid MP3 frame size (an MP3 frame header is 4 bytes minimum)
MIN_MP3_SIZE = 256


# ─── Secret Retrieval ────────────────────────────────────────────────────────

_cached_api_key: Optional[str] = None


def get_api_key() -> str:
    """
    Retrieve the KurdishTTS API key from AWS Secrets Manager.
    Caches the key for the Lambda execution lifetime (warm starts).
    """
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key

    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=KURDISH_TTS_SECRET_NAME)
        secret = response.get("SecretString", "")

        # Support both plain string and JSON {"api_key": "..."} formats
        try:
            parsed = json.loads(secret)
            key = parsed.get("api_key") or parsed.get("key") or parsed.get("tts_key")
            if key:
                _cached_api_key = key.strip()
                return _cached_api_key
        except (json.JSONDecodeError, AttributeError):
            pass

        # Plain string secret
        if secret.strip():
            _cached_api_key = secret.strip()
            return _cached_api_key

        raise TTSError("Secret exists but contains no usable API key")

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "ResourceNotFoundException":
            raise TTSError(f"Secret '{KURDISH_TTS_SECRET_NAME}' not found in Secrets Manager")
        elif error_code == "AccessDeniedException":
            raise TTSError(f"Lambda lacks permission to read secret '{KURDISH_TTS_SECRET_NAME}'")
        else:
            raise TTSError(f"Secrets Manager error: {error_code}")


# ─── Text Chunking ───────────────────────────────────────────────────────────

def chunk_text(text: str, max_chars: int = KURDISH_TTS_CHUNK_LIMIT) -> list:
    """
    Split text into chunks at sentence boundaries, respecting the API char limit.

    Strategy:
    1. Split on sentence-ending punctuation followed by whitespace
    2. If a single sentence exceeds the limit, split on clause boundaries (commas)
    3. If still too long, hard-split at the limit (rare edge case)
    """
    if len(text) <= max_chars:
        return [text]

    # Split on sentence boundaries: period/question/exclamation followed by space or newline
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # If adding this sentence would exceed the limit
        if len(current_chunk) + len(sentence) + 1 > max_chars:
            # Save current chunk if it has content
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""

            # If the single sentence itself exceeds the limit, sub-split
            if len(sentence) > max_chars:
                sub_parts = _split_long_sentence(sentence, max_chars)
                # Add all sub-parts except the last as complete chunks
                for part in sub_parts[:-1]:
                    chunks.append(part.strip())
                current_chunk = sub_parts[-1]
            else:
                current_chunk = sentence
        else:
            if current_chunk:
                current_chunk += " " + sentence
            else:
                current_chunk = sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _split_long_sentence(text: str, max_chars: int) -> list:
    """Split a long sentence on commas or hard-break if necessary."""
    # Try splitting on commas
    parts = text.split(", ")
    if len(parts) > 1:
        result = []
        current = ""
        for part in parts:
            candidate = current + ", " + part if current else part
            if len(candidate) > max_chars and current:
                result.append(current.strip())
                current = part
            else:
                current = candidate
        if current:
            result.append(current.strip())
        return result

    # Hard split as last resort
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


# ─── API Call ────────────────────────────────────────────────────────────────

def synthesize_chunk(text: str, api_key: str, speaker_id: str = KURDISH_TTS_SPEAKER) -> bytes:
    """
    Synthesize a single text chunk via the KurdishTTS API.
    Returns raw MP3 bytes.

    Raises TTSError on failure after retries.
    """
    payload = {
        "text": text,
        "speaker_id": speaker_id,
        "model_version": KURDISH_TTS_MODEL,
        "format": "mp3",
    }

    last_error = None
    for attempt in range(1, KURDISH_TTS_MAX_RETRIES + 1):
        try:
            response = requests.post(
                KURDISH_TTS_ENDPOINT,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=KURDISH_TTS_TIMEOUT,
            )

            # Handle specific error codes
            if response.status_code == 401:
                raise TTSError("KurdishTTS authentication failed (invalid API key)")
            elif response.status_code == 403:
                raise TTSError("KurdishTTS quota exhausted or plan inactive")
            elif response.status_code == 422:
                raise TTSError(f"KurdishTTS validation error: {response.text[:200]}")
            elif response.status_code != 200:
                last_error = f"KurdishTTS HTTP {response.status_code}: {response.text[:100]}"
                if attempt < KURDISH_TTS_MAX_RETRIES:
                    time.sleep(1 * attempt)
                    continue
                raise TTSError(last_error)

            # Validate response
            content_type = response.headers.get("Content-Type", "")
            if "audio" not in content_type and "octet-stream" not in content_type:
                # Check for JSON error response
                try:
                    error_data = response.json()
                    if error_data.get("generation", {}).get("collapsed"):
                        raise TTSError("KurdishTTS returned collapsed generation (empty output)")
                    raise TTSError(f"KurdishTTS unexpected response: {str(error_data)[:200]}")
                except (ValueError, AttributeError):
                    raise TTSError(f"KurdishTTS unexpected content-type: {content_type}")

            audio_data = response.content
            if len(audio_data) < MIN_MP3_SIZE:
                raise TTSError(f"KurdishTTS returned suspiciously small audio: {len(audio_data)} bytes")

            return audio_data

        except requests.Timeout:
            last_error = f"KurdishTTS timeout after {KURDISH_TTS_TIMEOUT}s (attempt {attempt})"
            if attempt < KURDISH_TTS_MAX_RETRIES:
                time.sleep(1 * attempt)
                continue

        except requests.RequestException as e:
            last_error = f"KurdishTTS request failed: {str(e)[:100]} (attempt {attempt})"
            if attempt < KURDISH_TTS_MAX_RETRIES:
                time.sleep(1 * attempt)
                continue

    raise TTSError(last_error or "KurdishTTS synthesis failed after retries")


# ─── Full Synthesis (with chunking) ─────────────────────────────────────────

def synthesize_kurdish(text: str, speaker_id: str = KURDISH_TTS_SPEAKER) -> bytes:
    """
    Synthesize full Kurdish text to MP3, handling chunking for long texts.

    MP3 is a frame-based format — concatenating valid MP3 files at the same
    sample rate produces a valid MP3 stream. The KurdishTTS API returns MP3
    at 22.05 kHz consistently, making concatenation safe.

    Returns combined MP3 bytes.
    Raises TTSError if the API key is missing or synthesis fails.
    """
    api_key = get_api_key()

    chunks = chunk_text(text)
    print(f"  KurdishTTS: synthesizing {len(text)} chars in {len(chunks)} chunk(s)")

    audio_parts = []
    total_chars = 0

    for i, chunk in enumerate(chunks):
        print(f"  KurdishTTS chunk {i + 1}/{len(chunks)}: {len(chunk)} chars")
        audio_data = synthesize_chunk(chunk, api_key, speaker_id)
        audio_parts.append(audio_data)
        total_chars += len(chunk)

    # Concatenate MP3 frames
    combined = b"".join(audio_parts)
    print(f"  KurdishTTS: total audio {len(combined)} bytes from {total_chars} chars")

    return combined


# ─── TTSProvider Implementation ──────────────────────────────────────────────

class KurdishTTSProvider(TTSProvider):
    """
    Kurdish TTS provider using kurdishtts.com API.

    Supports Kurmanji Kurdish in Latin script.
    Structured for future Sorani extension (separate script generation needed).
    """

    def __init__(self, speaker_id: str = KURDISH_TTS_SPEAKER):
        self._speaker_id = speaker_id

    def synthesize(self, text: str, language: str = "ku", voice_id: Optional[str] = None) -> TTSResult:
        """Synthesize Kurdish text to speech."""
        if language not in ("ku", "kmr", "kurmanji"):
            raise TTSError(f"KurdishTTSProvider does not support language: {language}")

        speaker = voice_id or self._speaker_id
        audio_data = synthesize_kurdish(text, speaker_id=speaker)

        return TTSResult(
            audio_data=audio_data,
            duration_seconds=0.0,  # Not provided by the API
            provider="kurdish-tts",
            voice_id=speaker,
            language="ku",
            format="mp3",
            chars_synthesized=len(text),
        )

    def supports_language(self, language: str) -> bool:
        return language in ("ku", "kmr", "kurmanji")

    @property
    def provider_name(self) -> str:
        return "kurdish-tts"
