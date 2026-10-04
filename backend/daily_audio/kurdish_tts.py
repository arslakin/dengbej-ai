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
Output: uncompressed PCM WAV, mono, 16-bit. The provider has been observed to
    emit either 22050 Hz or 24000 Hz depending on the model/voice; both native
    rates are accepted and preserved as-is. Audio is never resampled, and a
    24000 Hz stream is never reinterpreted as 22050 Hz.
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
# Final Lambda safety margin (seconds). An outbound HTTP attempt is only begun
# when its request timeout plus this margin still fits inside the remaining
# Lambda execution time, so the function returns a controlled result instead of
# being killed mid-request by a hard Lambda timeout.
KURDISH_TTS_SAFETY_MARGIN = int(os.environ.get("KURDISH_TTS_SAFETY_MARGIN", "30"))

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


# ─── Deadline awareness ──────────────────────────────────────────────────────

class TTSPartialResultError(TTSError):
    """
    Raised when synthesis fails PART-WAY through, carrying conservative
    accounting so the caller can refund only the characters that were never
    submitted to the provider.

    Fields:
      attempted_chars  — characters in chunks for which at least one HTTP
                         request was submitted (the provider may have billed
                         them; retain them in the quota).
      completed_chunks — number of chunks that fully succeeded before the
                         failure.
      total_chunks     — total chunks the text was split into.
      stage            — a short label of where it failed (e.g.
                         "time_budget", "chunk_request", "wav_validation",
                         "assembly").

    No partial audio is ever produced or persisted on any of these paths.
    """

    def __init__(self, message, attempted_chars=0, completed_chunks=0,
                 total_chunks=0, stage="unknown"):
        super().__init__(message)
        self.attempted_chars = attempted_chars
        self.completed_chunks = completed_chunks
        self.total_chunks = total_chunks
        self.stage = stage


class TTSTimeBudgetError(TTSPartialResultError):
    """
    Raised when there is not enough remaining Lambda execution time to safely
    begin (or retry) an outbound KurdishTTS request. A CONTROLLED exit that
    carries the same partial accounting as its base class (stage="time_budget"
    by default). No partial audio is ever produced on this path.
    """

    def __init__(self, message, attempted_chars=0, completed_chunks=0,
                 total_chunks=0, stage="time_budget"):
        super().__init__(
            message,
            attempted_chars=attempted_chars,
            completed_chunks=completed_chunks,
            total_chunks=total_chunks,
            stage=stage,
        )


class Deadline:
    """
    Wraps a Lambda ``context`` to answer "is there enough time left to start an
    HTTP attempt whose request timeout is ``http_timeout`` seconds?".

    A ``None`` context means NO deadline enforcement (unlimited time). This
    keeps direct unit-test and non-Lambda usage working unchanged: callers that
    do not pass a context behave exactly as before this change.
    """

    def __init__(self, context=None, safety_margin_s=None):
        self._context = context
        self._margin = KURDISH_TTS_SAFETY_MARGIN if safety_margin_s is None else safety_margin_s

    @property
    def enforced(self) -> bool:
        return self._context is not None and hasattr(self._context, "get_remaining_time_in_millis")

    def remaining_s(self):
        """Remaining Lambda time in seconds, or None if unenforced."""
        if not self.enforced:
            return None
        try:
            return self._context.get_remaining_time_in_millis() / 1000.0
        except Exception:
            # If the context cannot report time, do not block synthesis.
            return None

    def fits(self, http_timeout_s: int) -> bool:
        """True if an attempt with this HTTP timeout plus the safety margin fits."""
        remaining = self.remaining_s()
        if remaining is None:
            return True  # unenforced -> always allowed
        return remaining >= (http_timeout_s + self._margin)

# Expected WAV parameters from the API.
# The provider emits uncompressed PCM, mono, 16-bit. The sample rate is NOT
# fixed: 22050 Hz and 24000 Hz have both been observed in production. Accept
# either native rate and preserve it; reject anything else. Audio is never
# resampled.
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
ALLOWED_SAMPLE_RATES = (22050, 24000)
# PCM/uncompressed WAV reports a compression type of "NONE" via the wave module.
EXPECTED_COMPTYPE = "NONE"

# Backward-compatible alias: the lowest supported native rate. Retained so
# existing imports keep working; validation uses ALLOWED_SAMPLE_RATES, not this.
EXPECTED_SAMPLE_RATE = 22050

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

def synthesize_chunk(text: str, api_key: str, speaker_id: str = None, deadline: "Deadline" = None) -> bytes:
    """
    Synthesize a single text chunk via the KurdishTTS API.
    Returns raw WAV bytes.

    Raises TTSError on failure after retries. If a ``deadline`` is supplied,
    the remaining Lambda time is checked before EVERY HTTP attempt (including
    retries); if the attempt's request timeout plus the safety margin would not
    fit, a ``TTSTimeBudgetError`` is raised BEFORE any request is sent. A
    ``None`` deadline disables this check (direct/non-Lambda usage unchanged).
    """
    if speaker_id is None:
        speaker_id = KURDISH_TTS_SPEAKER
    if deadline is None:
        deadline = Deadline(None)

    payload = json.dumps({
        "text": text,
        "speaker_id": speaker_id,
        "model_version": KURDISH_TTS_MODEL,
        "format": "wav",
        "speed": KURDISH_TTS_SPEED,
    }).encode("utf-8")

    last_error = None
    for attempt in range(1, KURDISH_TTS_MAX_RETRIES + 1):
        # Deadline guard BEFORE every attempt (first try AND each retry): never
        # begin an HTTP request we cannot finish inside the Lambda time budget.
        if not deadline.fits(KURDISH_TTS_TIMEOUT):
            raise TTSTimeBudgetError(
                f"Insufficient Lambda time for KurdishTTS attempt "
                f"(need {KURDISH_TTS_TIMEOUT}s + {deadline._margin}s margin, "
                f"remaining {deadline.remaining_s():.1f}s)"
            )
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
    """Validate that data is a proper WAV file with supported audio params.

    Accepts only uncompressed PCM, mono, 16-bit audio at one of the supported
    native sample rates (22050 Hz or 24000 Hz). Rejects compressed, stereo,
    non-16-bit, zero-frame, unsupported-rate, or malformed WAV data.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            comptype = wf.getcomptype()
            if comptype != EXPECTED_COMPTYPE:
                raise TTSError(
                    f"KurdishTTS WAV is compressed ({comptype}/{wf.getcompname()}), "
                    f"expected uncompressed PCM ({EXPECTED_COMPTYPE})"
                )
            if wf.getnchannels() != EXPECTED_CHANNELS:
                raise TTSError(f"KurdishTTS WAV has {wf.getnchannels()} channels, expected {EXPECTED_CHANNELS}")
            if wf.getsampwidth() != EXPECTED_SAMPLE_WIDTH:
                raise TTSError(f"KurdishTTS WAV has {wf.getsampwidth()}-byte samples, expected {EXPECTED_SAMPLE_WIDTH}")
            if wf.getframerate() not in ALLOWED_SAMPLE_RATES:
                allowed = " or ".join(str(r) for r in ALLOWED_SAMPLE_RATES)
                raise TTSError(f"KurdishTTS WAV has {wf.getframerate()} Hz, expected {allowed}")
            if wf.getnframes() == 0:
                raise TTSError("KurdishTTS WAV contains zero audio frames")
    except wave.Error as e:
        raise TTSError(f"KurdishTTS returned invalid WAV data: {e}")


def _extract_pcm(wav_data: bytes) -> bytes:
    """Extract raw PCM frames from a WAV file."""
    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        return wf.readframes(wf.getnframes())


def _read_wav_params(wav_data: bytes):
    """Return the (channels, sampwidth, framerate, comptype) of a WAV buffer."""
    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        return (
            wf.getnchannels(),
            wf.getsampwidth(),
            wf.getframerate(),
            wf.getcomptype(),
        )


def assemble_wav(chunks: list) -> bytes:
    """
    Assemble multiple WAV byte buffers into a single valid WAV file.

    The audio parameters (channels, sample width, sample rate, compression)
    are read from the FIRST validated chunk and used verbatim to write the
    combined file. Every subsequent chunk must report the exact same
    parameters; mixed-rate or mixed-format chunks are rejected. Audio is
    never resampled and a 24000 Hz stream is never relabelled as 22050 Hz.
    """
    if len(chunks) == 1:
        return chunks[0]

    # Validate and lock the format from the first chunk.
    _validate_wav(chunks[0])
    base_channels, base_width, base_rate, base_comptype = _read_wav_params(chunks[0])

    all_pcm = _extract_pcm(chunks[0])
    for index, chunk_data in enumerate(chunks[1:], start=2):
        _validate_wav(chunk_data)
        channels, width, rate, comptype = _read_wav_params(chunk_data)
        if (channels, width, rate, comptype) != (base_channels, base_width, base_rate, base_comptype):
            raise TTSError(
                "KurdishTTS WAV chunk "
                f"{index} format mismatch: got "
                f"{channels}ch/{width}B/{rate}Hz/{comptype}, "
                f"expected {base_channels}ch/{base_width}B/{base_rate}Hz/{base_comptype}"
            )
        all_pcm += _extract_pcm(chunk_data)

    output = io.BytesIO()
    with wave.open(output, "wb") as wf:
        wf.setnchannels(base_channels)
        wf.setsampwidth(base_width)
        wf.setframerate(base_rate)
        wf.writeframes(all_pcm)

    return output.getvalue()


# ─── Full Synthesis (with chunking + WAV assembly) ───────────────────────────

def synthesize_kurdish(text: str, speaker_id: str = None, deadline: "Deadline" = None) -> bytes:
    """
    Synthesize full Kurdish text to WAV, handling chunking for long texts.

    Returns a single valid uncompressed PCM WAV (mono, 16-bit) at the
    provider's native sample rate (22050 Hz or 24000 Hz), preserved as-is.
    When the text is chunked, every chunk must share the same format or
    assembly fails.

    If a ``deadline`` is supplied, remaining Lambda time is checked before every
    outbound HTTP attempt (including retries). When time runs out, a
    ``TTSTimeBudgetError`` is raised carrying ``attempted_chars`` (characters in
    chunks for which at least one request was submitted — which the provider may
    have billed), ``completed_chunks`` and ``total_chunks``. No partial WAV is
    ever produced on that path. A ``None`` deadline means unlimited (direct and
    non-Lambda usage unchanged). Raises TTSError if the API key is missing or
    synthesis fails for other reasons.
    """
    if speaker_id is None:
        speaker_id = KURDISH_TTS_SPEAKER
    if deadline is None:
        deadline = Deadline(None)

    # Pre-request setup: key retrieval and chunking happen BEFORE any outbound
    # provider request. A failure here means nothing was ever submitted, so the
    # caller must refund the FULL reservation. Surface it as a partial result
    # with stage="pre_request" and attempted_chars=0 so every failure path flows
    # through the same structured accounting (never the generic "failed" path).
    try:
        api_key = get_api_key()
        chunks = chunk_text(text)
    except TTSPartialResultError:
        raise
    except TTSError as e:
        print(f"  KurdishTTS: pre_request failure (no request submitted): {str(e)[:120]}")
        raise TTSPartialResultError(
            f"Synthesis setup failed before any request: {str(e)[:160]}",
            attempted_chars=0,
            completed_chunks=0,
            total_chunks=0,
            stage="pre_request",
        )

    total_chunks = len(chunks)
    print(f"  KurdishTTS: synthesizing {len(text)} chars in {total_chunks} chunk(s), speaker={speaker_id}")

    wav_parts = []
    completed_chars = 0   # chars in chunks that fully succeeded
    attempted_chars = 0   # chars in chunks for which a request was submitted

    for i, chunk in enumerate(chunks):
        chunk_len = len(chunk)
        # Pre-chunk deadline guard: if even the first attempt for this chunk
        # cannot fit, stop BEFORE submitting anything for it. These chars are
        # not attempted, so the caller refunds them.
        if not deadline.fits(KURDISH_TTS_TIMEOUT):
            print(
                f"  KurdishTTS: time budget exhausted before chunk {i + 1}/{total_chunks}; "
                f"attempted={attempted_chars} chars, completed={i} chunk(s)"
            )
            raise TTSTimeBudgetError(
                f"Time budget exhausted before chunk {i + 1}/{total_chunks}",
                attempted_chars=attempted_chars,
                completed_chunks=i,
                total_chunks=total_chunks,
            )
        print(f"  KurdishTTS chunk {i + 1}/{total_chunks}: {chunk_len} chars")
        # The deadline pre-guard above passed, so the first attempt WILL be
        # submitted. Count this chunk as attempted BEFORE the call: the request
        # reaches the provider and may be billed even if it later fails.
        attempted_chars += chunk_len
        try:
            wav_data = synthesize_chunk(chunk, api_key, speaker_id, deadline=deadline)
        except TTSTimeBudgetError:
            # A deadline stop fired inside the (first/retry) attempt loop for
            # this chunk. The request for this chunk never completed; it may or
            # may not have been billed, so we conservatively keep it attempted.
            print(
                f"  KurdishTTS: time budget exhausted during chunk {i + 1}/{total_chunks}; "
                f"attempted={attempted_chars} chars, completed={i} chunk(s)"
            )
            raise TTSTimeBudgetError(
                f"Time budget exhausted during chunk {i + 1}/{total_chunks}",
                attempted_chars=attempted_chars,
                completed_chunks=i,
                total_chunks=total_chunks,
            )
        except TTSError as e:
            # Any other provider/network/validation failure for THIS chunk after
            # a request was submitted (HTTP error, connection failure, collapsed
            # generation, invalid/malformed/mixed WAV). The provider received
            # this chunk's request, so retain it (and all earlier chunks) as
            # attempted; the caller refunds only the never-submitted remainder.
            stage = "wav_validation" if "WAV" in str(e) else "chunk_request"
            print(
                f"  KurdishTTS: {stage} failure on chunk {i + 1}/{total_chunks}; "
                f"attempted={attempted_chars} chars, completed={i} chunk(s): {str(e)[:120]}"
            )
            raise TTSPartialResultError(
                f"Chunk {i + 1}/{total_chunks} failed ({stage}): {str(e)[:160]}",
                attempted_chars=attempted_chars,
                completed_chunks=i,
                total_chunks=total_chunks,
                stage=stage,
            )
        wav_parts.append(wav_data)
        completed_chars += chunk_len

    # Assemble into single WAV. By here every chunk's request was submitted and
    # individually validated, so on an assembly/mixed-format failure we retain
    # ALL submitted characters and refund nothing.
    try:
        combined = assemble_wav(wav_parts)
    except TTSError as e:
        print(
            f"  KurdishTTS: assembly failure after {total_chunks} submitted chunk(s); "
            f"attempted={attempted_chars} chars: {str(e)[:120]}"
        )
        raise TTSPartialResultError(
            f"WAV assembly failed after all {total_chunks} chunk(s) submitted: {str(e)[:160]}",
            attempted_chars=attempted_chars,
            completed_chunks=total_chunks,
            total_chunks=total_chunks,
            stage="assembly",
        )
    print(f"  KurdishTTS: assembled WAV {len(combined)} bytes from {completed_chars} chars, {len(wav_parts)} part(s)")

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
