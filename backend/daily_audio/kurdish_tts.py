"""
KurdishTTS Provider — Kurmanji TTS via kurdishtts.com API.

Synthesizes Kurmanji Kurdish text to WAV audio using the KurdishTTS.com API.
Handles chunking for texts exceeding the API character limit, retrieves the
API key from AWS Secrets Manager, and assembles multi-chunk output into a
single valid WAV file using Python's standard `wave` module.

Uses only standard-library HTTP (urllib) so no external `requests` dependency
is needed in the Lambda package.

API docs: https://www.kurdishtts.com/docs/api
Endpoint: POST https://www.kurdishtts.com/api/tts-proxy
Auth: x-api-key header
Output: WAV (PCM 16-bit, mono, 22050 Hz)
"""

import io
import json
import os
import re
import time
import wave
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import boto3
from botocore.exceptions import ClientError

from tts_provider import TTSProvider, TTSResult, TTSError


# ─── Configuration ───────────────────────────────────────────────────────────

KURDISH_TTS_ENDPOINT = "https://www.kurdishtts.com/api/tts-proxy"
KURDISH_TTS_SECRET_NAME = os.environ.get(
    "KURDISH_TTS_SECRET_NAME", "dengbej-ai/kurdish-tts-api-key"
)
KURDISH_TTS_SPEAKER = os.environ.get("KURDISH_TTS_SPEAKER", "kurmanji_236")
KURDISH_TTS_MODEL = os.environ.get("KURDISH_TTS_MODEL", "v4")
# Free-tier limit is 500 chars; default to 480 for safety margin.
KURDISH_TTS_MAX_CHARS = int(os.environ.get("KURDISH_TTS_MAX_CHARS", "480"))
KURDISH_TTS_TIMEOUT = int(os.environ.get("KURDISH_TTS_TIMEOUT", "30"))
KURDISH_TTS_MAX_RETRIES = int(os.environ.get("KURDISH_TTS_MAX_RETRIES", "2"))

# Speed: 0.25–4.0 per API docs; higher = faster. Default 1.1 for natural news pace.
_SPEED_MIN = 0.25
_SPEED_MAX = 4.0
_SPEED_DEFAULT = 1.1


def _parse_speed(raw: str) -> float:
    """Parse and validate speed, falling back to default on invalid input."""
    try:
        val = float(raw)
        if _SPEED_MIN <= val <= _SPEED_MAX:
            return val
    except (ValueError, TypeError):
        pass
    return _SPEED_DEFAULT


KURDISH_TTS_SPEED = _parse_speed(os.environ.get("KURDISH_TTS_SPEED", "1.1"))

# Expected WAV parameters from the API (22050 Hz, mono, 16-bit)
EXPECTED_SAMPLE_RATE = 22050
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

# Minimum valid WAV size (44-byte header + at least some PCM data)
MIN_WAV_SIZE = 100


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

def chunk_text(text: str, max_chars: int = None) -> list:
    """
    Split text into chunks at sentence boundaries, respecting the API char limit.

    Strategy:
    1. Split on sentence-ending punctuation followed by whitespace
    2. If a single sentence exceeds the limit, split on clause boundaries (commas)
    3. If still too long, hard-split at the limit
    """
    if max_chars is None:
        max_chars = KURDISH_TTS_MAX_CHARS

    if len(text) <= max_chars:
        return [text]

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 > max_chars:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""

            if len(sentence) > max_chars:
                sub_parts = _split_long_sentence(sentence, max_chars)
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

    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]


# ─── API Call (stdlib urllib) ────────────────────────────────────────────────

def synthesize_chunk(text: str, api_key: str, speaker_id: str = None) -> bytes:
    """
    Synthesize a single text chunk via the KurdishTTS API.
    Returns raw WAV bytes.

    Raises TTSError on failure after retries.
    """
    if speaker_id is None:
        speaker_id = KURDISH_TTS_SPEAKER

    payload = json.dumps({
        "text": text,
        "speaker_id": speaker_id,
        "model_version": KURDISH_TTS_MODEL,
        "format": "wav",
        "speed": KURDISH_TTS_SPEED,
    }).encode("utf-8")

    last_error = None
    for attempt in range(1, KURDISH_TTS_MAX_RETRIES + 1):
        try:
            req = Request(
                KURDISH_TTS_ENDPOINT,
                data=payload,
                headers={
                    "x-api-key": api_key,
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urlopen(req, timeout=KURDISH_TTS_TIMEOUT) as resp:
                status = resp.status
                content_type = resp.headers.get("Content-Type", "")
                data = resp.read()

            if len(data) < MIN_WAV_SIZE:
                raise TTSError(f"KurdishTTS returned suspiciously small audio: {len(data)} bytes")

            # Check for collapsed generation in JSON response
            if "application/json" in content_type:
                try:
                    json_body = json.loads(data)
                    if json_body.get("generation", {}).get("collapsed"):
                        raise TTSError("KurdishTTS returned collapsed generation (empty output)")
                    raise TTSError(f"KurdishTTS unexpected JSON response: {str(json_body)[:200]}")
                except (ValueError, AttributeError):
                    raise TTSError(f"KurdishTTS unexpected content-type: {content_type}")

            # Validate WAV header
            _validate_wav(data)

            return data

        except HTTPError as e:
            status = e.code
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass

            if status == 401:
                raise TTSError("KurdishTTS authentication failed (invalid API key)")
            elif status == 403:
                raise TTSError("KurdishTTS quota exhausted or plan inactive")
            elif status == 422:
                raise TTSError(f"KurdishTTS validation error: {body}")
            else:
                last_error = f"KurdishTTS HTTP {status}: {body}"
                if attempt < KURDISH_TTS_MAX_RETRIES:
                    time.sleep(1 * attempt)
                    continue
                raise TTSError(last_error)

        except URLError as e:
            reason = str(e.reason) if hasattr(e, "reason") else str(e)
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                last_error = f"KurdishTTS timeout after {KURDISH_TTS_TIMEOUT}s (attempt {attempt})"
            else:
                last_error = f"KurdishTTS connection failed: {reason[:100]} (attempt {attempt})"
            if attempt < KURDISH_TTS_MAX_RETRIES:
                time.sleep(1 * attempt)
                continue

        except TTSError:
            raise

        except Exception as e:
            last_error = f"KurdishTTS unexpected error: {str(e)[:100]} (attempt {attempt})"
            if attempt < KURDISH_TTS_MAX_RETRIES:
                time.sleep(1 * attempt)
                continue

    raise TTSError(last_error or "KurdishTTS synthesis failed after retries")


# ─── WAV Validation and Assembly ─────────────────────────────────────────────

def _validate_wav(data: bytes):
    """Validate that data is a proper WAV file with expected audio params."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            if wf.getnchannels() != EXPECTED_CHANNELS:
                raise TTSError(f"KurdishTTS WAV has {wf.getnchannels()} channels, expected {EXPECTED_CHANNELS}")
            if wf.getsampwidth() != EXPECTED_SAMPLE_WIDTH:
                raise TTSError(f"KurdishTTS WAV has {wf.getsampwidth()}-byte samples, expected {EXPECTED_SAMPLE_WIDTH}")
            if wf.getframerate() != EXPECTED_SAMPLE_RATE:
                raise TTSError(f"KurdishTTS WAV has {wf.getframerate()} Hz, expected {EXPECTED_SAMPLE_RATE}")
            if wf.getnframes() == 0:
                raise TTSError("KurdishTTS WAV contains zero audio frames")
    except wave.Error as e:
        raise TTSError(f"KurdishTTS returned invalid WAV data: {e}")


def _extract_pcm(wav_data: bytes) -> bytes:
    """Extract raw PCM frames from a WAV file."""
    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        return wf.readframes(wf.getnframes())


def assemble_wav(chunks: list) -> bytes:
    """
    Assemble multiple WAV byte buffers into a single valid WAV file.

    Extracts PCM frames from each chunk, concatenates them, and writes
    a new WAV with a correct header using Python's standard wave module.
    """
    if len(chunks) == 1:
        return chunks[0]

    all_pcm = b""
    for chunk_data in chunks:
        all_pcm += _extract_pcm(chunk_data)

    output = io.BytesIO()
    with wave.open(output, "wb") as wf:
        wf.setnchannels(EXPECTED_CHANNELS)
        wf.setsampwidth(EXPECTED_SAMPLE_WIDTH)
        wf.setframerate(EXPECTED_SAMPLE_RATE)
        wf.writeframes(all_pcm)

    return output.getvalue()


# ─── Full Synthesis (with chunking + WAV assembly) ───────────────────────────

def synthesize_kurdish(text: str, speaker_id: str = None) -> bytes:
    """
    Synthesize full Kurdish text to WAV, handling chunking for long texts.

    Returns a single valid WAV file (PCM 16-bit, mono, 22050 Hz).
    Raises TTSError if the API key is missing or synthesis fails.
    """
    if speaker_id is None:
        speaker_id = KURDISH_TTS_SPEAKER

    api_key = get_api_key()

    chunks = chunk_text(text)
    print(f"  KurdishTTS: synthesizing {len(text)} chars in {len(chunks)} chunk(s), speaker={speaker_id}")

    wav_parts = []
    total_chars = 0

    for i, chunk in enumerate(chunks):
        print(f"  KurdishTTS chunk {i + 1}/{len(chunks)}: {len(chunk)} chars")
        wav_data = synthesize_chunk(chunk, api_key, speaker_id)
        wav_parts.append(wav_data)
        total_chars += len(chunk)

    # Assemble into single WAV
    combined = assemble_wav(wav_parts)
    print(f"  KurdishTTS: assembled WAV {len(combined)} bytes from {total_chars} chars, {len(wav_parts)} part(s)")

    return combined


# ─── TTSProvider Implementation ──────────────────────────────────────────────

class KurdishTTSProvider(TTSProvider):
    """
    Kurdish TTS provider using kurdishtts.com API.

    Supports Kurmanji Kurdish in Latin script.
    Structured for future Sorani extension (separate script generation needed).
    """

    def __init__(self, speaker_id: str = None):
        self._speaker_id = speaker_id or KURDISH_TTS_SPEAKER

    def synthesize(self, text: str, language: str = "ku", voice_id: Optional[str] = None) -> TTSResult:
        """Synthesize Kurdish text to speech."""
        if language not in ("ku", "kmr", "kurmanji"):
            raise TTSError(f"KurdishTTSProvider does not support language: {language}")

        speaker = voice_id or self._speaker_id
        audio_data = synthesize_kurdish(text, speaker_id=speaker)

        return TTSResult(
            audio_data=audio_data,
            duration_seconds=0.0,  # Could be computed from WAV frame count
            provider="kurdish-tts",
            voice_id=speaker,
            language="ku",
            format="wav",
            chars_synthesized=len(text),
        )

    def supports_language(self, language: str) -> bool:
        return language in ("ku", "kmr", "kurmanji")

    @property
    def provider_name(self) -> str:
        return "kurdish-tts"
