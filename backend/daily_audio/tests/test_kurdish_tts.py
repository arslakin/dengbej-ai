"""
Unit tests for Kurdish TTS provider (kurdishtts.com integration).

Tests cover:
- Free-tier chunking (480-char default limit)
- Successful single-chunk synthesis
- Multi-chunk WAV output assembly
- Invalid WAV data handling
- Missing secret / auth / quota failures
- Timeout handling
- English Polly fallback when Kurdish TTS fails
- Idempotency (unchanged scripts not re-synthesized)
- S3 metadata (content-type, key extension)
- Provider interface
"""

import io
import sys
import os
import wave
from decimal import Decimal
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kurdish_tts import (
    chunk_text,
    synthesize_chunk,
    synthesize_kurdish,
    assemble_wav,
    get_api_key,
    KurdishTTSProvider,
    KURDISH_TTS_MAX_CHARS,
    EXPECTED_SAMPLE_RATE,
    EXPECTED_CHANNELS,
    EXPECTED_SAMPLE_WIDTH,
    MIN_WAV_SIZE,
    _validate_wav,
    _extract_pcm,
)
from tts_provider import TTSError


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_wav(pcm_data: bytes, nchannels=1, sampwidth=2, framerate=22050) -> bytes:
    """Create a valid WAV file from raw PCM data."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# 0.1 seconds of silence at 22050 Hz, 16-bit mono = 4410 bytes of PCM
SILENCE_PCM = b"\x00\x00" * 2205
FAKE_WAV = make_wav(SILENCE_PCM)

# Different PCM content for multi-chunk test
PCM_A = b"\x01\x00" * 2205
PCM_B = b"\x02\x00" * 2205
WAV_A = make_wav(PCM_A)
WAV_B = make_wav(PCM_B)


# ─── Test: Free-tier Chunking ────────────────────────────────────────────────

def test_chunk_text_within_limit():
    """Text within 480 chars should return single chunk."""
    text = "Rojbaş. Ev Dengbêj e."
    chunks = chunk_text(text, max_chars=480)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_respects_free_tier_default():
    """Default limit should be 480 (free-tier safe)."""
    assert KURDISH_TTS_MAX_CHARS == 480


def test_chunk_text_splits_on_sentences():
    """Long text should split on sentence boundaries."""
    text = "Hevok yek. Hevok du. Hevok sê. Hevok çar."
    chunks = chunk_text(text, max_chars=25)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 25


def test_chunk_text_many_sentences():
    """Typical program script (~800 chars) should split into 2+ chunks at 480."""
    text = "Rojbaş. Ev Dengbêj e. " + "Ev nûçeyek e ji cîhanê. " * 25  # ~622 chars
    chunks = chunk_text(text, max_chars=480)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 480


def test_chunk_text_handles_long_sentence():
    """A sentence longer than the limit should be sub-split."""
    text = "A" * 600
    chunks = chunk_text(text, max_chars=480)
    assert len(chunks) >= 2
    combined = "".join(chunks)
    assert len(combined) == 600


def test_chunk_text_preserves_all_content():
    """All text should be present across chunks."""
    text = "Hevok A. " * 60  # ~540 chars
    chunks = chunk_text(text, max_chars=480)
    combined = " ".join(chunks)
    assert combined.count("Hevok A") == 60


# ─── Test: Multi-chunk WAV Assembly ──────────────────────────────────────────

def test_assemble_wav_single_chunk():
    """Single chunk should be returned as-is."""
    result = assemble_wav([FAKE_WAV])
    assert result == FAKE_WAV


def test_assemble_wav_multi_chunk():
    """Multiple WAV chunks should produce a valid combined WAV."""
    result = assemble_wav([WAV_A, WAV_B])

    # Validate output is valid WAV
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getnchannels() == EXPECTED_CHANNELS
        assert wf.getsampwidth() == EXPECTED_SAMPLE_WIDTH
        assert wf.getframerate() == EXPECTED_SAMPLE_RATE
        # Frame count should be sum of both
        assert wf.getnframes() == 2205 + 2205
        pcm = wf.readframes(wf.getnframes())
        assert pcm == PCM_A + PCM_B


def test_assemble_wav_three_chunks():
    """Three chunks assembled correctly."""
    pcm_c = b"\x03\x00" * 1000
    wav_c = make_wav(pcm_c)
    result = assemble_wav([WAV_A, WAV_B, wav_c])

    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getnframes() == 2205 + 2205 + 1000


# ─── Test: Invalid WAV Data ──────────────────────────────────────────────────

def test_validate_wav_rejects_non_wav():
    """Non-WAV data should raise TTSError."""
    try:
        _validate_wav(b"this is not wav data at all")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "invalid WAV" in str(e).lower() or "wav" in str(e).lower()


def test_validate_wav_rejects_wrong_sample_rate():
    """WAV with wrong sample rate should be rejected."""
    bad_wav = make_wav(SILENCE_PCM, framerate=44100)
    try:
        _validate_wav(bad_wav)
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "44100" in str(e) or "Hz" in str(e)


def test_validate_wav_rejects_stereo():
    """Stereo WAV should be rejected."""
    stereo_pcm = b"\x00\x00\x00\x00" * 2205  # stereo needs 2x samples per frame
    bad_wav = make_wav(stereo_pcm, nchannels=2)
    try:
        _validate_wav(bad_wav)
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "channel" in str(e).lower()


def test_validate_wav_rejects_empty_frames():
    """WAV with zero frames should be rejected."""
    empty_wav = make_wav(b"")
    try:
        _validate_wav(empty_wav)
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "zero" in str(e).lower()


# ─── Test: Successful Synthesis ──────────────────────────────────────────────

@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_synthesize_chunk_success(mock_urlopen, mock_key):
    """Successful single chunk returns WAV bytes."""
    mock_key.return_value = "test-key-123"
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "audio/wav"}
    mock_resp.read.return_value = FAKE_WAV
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    result = synthesize_chunk("Rojbaş", "test-key-123")
    assert len(result) > MIN_WAV_SIZE
    # Should be valid WAV
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 22050


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_synthesize_kurdish_multi_chunk_wav(mock_urlopen, mock_key):
    """Long text produces multi-chunk request and valid assembled WAV."""
    mock_key.return_value = "test-key-123"

    call_count = [0]

    def mock_open_side_effect(req, timeout=None):
        call_count[0] += 1
        resp = MagicMock()
        resp.status = 200
        resp.headers = {"Content-Type": "audio/wav"}
        resp.read.return_value = WAV_A if call_count[0] % 2 == 1 else WAV_B
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    mock_urlopen.side_effect = mock_open_side_effect

    # Create text that exceeds free-tier (480 chars)
    text = "Hevok yekem. " * 40  # ~560 chars
    result = synthesize_kurdish(text)

    # Should have made multiple API calls
    assert call_count[0] >= 2
    # Result should be valid WAV
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == EXPECTED_SAMPLE_RATE
        assert wf.getnframes() > 0


# ─── Test: Missing Secret ────────────────────────────────────────────────────

@patch("kurdish_tts._cached_api_key", None)
@patch("kurdish_tts.boto3.client")
def test_get_api_key_secret_not_found(mock_boto):
    """Missing secret should raise TTSError."""
    from botocore.exceptions import ClientError
    mock_client = MagicMock()
    mock_boto.return_value = mock_client
    mock_client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "Not found"}},
        "GetSecretValue"
    )
    import kurdish_tts
    kurdish_tts._cached_api_key = None
    try:
        get_api_key()
        assert False
    except TTSError as e:
        assert "not found" in str(e).lower()


@patch("kurdish_tts._cached_api_key", None)
@patch("kurdish_tts.boto3.client")
def test_get_api_key_access_denied(mock_boto):
    """AccessDeniedException should raise descriptive TTSError."""
    from botocore.exceptions import ClientError
    mock_client = MagicMock()
    mock_boto.return_value = mock_client
    mock_client.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "No access"}},
        "GetSecretValue"
    )
    import kurdish_tts
    kurdish_tts._cached_api_key = None
    try:
        get_api_key()
        assert False
    except TTSError as e:
        assert "permission" in str(e).lower()


# ─── Test: Timeout ───────────────────────────────────────────────────────────

@patch("kurdish_tts.urlopen")
def test_synthesize_chunk_timeout(mock_urlopen):
    """Timeout should retry and raise TTSError."""
    from urllib.error import URLError
    mock_urlopen.side_effect = URLError("timed out")

    try:
        synthesize_chunk("Test", "key123")
        assert False
    except TTSError as e:
        assert "timeout" in str(e).lower() or "connection" in str(e).lower()
    assert mock_urlopen.call_count == 2


# ─── Test: Auth / Quota Failures ─────────────────────────────────────────────

@patch("kurdish_tts.urlopen")
def test_synthesize_chunk_auth_failure(mock_urlopen):
    """401 should immediately raise without retry."""
    from urllib.error import HTTPError
    mock_urlopen.side_effect = HTTPError(
        "url", 401, "Unauthorized", {}, io.BytesIO(b"")
    )
    try:
        synthesize_chunk("Test", "bad-key")
        assert False
    except TTSError as e:
        assert "authentication" in str(e).lower()
    assert mock_urlopen.call_count == 1


@patch("kurdish_tts.urlopen")
def test_synthesize_chunk_quota_exhausted(mock_urlopen):
    """403 should immediately raise without retry."""
    from urllib.error import HTTPError
    mock_urlopen.side_effect = HTTPError(
        "url", 403, "Forbidden", {}, io.BytesIO(b"")
    )
    try:
        synthesize_chunk("Test", "key123")
        assert False
    except TTSError as e:
        assert "quota" in str(e).lower()
    assert mock_urlopen.call_count == 1


# ─── Test: Fallback ──────────────────────────────────────────────────────────

@patch("lambda_function.TTS_ENABLED", True)
@patch("lambda_function.synthesize_and_upload")
@patch("lambda_function.generate_english_narration")
@patch("lambda_function.get_processed_briefing")
@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.store_script")
def test_kurdish_tts_failure_preserves_english(mock_store, mock_bedrock, mock_get, mock_en, mock_synth):
    """If Kurdish TTS fails, English Polly audio should still be stored."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "stories": [{"processing_status": "processed", "headline": "Test", "category": "world",
                     "summary_en": "Summary", "summary_ku": "Kurte", "primary_source": "BBC"}] * 5,
    }
    mock_get.return_value = briefing
    mock_bedrock.return_value = "Rojbaş. Ev Dengbêj e. Nûçe."
    mock_en.return_value = "English narration text."
    mock_synth.return_value = "https://dengbej-audio.s3.amazonaws.com/daily/en_test.mp3"

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}):
        import sys
        sys.modules["kurdish_tts"].synthesize_kurdish.side_effect = Exception("Kurdish TTS unavailable")
        sys.modules["kurdish_tts"].TTSError = Exception

        result = lambda_handler({"date": "2026-09-01", "force": True}, None)

    assert result["statusCode"] == 200
    assert mock_store.called


# ─── Test: Idempotency ───────────────────────────────────────────────────────

@patch("lambda_function.get_processed_briefing")
def test_existing_script_not_regenerated(mock_get):
    """If script already exists and force=False, no TTS calls."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "daily_audio_script_ku": "Existing script",
        "stories": [{"processing_status": "processed"}] * 5,
    }
    mock_get.return_value = briefing

    result = lambda_handler({"date": "2026-09-01", "force": False}, None)
    assert result["statusCode"] == 200
    assert result["body"]["status"] == "already_exists"


# ─── Test: S3 Metadata ───────────────────────────────────────────────────────

@patch("lambda_function.TTS_ENABLED", True)
@patch("lambda_function.s3_client")
@patch("lambda_function.synthesize_and_upload")
@patch("lambda_function.generate_english_narration")
@patch("lambda_function.get_processed_briefing")
@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.store_script")
def test_kurdish_audio_uploaded_as_wav(mock_store, mock_bedrock, mock_get, mock_en, mock_synth, mock_s3):
    """Kurdish audio should be uploaded with .wav key and audio/wav content type."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "stories": [{"processing_status": "processed", "headline": "Test", "category": "world",
                     "summary_en": "Summary", "summary_ku": "Kurte", "primary_source": "BBC"}] * 5,
    }
    mock_get.return_value = briefing
    mock_bedrock.return_value = "Rojbaş. Script."
    mock_en.return_value = "English."
    mock_synth.return_value = "https://dengbej-audio.s3.amazonaws.com/daily/en.mp3"

    with patch("lambda_function.TTS_ENABLED", True):
        # Mock the Kurdish TTS module to return a valid WAV
        with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as mods:
            import sys
            sys.modules["kurdish_tts"].synthesize_kurdish.return_value = FAKE_WAV
            sys.modules["kurdish_tts"].TTSError = TTSError

            result = lambda_handler({"date": "2026-09-01", "force": True}, None)

    # Check S3 put_object was called with WAV content type
    if mock_s3.put_object.called:
        call_kwargs = mock_s3.put_object.call_args
        if call_kwargs:
            kwargs = call_kwargs[1] if call_kwargs[1] else {}
            # The key should end with .wav
            key = kwargs.get("Key", "")
            content_type = kwargs.get("ContentType", "")
            if "_ku_" in key:
                assert key.endswith(".wav"), f"Key should end with .wav: {key}"
                assert content_type == "audio/wav", f"ContentType should be audio/wav: {content_type}"


# ─── Test: Provider Interface ────────────────────────────────────────────────

@patch("kurdish_tts.synthesize_kurdish")
def test_provider_returns_wav_format(mock_synth):
    """KurdishTTSProvider.synthesize should return TTSResult with wav format."""
    mock_synth.return_value = FAKE_WAV

    provider = KurdishTTSProvider()
    result = provider.synthesize("Rojbaş")

    assert result.audio_data == FAKE_WAV
    assert result.provider == "kurdish-tts"
    assert result.language == "ku"
    assert result.format == "wav"


def test_provider_supports_kurdish():
    """Provider should support Kurdish language codes."""
    provider = KurdishTTSProvider()
    assert provider.supports_language("ku") is True
    assert provider.supports_language("kmr") is True
    assert provider.supports_language("kurmanji") is True
    assert provider.supports_language("en") is False


def test_provider_rejects_unsupported_language():
    """Provider should raise TTSError for non-Kurdish."""
    provider = KurdishTTSProvider()
    try:
        provider.synthesize("Hello", language="en")
        assert False
    except TTSError as e:
        assert "not support" in str(e).lower()


def test_provider_speaker_configurable():
    """Speaker should be configurable via constructor."""
    provider = KurdishTTSProvider(speaker_id="kurmanji_241")
    assert provider._speaker_id == "kurmanji_241"


# ─── Test: KURDISH_TTS_ENABLED flag ──────────────────────────────────────────

@patch("lambda_function.KURDISH_TTS_ENABLED", False)
@patch("lambda_function.TTS_ENABLED", True)
@patch("lambda_function.synthesize_and_upload")
@patch("lambda_function.generate_english_narration")
@patch("lambda_function.get_processed_briefing")
@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.store_script")
def test_kurdish_tts_disabled_skips_synthesis(mock_store, mock_bedrock, mock_get, mock_en, mock_synth):
    """When KURDISH_TTS_ENABLED=false, Kurdish TTS is never called."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "stories": [{"processing_status": "processed", "headline": "Test", "category": "world",
                     "summary_en": "Summary", "summary_ku": "Kurte", "primary_source": "BBC"}] * 5,
    }
    mock_get.return_value = briefing
    mock_bedrock.return_value = "Rojbaş. Script ku."
    mock_en.return_value = "English narration."
    mock_synth.return_value = "https://dengbej-audio.s3.amazonaws.com/daily/en.mp3"

    result = lambda_handler({"date": "2026-09-01", "force": True}, None)

    assert result["statusCode"] == 200
    # store_script should have been called — check audio_url_ku is None
    call_args = mock_store.call_args
    kwargs = call_args[1] if call_args[1] else {}
    # audio_url_ku should be None when disabled
    assert kwargs.get("audio_url_ku") is None
    # audio_url should be English (legacy compat)
    assert kwargs.get("audio_url") == "https://dengbej-audio.s3.amazonaws.com/daily/en.mp3"


@patch("lambda_function.KURDISH_TTS_ENABLED", False)
@patch("lambda_function.TTS_ENABLED", True)
@patch("lambda_function.synthesize_and_upload")
@patch("lambda_function.generate_english_narration")
@patch("lambda_function.get_processed_briefing")
@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.store_script")
def test_legacy_audio_url_always_english(mock_store, mock_bedrock, mock_get, mock_en, mock_synth):
    """Legacy audio_url field must always point to English Polly audio."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "stories": [{"processing_status": "processed", "headline": "Test", "category": "world",
                     "summary_en": "S", "summary_ku": "K", "primary_source": "BBC"}] * 5,
    }
    mock_get.return_value = briefing
    mock_bedrock.return_value = "Script."
    mock_en.return_value = "English."
    en_url = "https://dengbej-audio.s3.amazonaws.com/daily/2026-09-01_en_test.mp3"
    mock_synth.return_value = en_url

    result = lambda_handler({"date": "2026-09-01", "force": True}, None)

    assert result["statusCode"] == 200
    # The response audio_url should be English
    assert result["body"]["audio_url"] == en_url
    assert result["body"]["audio_url_en"] == en_url
    assert result["body"]["audio_url_ku"] is None


# ─── Test: Controlled TTS test handler ───────────────────────────────────────

def test_tts_test_rejects_missing_text():
    """Test handler rejects missing text."""
    from lambda_function import lambda_handler
    result = lambda_handler({"test_kurdish_tts": True}, None)
    assert result["statusCode"] == 400
    assert "required" in result["body"]["error"].lower()


def test_tts_test_rejects_too_long_text():
    """Test handler rejects text over 300 chars."""
    from lambda_function import lambda_handler
    result = lambda_handler({"test_kurdish_tts": True, "text": "A" * 301}, None)
    assert result["statusCode"] == 400
    assert "300" in result["body"]["error"]


def test_tts_test_rejects_non_boolean_flag():
    """test_kurdish_tts must be exactly boolean True, not string."""
    from lambda_function import lambda_handler, Telemetry
    # With "true" string, should NOT trigger the test handler
    # It should fall through to normal handling
    with patch("lambda_function.get_processed_briefing") as mock_get:
        mock_get.return_value = None
        result = lambda_handler({"test_kurdish_tts": "true", "date": "2099-01-01"}, None)
        # Normal flow: no briefing found -> 404
        assert result["statusCode"] == 404


@patch("lambda_function.s3_client")
def test_tts_test_success(mock_s3):
    """Successful test stores under tts-tests/ prefix."""
    from lambda_function import lambda_handler

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _:
        import sys
        sys.modules["kurdish_tts"].synthesize_kurdish.return_value = FAKE_WAV

        result = lambda_handler({
            "test_kurdish_tts": True,
            "text": "Rojbaş, ev testek e."
        }, None)

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "test_complete"
    assert result["body"]["chars_synthesized"] == 20
    assert "tts-tests/" in result["body"]["s3_key"]
    assert result["body"]["audio_url"].endswith(".wav")

    # Verify S3 call used tts-tests/ prefix and audio/wav
    call_kwargs = mock_s3.put_object.call_args[1]
    assert call_kwargs["Key"].startswith("tts-tests/")
    assert call_kwargs["ContentType"] == "audio/wav"


# ─── Test: Secrets Manager JSON format ───────────────────────────────────────

@patch("kurdish_tts._cached_api_key", None)
@patch("kurdish_tts.boto3.client")
def test_get_api_key_json_format(mock_boto):
    """Should parse JSON secret with api_key field."""
    mock_client = MagicMock()
    mock_boto.return_value = mock_client
    mock_client.get_secret_value.return_value = {
        "SecretString": '{"api_key": "kt_test_12345"}'
    }

    import kurdish_tts
    kurdish_tts._cached_api_key = None
    key = get_api_key()
    assert key == "kt_test_12345"
    # Reset for other tests
    kurdish_tts._cached_api_key = None


# ─── Test: KURDISH_TTS_SPEED configuration ───────────────────────────────────

def test_speed_default_value():
    """Default speed should be 1.1."""
    from kurdish_tts import KURDISH_TTS_SPEED
    assert KURDISH_TTS_SPEED == 1.1


def test_speed_parse_valid():
    """Valid speeds within range should be accepted."""
    from kurdish_tts import _parse_speed
    assert _parse_speed("1.5") == 1.5
    assert _parse_speed("0.25") == 0.25
    assert _parse_speed("4.0") == 4.0
    assert _parse_speed("2") == 2.0


def test_speed_parse_invalid_falls_back():
    """Invalid speed values should fall back to 1.1."""
    from kurdish_tts import _parse_speed, _SPEED_DEFAULT
    assert _parse_speed("0.1") == _SPEED_DEFAULT  # below min
    assert _parse_speed("5.0") == _SPEED_DEFAULT  # above max
    assert _parse_speed("abc") == _SPEED_DEFAULT  # non-numeric
    assert _parse_speed("") == _SPEED_DEFAULT     # empty
    assert _parse_speed(None) == _SPEED_DEFAULT   # None


def test_speed_parse_boundary():
    """Boundary values should be accepted."""
    from kurdish_tts import _parse_speed
    assert _parse_speed("0.25") == 0.25
    assert _parse_speed("4.0") == 4.0


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_speed_included_in_payload(mock_urlopen, mock_key):
    """Speed should be included in every API request payload."""
    import json as json_mod
    mock_key.return_value = "test-key"
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "audio/wav"}
    mock_resp.read.return_value = FAKE_WAV
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    synthesize_chunk("Rojbaş.", "test-key")

    # Extract the payload sent to urlopen
    call_args = mock_urlopen.call_args
    req = call_args[0][0]  # First positional arg is the Request object
    body = json_mod.loads(req.data.decode("utf-8"))
    assert "speed" in body
    assert body["speed"] == 1.1


# ─── Test: Batch handler ─────────────────────────────────────────────────────

def test_batch_requires_max_chars():
    """Batch handler rejects missing max_chars."""
    from lambda_function import lambda_handler
    result = lambda_handler({"generate_kurdish_batch": True}, None)
    assert result["statusCode"] == 400
    assert "max_chars" in result["body"]["error"]


def test_batch_budget_exhausted():
    """Batch returns budget_exhausted when chars_already_used >= monthly budget."""
    from lambda_function import lambda_handler
    result = lambda_handler({
        "generate_kurdish_batch": True,
        "max_chars": 5000,
        "chars_already_used": 18000,
    }, None)
    assert result["statusCode"] == 200
    assert result["body"]["status"] == "budget_exhausted"


@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_batch_dry_run_reports_candidates(mock_briefing, mock_program):
    """Dry run should report candidates without making TTS calls."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "daily_audio_script_ku": "A" * 500,
        "daily_audio_meta": {"audio_url_ku": None},
    }
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "B" * 300, "story_count": 3,
        "audio_url_ku": None,
    } if pid == "world" else None

    result = lambda_handler({
        "generate_kurdish_batch": True,
        "max_chars": 10000,
        "dry_run": True,
        "date": "2026-09-01",
    }, None)

    assert result["statusCode"] == 200
    body = result["body"]
    assert body["status"] == "dry_run"
    assert body["candidates_found"] == 2
    assert body["total_chars_selected"] == 800  # 500 + 300


@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_batch_dry_run_respects_budget(mock_briefing, mock_program):
    """Dry run should stop selecting when budget would be exceeded."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = {
        "briefing_date": "2026-09-01", "generated_at": "T",
        "daily_audio_script_ku": "A" * 3000,
        "daily_audio_meta": {},
    }
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "B" * 2000, "story_count": 5,
    } if pid in ("world", "middle-east") else None

    result = lambda_handler({
        "generate_kurdish_batch": True,
        "max_chars": 4500,
        "dry_run": True,
        "date": "2026-09-01",
    }, None)

    body = result["body"]
    # Budget is 4500: today (3000) fits, world (2000) and middle-east (2000) both exceed remaining 1500
    assert body["candidates_selected"] == 1
    assert body["total_chars_selected"] == 3000
    assert len(body["skipped"]) == 2
    assert body["skipped"][0]["program_id"] == "world"
    assert body["skipped"][0]["reason"] == "over_budget"


@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_batch_skips_existing_audio_ku(mock_briefing, mock_program):
    """Programs with existing audio_url_ku should be skipped (idempotent)."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = {
        "briefing_date": "2026-09-01", "generated_at": "T",
        "daily_audio_script_ku": "Script",
        "daily_audio_meta": {"audio_url_ku": "https://existing.wav"},
    }
    mock_program.return_value = None

    result = lambda_handler({
        "generate_kurdish_batch": True,
        "max_chars": 10000,
        "dry_run": True,
        "date": "2026-09-01",
    }, None)

    # Briefing already has audio_url_ku -> should be skipped
    assert result["body"]["candidates_found"] == 0


@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_batch_priority_order(mock_briefing, mock_program):
    """Candidates should follow priority: today > world > middle-east > turkey."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = None  # No briefing

    def prog_side_effect(pid, d):
        if pid in ("world", "turkey", "middle-east"):
            return {"program_id": pid, "briefing_date": d, "script_ku": pid * 10, "story_count": 3}
        return None

    mock_program.side_effect = prog_side_effect

    result = lambda_handler({
        "generate_kurdish_batch": True,
        "max_chars": 50000,
        "dry_run": True,
        "date": "2026-09-01",
    }, None)

    programs = [p["program_id"] for p in result["body"]["programs"]]
    assert programs == ["world", "middle-east", "turkey"]


@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function.s3_client")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_batch_execute_stores_ku_only(mock_briefing, mock_program, mock_s3, mock_update):
    """Non-dry-run batch should store audio_url_ku without touching English."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = None
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "Rojbaş.", "story_count": 2,
    } if pid == "world" else None

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _, \
         patch("quota.reserve", return_value=True), \
         patch("quota.get_usage", return_value=0):
        import sys
        sys.modules["kurdish_tts"].synthesize_kurdish.return_value = FAKE_WAV

        result = lambda_handler({
            "generate_kurdish_batch": True,
            "max_chars": 10000,
            "dry_run": False,
            "date": "2026-09-01",
        }, None)

    assert result["body"]["status"] == "completed"
    assert result["body"]["results"][0]["status"] == "success"
    # Verify _update_program_ku_audio was called (not the full store that touches audio_url)
    mock_update.assert_called_once()


# ─── Test: Dry run makes zero side effects ───────────────────────────────────

@patch("lambda_function.s3_client")
@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function._update_briefing_ku_audio")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_dry_run_zero_api_calls(mock_briefing, mock_program, mock_upd_brief, mock_upd_prog, mock_s3):
    """Dry run must make zero KurdishTTS calls, zero S3 uploads, zero DynamoDB updates."""
    from lambda_function import lambda_handler

    mock_briefing.return_value = {
        "briefing_date": "2026-09-01", "generated_at": "T",
        "daily_audio_script_ku": "Script text here.",
        "daily_audio_meta": {},
    }
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "Program script.", "story_count": 3,
    } if pid == "world" else None

    # Patch kurdish_tts to detect if it's ever called
    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _:
        import sys
        ku_mock = sys.modules["kurdish_tts"]
        ku_mock.synthesize_kurdish = MagicMock()

        result = lambda_handler({
            "generate_kurdish_batch": True,
            "max_chars": 50000,
            "dry_run": True,
            "date": "2026-09-01",
        }, None)

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "dry_run"
    # Zero API calls
    ku_mock.synthesize_kurdish.assert_not_called()
    # Zero S3 uploads
    mock_s3.put_object.assert_not_called()
    # Zero DynamoDB updates
    mock_upd_brief.assert_not_called()
    mock_upd_prog.assert_not_called()


# ─── Test: Quota module ──────────────────────────────────────────────────────

@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_quota_reserve_success(mock_resource):
    """Reserve should succeed when under budget."""
    import quota
    quota._dynamodb = None

    mock_table = MagicMock()
    mock_resource.return_value.Table.return_value = mock_table
    mock_table.update_item.return_value = {}

    result = quota.reserve(500, "2026-08")
    assert result is True
    mock_table.update_item.assert_called_once()


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_quota_reserve_exceeds_budget(mock_resource):
    """Reserve should return False when it would exceed budget."""
    from botocore.exceptions import ClientError
    import quota
    quota._dynamodb = None

    mock_table = MagicMock()
    mock_resource.return_value.Table.return_value = mock_table
    mock_table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": ""}},
        "UpdateItem"
    )

    result = quota.reserve(500, "2026-08")
    assert result is False


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_quota_refund(mock_resource):
    """Refund should decrement chars_used."""
    import quota
    quota._dynamodb = None

    mock_table = MagicMock()
    mock_resource.return_value.Table.return_value = mock_table
    mock_table.update_item.return_value = {}

    quota.refund(300, "2026-08")
    mock_table.update_item.assert_called_once()
    # Verify the decrement expression
    call_kwargs = mock_table.update_item.call_args[1]
    assert "chars_used - :dec" in call_kwargs["UpdateExpression"]


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_quota_get_usage(mock_resource):
    """get_usage should return stored chars_used value."""
    import quota
    from decimal import Decimal
    quota._dynamodb = None

    mock_table = MagicMock()
    mock_resource.return_value.Table.return_value = mock_table
    mock_table.get_item.return_value = {
        "Item": {"chars_used": Decimal("6500")}
    }

    result = quota.get_usage("2026-08")
    assert result == 6500


@patch("quota._dynamodb", None)
@patch("quota.boto3.resource")
def test_quota_get_usage_no_record(mock_resource):
    """get_usage should return 0 for a new month."""
    import quota
    quota._dynamodb = None

    mock_table = MagicMock()
    mock_resource.return_value.Table.return_value = mock_table
    mock_table.get_item.return_value = {}

    result = quota.get_usage("2026-09")
    assert result == 0


def test_quota_reserve_zero_chars():
    """Reserving zero chars should succeed trivially."""
    import quota
    assert quota.reserve(0) is True


# ─── Integration: Fail-closed quota + dry-run zero side effects ──────────────

@patch("lambda_function.s3_client")
@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function._update_briefing_ku_audio")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
@patch("quota.boto3.resource")
def test_dry_run_zero_side_effects_integration(mock_quota_res, mock_briefing, mock_program,
                                               mock_upd_brief, mock_upd_prog, mock_s3):
    """
    Integration: a dry run through the real lambda_handler must make
    zero synthesis calls, zero quota writes, zero S3 writes, zero DB updates.
    """
    from lambda_function import lambda_handler
    import quota
    quota._dynamodb = None

    # Quota table mock — record update_item calls
    mock_quota_table = MagicMock()
    mock_quota_res.return_value.Table.return_value = mock_quota_table
    mock_quota_table.get_item.return_value = {"Item": {"chars_used": Decimal("9915")}}

    mock_briefing.return_value = {
        "briefing_date": "2026-08-29", "generated_at": "T",
        "daily_audio_script_ku": "Rojbaş. " * 50,
        "daily_audio_meta": {},
    }
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "Nûçe.", "story_count": 3,
    } if pid == "world" else None

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _:
        import sys
        ku_mock = sys.modules["kurdish_tts"]
        ku_mock.synthesize_kurdish = MagicMock()

        result = lambda_handler({
            "generate_kurdish_batch": True,
            "max_chars": 18000,
            "dry_run": True,
            "date": "2026-08-29",
            "request_id": "DRYRUN-TEST-001",
        }, None)

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "dry_run"
    assert result["body"]["request_id"] == "DRYRUN-TEST-001"
    # Zero synthesis
    ku_mock.synthesize_kurdish.assert_not_called()
    # Zero S3
    mock_s3.put_object.assert_not_called()
    # Zero DB audio updates
    mock_upd_brief.assert_not_called()
    mock_upd_prog.assert_not_called()
    # Zero quota WRITES (get_item for reading is allowed, update_item is not)
    mock_quota_table.update_item.assert_not_called()


@patch("lambda_function.s3_client")
@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_fail_closed_when_reservation_raises(mock_briefing, mock_program, mock_upd_prog, mock_s3):
    """
    Fail-closed: if quota_reserve raises, synthesis must NOT happen.
    """
    from lambda_function import lambda_handler

    mock_briefing.return_value = None
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "Nûçe.", "story_count": 3,
    } if pid == "world" else None

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _, \
         patch("quota.reserve", side_effect=Exception("DynamoDB unavailable")):
        import sys
        ku_mock = sys.modules["kurdish_tts"]
        ku_mock.synthesize_kurdish = MagicMock()

        result = lambda_handler({
            "generate_kurdish_batch": True,
            "max_chars": 18000,
            "dry_run": False,
            "date": "2026-08-29",
        }, None)

    # Synthesis must never have been called (fail closed)
    ku_mock.synthesize_kurdish.assert_not_called()
    mock_s3.put_object.assert_not_called()
    # Result should show skipped with reservation reason
    statuses = [r["status"] for r in result["body"]["results"]]
    assert all(s == "skipped" for s in statuses)
    assert result["body"]["chars_consumed"] == 0


@patch("lambda_function.s3_client")
@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_fail_closed_when_reservation_returns_false(mock_briefing, mock_program, mock_upd_prog, mock_s3):
    """
    Fail-closed: if quota_reserve returns False (budget exceeded), skip synthesis.
    """
    from lambda_function import lambda_handler

    mock_briefing.return_value = None
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "Nûçe.", "story_count": 3,
    } if pid == "world" else None

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _, \
         patch("quota.reserve", return_value=False):
        import sys
        ku_mock = sys.modules["kurdish_tts"]
        ku_mock.synthesize_kurdish = MagicMock()

        result = lambda_handler({
            "generate_kurdish_batch": True,
            "max_chars": 18000,
            "dry_run": False,
            "date": "2026-08-29",
        }, None)

    ku_mock.synthesize_kurdish.assert_not_called()
    mock_s3.put_object.assert_not_called()
    assert result["body"]["chars_consumed"] == 0


@patch("lambda_function.s3_client")
@patch("lambda_function._update_program_ku_audio")
@patch("lambda_function._get_program_for_batch")
@patch("lambda_function._get_briefing_for_batch")
def test_reservation_confirmed_before_synthesis(mock_briefing, mock_program, mock_upd_prog, mock_s3):
    """
    Reservation must be confirmed via get_usage before synthesis proceeds.
    If confirmation fails, refund and skip.
    """
    from lambda_function import lambda_handler

    mock_briefing.return_value = None
    mock_program.side_effect = lambda pid, d: {
        "program_id": pid, "briefing_date": d,
        "script_ku": "Nûçe.", "story_count": 3,
    } if pid == "world" else None

    # get_usage: first call (top of handler, reads current usage) succeeds,
    # subsequent calls (confirmation after reserve) raise.
    usage_calls = [0]
    def usage_side_effect(*a, **k):
        usage_calls[0] += 1
        if usage_calls[0] == 1:
            return 0  # initial read
        raise Exception("cannot confirm")

    with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _, \
         patch("quota.reserve", return_value=True), \
         patch("quota.get_usage", side_effect=usage_side_effect), \
         patch("quota.refund") as mock_refund:
        import sys
        ku_mock = sys.modules["kurdish_tts"]
        ku_mock.synthesize_kurdish = MagicMock()

        result = lambda_handler({
            "generate_kurdish_batch": True,
            "max_chars": 18000,
            "dry_run": False,
            "date": "2026-08-29",
        }, None)

    # Reservation succeeded but confirmation failed -> refund + skip, no synthesis
    ku_mock.synthesize_kurdish.assert_not_called()
    mock_refund.assert_called()
    statuses = [r["status"] for r in result["body"]["results"]]
    assert all(s == "skipped" for s in statuses)


# ─── WAV sample-rate compatibility (22050 Hz and 24000 Hz) ───────────────────
# The live provider was observed emitting 24000 Hz PCM while the code only
# accepted 22050 Hz, causing synthesis to fail with:
#   "KurdishTTS WAV has 24000 Hz, expected 22050"
# These tests lock in support for both native rates (mono, 16-bit, PCM) and the
# strict multi-chunk format-consistency rules (no resampling, no relabelling).

from kurdish_tts import ALLOWED_SAMPLE_RATES, EXPECTED_COMPTYPE  # noqa: E402

# 24000 Hz fixtures (0.1s of PCM at 24000 Hz, 16-bit mono = 2400 frames)
PCM_24K_A = b"\x01\x00" * 2400
PCM_24K_B = b"\x02\x00" * 2400
WAV_24K_A = make_wav(PCM_24K_A, framerate=24000)
WAV_24K_B = make_wav(PCM_24K_B, framerate=24000)


def test_allowed_sample_rates_are_22050_and_24000():
    assert set(ALLOWED_SAMPLE_RATES) == {22050, 24000}
    assert EXPECTED_COMPTYPE == "NONE"


# --- single-chunk validation ---

def test_validate_wav_accepts_single_chunk_22050():
    _validate_wav(make_wav(SILENCE_PCM, framerate=22050))  # must not raise


def test_validate_wav_accepts_single_chunk_24000():
    _validate_wav(make_wav(b"\x00\x00" * 2400, framerate=24000))  # must not raise


# --- multi-chunk assembly, same native rate ---

def test_assemble_multi_chunk_22050():
    result = assemble_wav([WAV_A, WAV_B])
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 22050
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 2205 + 2205
        assert wf.readframes(wf.getnframes()) == PCM_A + PCM_B


def test_assemble_multi_chunk_24000():
    result = assemble_wav([WAV_24K_A, WAV_24K_B])
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getnframes() == 2400 + 2400
        assert wf.readframes(wf.getnframes()) == PCM_24K_A + PCM_24K_B


def test_assembled_wav_retains_24000_rate():
    """Assembled multi-chunk 24000 Hz audio must stay 24000 Hz, not relabelled."""
    result = assemble_wav([WAV_24K_A, WAV_24K_B])
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 24000
    # And the assembled output must itself pass validation at 24000 Hz.
    _validate_wav(result)


def test_single_chunk_24000_passthrough_preserves_rate():
    """A single 24000 Hz chunk is returned as-is and remains 24000 Hz."""
    result = assemble_wav([WAV_24K_A])
    assert result == WAV_24K_A
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 24000


# --- mixed-rate / mixed-format rejection ---

def test_assemble_rejects_mixed_sample_rates():
    """A 22050 chunk followed by a 24000 chunk must be rejected (no resample)."""
    try:
        assemble_wav([WAV_A, WAV_24K_A])
        assert False, "Should have raised TTSError for mixed sample rates"
    except TTSError as e:
        msg = str(e).lower()
        assert "mismatch" in msg or "22050" in str(e) or "24000" in str(e)


def test_assemble_rejects_mixed_rate_first_24000_then_22050():
    try:
        assemble_wav([WAV_24K_A, WAV_A])
        assert False, "Should have raised TTSError for mixed sample rates"
    except TTSError as e:
        assert "mismatch" in str(e).lower() or "Hz" in str(e)


def test_assemble_rejects_mixed_channels():
    """A mono first chunk and stereo later chunk must be rejected."""
    stereo = make_wav(b"\x00\x00\x00\x00" * 2205, nchannels=2)
    try:
        assemble_wav([WAV_A, stereo])
        assert False, "Should have raised TTSError"
    except TTSError:
        pass


# --- unsupported single-chunk rates and formats ---

def test_validate_wav_rejects_16000():
    try:
        _validate_wav(make_wav(SILENCE_PCM, framerate=16000))
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "16000" in str(e)


def test_validate_wav_rejects_44100_still():
    try:
        _validate_wav(make_wav(SILENCE_PCM, framerate=44100))
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "44100" in str(e)


def test_validate_wav_rejects_stereo_24000():
    bad = make_wav(b"\x00\x00\x00\x00" * 2400, nchannels=2, framerate=24000)
    try:
        _validate_wav(bad)
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "channel" in str(e).lower()


def test_validate_wav_rejects_non_16bit():
    """8-bit (1-byte) samples must be rejected even at an allowed rate."""
    bad = make_wav(b"\x00" * 2400, sampwidth=1, framerate=24000)
    try:
        _validate_wav(bad)
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "byte" in str(e).lower() or "sample" in str(e).lower()


def test_validate_wav_rejects_32bit():
    """32-bit (4-byte) samples must be rejected."""
    bad = make_wav(b"\x00\x00\x00\x00" * 2400, sampwidth=4, framerate=24000)
    try:
        _validate_wav(bad)
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "byte" in str(e).lower() or "sample" in str(e).lower()


def test_validate_wav_rejects_malformed_wav():
    try:
        _validate_wav(b"RIFF\x00\x00\x00\x00WAVEnot-a-real-wav")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "wav" in str(e).lower()


def test_validate_wav_rejects_zero_frame_24000():
    try:
        _validate_wav(make_wav(b"", framerate=24000))
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "zero" in str(e).lower()


def _make_mulaw_wav(framerate=24000, data_frames=200) -> bytes:
    """
    Build a minimal WAV whose fmt chunk declares µ-law (format code 7), i.e.
    a compressed/non-PCM stream. Python's `wave` cannot write this, so the
    bytes are assembled by hand. mono, 8-bit µ-law.
    """
    import struct
    audio_format = 7  # WAVE_FORMAT_MULAW (non-PCM)
    channels = 1
    bits_per_sample = 8
    byte_rate = framerate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data = b"\x7f" * data_frames
    fmt_chunk = struct.pack(
        "<HHIIHH", audio_format, channels, framerate, byte_rate, block_align, bits_per_sample
    )
    riff = (
        b"RIFF"
        + struct.pack("<I", 4 + (8 + len(fmt_chunk)) + (8 + len(data)))
        + b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt_chunk)) + fmt_chunk
        + b"data" + struct.pack("<I", len(data)) + data
    )
    return riff


def test_validate_wav_rejects_compressed():
    """A non-PCM (µ-law, format code 7) WAV must be rejected."""
    try:
        _validate_wav(_make_mulaw_wav())
        assert False, "Should have raised TTSError for compressed WAV"
    except TTSError as e:
        assert "compress" in str(e).lower() or "pcm" in str(e).lower() or "wav" in str(e).lower()


# --- end-to-end 24000 Hz synthesis + unchanged chunking/payload ---

@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_synthesize_kurdish_multi_chunk_24000(mock_urlopen, mock_key):
    """Long text at 24000 Hz produces a valid assembled 24000 Hz WAV."""
    mock_key.return_value = "test-key-123"
    call_count = [0]

    def side_effect(req, timeout=None):
        call_count[0] += 1
        resp = MagicMock()
        resp.status = 200
        resp.headers = {"Content-Type": "audio/wav"}
        resp.read.return_value = WAV_24K_A if call_count[0] % 2 == 1 else WAV_24K_B
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    mock_urlopen.side_effect = side_effect
    text = "Hevok yekem. " * 40  # > 480 chars -> multiple chunks
    result = synthesize_kurdish(text)
    assert call_count[0] >= 2
    with wave.open(io.BytesIO(result), "rb") as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_tts_request_payload_unchanged(mock_urlopen, mock_key):
    """The POST payload shape (text/speaker_id/model_version/format/speed) is unchanged."""
    mock_key.return_value = "test-key-123"
    captured = {}

    def side_effect(req, timeout=None):
        captured["data"] = req.data
        resp = MagicMock()
        resp.status = 200
        resp.headers = {"Content-Type": "audio/wav"}
        resp.read.return_value = WAV_24K_A
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    mock_urlopen.side_effect = side_effect
    synthesize_chunk("Rojbaş", "test-key-123", "kurmanji_236")
    import json as _json
    body = _json.loads(captured["data"].decode("utf-8"))
    assert body["text"] == "Rojbaş"
    assert body["speaker_id"] == "kurmanji_236"
    assert body["format"] == "wav"
    assert "model_version" in body
    assert "speed" in body


def test_chunking_behavior_unchanged():
    """Chunking boundaries are unaffected by the sample-rate change."""
    text = "Hevok yekem. " * 40
    chunks = chunk_text(text, max_chars=480)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 480


# ─── Quota refund caveat (documentation guard) ───────────────────────────────

def test_refund_does_not_prove_external_provider_uncounted():
    """
    DOCUMENTED CAVEAT: quota.refund() only rolls back the INTERNAL DynamoDB
    monthly counter. It does NOT prove the external KurdishTTS provider did not
    count the API call(s) against its own plan/billing. A synthesis that fails
    AFTER one or more chunk requests have already hit the provider may still
    have consumed provider-side credits even though the internal reservation
    was refunded to zero.

    This test documents that caveat and asserts the current refund semantics
    are intact; it deliberately does NOT redesign quota accounting, since no
    existing test shows the current internal behavior is unsafe to retain. If
    provider-side counting must be reconciled, that belongs in a separate,
    reviewed change to quota accounting.
    """
    import quota
    # Internal refund remains a no-op guard for non-positive values (unchanged).
    with patch("quota.boto3.resource") as mock_resource:
        quota.refund(0, "2026-10")
        mock_resource.assert_not_called()


# ─── Deadline-aware timeout recovery ─────────────────────────────────────────
# A hard Lambda timeout previously killed synthesis mid-run and left a dangling
# quota reservation. These tests prove the bounded, deadline-aware behavior:
# never begin an HTTP attempt (first try or retry) that cannot finish within
# remaining Lambda time + safety margin; on exhaustion exit through a controlled
# TTSTimeBudgetError that reports attempted vs. total; retain attempted chars and
# refund only unattempted chars; never write a partial WAV or audio_url_ku.

from kurdish_tts import (  # noqa: E402
    Deadline,
    TTSTimeBudgetError,
    synthesize_kurdish as _synthesize_kurdish,
    KURDISH_TTS_TIMEOUT,
    KURDISH_TTS_SAFETY_MARGIN,
)


class _FakeContext:
    """Mimics the Lambda context.

    Two modes:
      * scalar start_s -> every poll returns that many seconds (stable).
      * list of seconds -> each poll pops the next value; once exhausted, the
        final value repeats. Lets a test choose the exact reading per poll.

    The deadline is polled a deterministic number of times: synthesize_kurdish
    polls once per chunk (pre-chunk guard) and synthesize_chunk polls once per
    HTTP attempt (first try + each retry).
    """
    def __init__(self, start_s):
        if isinstance(start_s, (list, tuple)):
            self._seq = [float(v) for v in start_s]
        else:
            self._seq = [float(start_s)]

    def get_remaining_time_in_millis(self):
        val = self._seq.pop(0) if len(self._seq) > 1 else self._seq[0]
        return int(max(0.0, val) * 1000)


def test_deadline_none_is_unenforced():
    """A None context means unlimited time (direct/unit-test usage unchanged)."""
    d = Deadline(None)
    assert d.enforced is False
    assert d.remaining_s() is None
    assert d.fits(KURDISH_TTS_TIMEOUT) is True


def test_deadline_fits_requires_timeout_plus_margin():
    """fits() is True only when remaining >= http_timeout + safety margin."""
    need = KURDISH_TTS_TIMEOUT + KURDISH_TTS_SAFETY_MARGIN
    # Just enough (no decrement -> stable reading)
    d_ok = Deadline(_FakeContext(need))
    assert d_ok.fits(KURDISH_TTS_TIMEOUT) is True
    # One second short
    d_short = Deadline(_FakeContext(need - 1))
    assert d_short.fits(KURDISH_TTS_TIMEOUT) is False


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_insufficient_time_before_first_request_zero_calls_full_refund(mock_urlopen, mock_key):
    """No time for the first chunk -> zero provider calls, attempted_chars=0."""
    mock_key.return_value = "k"
    # Long text -> multiple chunks; context reports too little time from the start.
    text = "Hevok yekem. " * 40
    too_little = KURDISH_TTS_TIMEOUT + KURDISH_TTS_SAFETY_MARGIN - 1
    ctx = _FakeContext(too_little)  # stable, always below need
    try:
        _synthesize_kurdish(text, deadline=Deadline(ctx))
        assert False, "expected TTSTimeBudgetError"
    except TTSTimeBudgetError as e:
        assert e.attempted_chars == 0
        assert e.completed_chunks == 0
        assert e.total_chunks >= 2
    mock_urlopen.assert_not_called()  # zero provider calls


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_insufficient_time_after_some_chunks_retains_attempted(mock_urlopen, mock_key):
    """Time for 2 chunks then exhausted -> attempted = first 2 chunk sizes."""
    mock_key.return_value = "k"

    def ok_resp(req, timeout=None):
        resp = MagicMock()
        resp.status = 200
        resp.headers = {"Content-Type": "audio/wav"}
        resp.read.return_value = WAV_24K_A
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    mock_urlopen.side_effect = ok_resp
    text = "Hevok yekem. " * 120  # long enough for 3+ chunks at the 480 limit
    from kurdish_tts import chunk_text
    chunks = chunk_text(text)
    assert len(chunks) >= 3
    need = KURDISH_TTS_TIMEOUT + KURDISH_TTS_SAFETY_MARGIN
    # Poll order: c1 pre-guard, c1 attempt, c2 pre-guard, c2 attempt, c3 pre-guard.
    # Fit the first four polls, then starve chunk 3's pre-guard.
    ctx = _FakeContext([need + 100, need + 100, need + 100, need + 100, need - 1])
    try:
        _synthesize_kurdish(text, deadline=Deadline(ctx))
        assert False, "expected TTSTimeBudgetError"
    except TTSTimeBudgetError as e:
        assert e.completed_chunks == 2
        assert e.attempted_chars == len(chunks[0]) + len(chunks[1])
        assert e.total_chunks == len(chunks)
    # Exactly 2 provider calls were made (chunks 1 and 2).
    assert mock_urlopen.call_count == 2


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_remaining_time_checked_before_retry(mock_urlopen, mock_key):
    """A first attempt fails transiently; the retry is guarded by remaining time."""
    mock_key.return_value = "k"
    from urllib.error import URLError
    # First attempt raises a retryable URLError; the retry must be time-checked.
    mock_urlopen.side_effect = URLError("temporary connection reset")
    need = KURDISH_TTS_TIMEOUT + KURDISH_TTS_SAFETY_MARGIN
    # Attempt 1 guard fits; after the failure, attempt 2 guard does NOT fit.
    ctx = _FakeContext([need + 5, need - 1])
    try:
        synthesize_chunk("Rojbaş", "k", "kurmanji_236", deadline=Deadline(ctx))
        assert False, "expected TTSTimeBudgetError on retry guard"
    except TTSTimeBudgetError:
        pass
    # Only the first attempt hit the network; the retry was blocked by the guard.
    assert mock_urlopen.call_count == 1


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.urlopen")
def test_retry_not_attempted_when_timeout_plus_margin_cannot_fit(mock_urlopen, mock_key):
    """If no attempt can fit at all, zero network calls occur."""
    mock_key.return_value = "k"
    need = KURDISH_TTS_TIMEOUT + KURDISH_TTS_SAFETY_MARGIN
    ctx = _FakeContext(need - 1)  # first attempt already cannot fit (stable)
    try:
        synthesize_chunk("Rojbaş", "k", "kurmanji_236", deadline=Deadline(ctx))
        assert False, "expected TTSTimeBudgetError"
    except TTSTimeBudgetError:
        pass
    mock_urlopen.assert_not_called()


def test_batch_time_budget_exhausted_no_partial_wav_or_url_ku():
    """Batch handler: on time exhaustion, no S3 upload, no url_ku, partial refund."""
    from lambda_function import handle_kurdish_batch
    refunds = []

    def fake_refund(chars, month_key=None):
        refunds.append(chars)

    script = "Hevok yekem. " * 60  # multi-chunk
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve", return_value=True), \
         patch("quota.get_usage", return_value=0), \
         patch("quota.refund", side_effect=fake_refund), \
         patch.dict("sys.modules", {"kurdish_tts": __import__("kurdish_tts")}):
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": script, "daily_audio_meta": {},
        }
        import kurdish_tts
        total = len(kurdish_tts.chunk_text(script))
        # Deadline fits chunk 1 (pre-guard + attempt), then starves chunk 2's
        # pre-guard. Poll order: c1 pre-guard, c1 attempt, c2 pre-guard, ...
        need = kurdish_tts.KURDISH_TTS_TIMEOUT + kurdish_tts.KURDISH_TTS_SAFETY_MARGIN
        ctx = _FakeContext([need + 50, need + 50, need - 1])
        with patch("kurdish_tts.get_api_key", return_value="k"), \
             patch("kurdish_tts.urlopen") as mock_open:
            def ok(req, timeout=None):
                r = MagicMock(); r.status = 200; r.headers = {"Content-Type": "audio/wav"}
                r.read.return_value = WAV_24K_A
                r.__enter__ = lambda s: s; r.__exit__ = MagicMock(return_value=False)
                return r
            mock_open.side_effect = ok
            result = handle_kurdish_batch({
                "generate_kurdish_batch": True, "dry_run": False,
                "date": "2026-10-03", "max_chars": 18000,
                "request_id": "unit-timebudget",
            }, ctx)

    body = result["body"]
    today = [r for r in body["results"] if r["program_id"] == "today"][0]
    assert today["status"] == "time_budget_exhausted"
    assert today["attempted_chars"] >= 1
    assert today["refunded_chars"] == today["chars"] - today["attempted_chars"]
    assert today["refunded_chars"] >= 0
    # No partial WAV uploaded, no url_ku written.
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()
    # Only the unattempted remainder was refunded (never the full reservation here).
    assert refunds == [today["refunded_chars"]] if today["refunded_chars"] > 0 else refunds == []


def test_batch_full_refund_when_time_out_before_any_request():
    """If no provider request is ever submitted, the full reservation is refunded."""
    from lambda_function import handle_kurdish_batch
    refunds = []
    script = "Hevok yekem. " * 60
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve", return_value=True), \
         patch("quota.get_usage", return_value=0), \
         patch("quota.refund", side_effect=lambda chars, month_key=None: refunds.append(chars)):
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": script, "daily_audio_meta": {},
        }
        import kurdish_tts
        need = kurdish_tts.KURDISH_TTS_TIMEOUT + kurdish_tts.KURDISH_TTS_SAFETY_MARGIN
        ctx = _FakeContext(need - 1)  # never enough, from the first chunk (stable)
        with patch("kurdish_tts.get_api_key", return_value="k"), \
             patch("kurdish_tts.urlopen") as mock_open:
            result = handle_kurdish_batch({
                "generate_kurdish_batch": True, "dry_run": False,
                "date": "2026-10-03", "max_chars": 18000,
                "request_id": "unit-timebudget-full",
            }, ctx)
            mock_open.assert_not_called()  # zero provider calls

    today = [r for r in result["body"]["results"] if r["program_id"] == "today"][0]
    assert today["status"] == "time_budget_exhausted"
    assert today["attempted_chars"] == 0
    assert today["refunded_chars"] == today["chars"]
    assert refunds == [today["chars"]]
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()


def test_batch_success_retains_full_reservation():
    """A fully successful synthesis uploads WAV, writes url_ku, refunds nothing."""
    from lambda_function import handle_kurdish_batch
    refunds = []
    script = "Rojbaş. Ev Dengbêj e."  # single chunk
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve", return_value=True), \
         patch("quota.get_usage", return_value=0), \
         patch("quota.refund", side_effect=lambda chars, month_key=None: refunds.append(chars)):
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": script, "daily_audio_meta": {},
        }
        import kurdish_tts
        # Generous remaining time throughout.
        ctx = _FakeContext(600)
        with patch("kurdish_tts.get_api_key", return_value="k"), \
             patch("kurdish_tts.urlopen") as mock_open:
            def ok(req, timeout=None):
                r = MagicMock(); r.status = 200; r.headers = {"Content-Type": "audio/wav"}
                r.read.return_value = WAV_24K_A
                r.__enter__ = lambda s: s; r.__exit__ = MagicMock(return_value=False)
                return r
            mock_open.side_effect = ok
            result = handle_kurdish_batch({
                "generate_kurdish_batch": True, "dry_run": False,
                "date": "2026-10-03", "max_chars": 18000,
                "request_id": "unit-success",
            }, ctx)

    today = [r for r in result["body"]["results"] if r["program_id"] == "today"][0]
    assert today["status"] == "success"
    assert "audio_url_ku" in today
    assert refunds == []  # full reservation retained
    mock_s3.put_object.assert_called_once()
    mock_upd.assert_called_once()


def test_batch_dry_run_still_no_synthesis_or_writes_with_context():
    """Dry run performs zero synthesis/quota/S3/DB even when a context is passed."""
    from lambda_function import handle_kurdish_batch
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve") as mock_reserve, \
         patch("quota.refund") as mock_refund, \
         patch("quota.get_usage", return_value=0):
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": "Rojbaş. " * 50, "daily_audio_meta": {},
        }
        with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}) as _:
            ku = sys.modules["kurdish_tts"]
            ku.synthesize_kurdish = MagicMock()
            result = handle_kurdish_batch({
                "generate_kurdish_batch": True, "dry_run": True,
                "date": "2026-10-03", "max_chars": 5000,
            }, _FakeContext(600))
            ku.synthesize_kurdish.assert_not_called()
    assert result["body"]["status"] == "dry_run"
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()
    mock_reserve.assert_not_called()
    mock_refund.assert_not_called()


def test_direct_synthesize_without_context_unchanged():
    """Direct synthesize_kurdish with no deadline still works (back-compat)."""
    with patch("kurdish_tts.get_api_key", return_value="k"), \
         patch("kurdish_tts.urlopen") as mock_open:
        def ok(req, timeout=None):
            r = MagicMock(); r.status = 200; r.headers = {"Content-Type": "audio/wav"}
            r.read.return_value = FAKE_WAV
            r.__enter__ = lambda s: s; r.__exit__ = MagicMock(return_value=False)
            return r
        mock_open.side_effect = ok
        out = _synthesize_kurdish("Rojbaş")  # no deadline arg
    with wave.open(io.BytesIO(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() in (22050, 24000)


# ─── General failure accounting (all stages, conservative refunds) ───────────
# Extends the time-budget accounting to EVERY failure stage: retain characters
# already submitted to the provider, refund only never-submitted characters,
# refund at most once, and never publish a partial WAV or audio_url_ku.

from kurdish_tts import TTSPartialResultError  # noqa: E402
from urllib.error import URLError  # noqa: E402

# Mono 22050 Hz chunk WAV reused as a successful provider response.
_OK_WAV = make_wav(b"\x11\x00" * 1000, framerate=22050)


def _ok_resp_factory(wav_bytes):
    def _resp(req, timeout=None):
        r = MagicMock(); r.status = 200; r.headers = {"Content-Type": "audio/wav"}
        r.read.return_value = wav_bytes
        r.__enter__ = lambda s: s; r.__exit__ = MagicMock(return_value=False)
        return r
    return _resp


def _run_batch(script, urlopen_side_effect, *, s3_error=None, db_error=None,
               context=None, reserve=True):
    """Drive handle_kurdish_batch for a single 'today' program and capture refunds."""
    from lambda_function import handle_kurdish_batch
    refunds = []
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve", return_value=reserve), \
         patch("quota.get_usage", return_value=0), \
         patch("quota.refund", side_effect=lambda chars, month_key=None: refunds.append(chars)), \
         patch("kurdish_tts.get_api_key", return_value="k"), \
         patch("kurdish_tts.urlopen") as mock_open:
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": script, "daily_audio_meta": {},
        }
        mock_open.side_effect = urlopen_side_effect
        if s3_error is not None:
            mock_s3.put_object.side_effect = s3_error
        if db_error is not None:
            mock_upd.side_effect = db_error
        result = handle_kurdish_batch({
            "generate_kurdish_batch": True, "dry_run": False,
            "date": "2026-10-03", "max_chars": 18000, "request_id": "unit-gen-acct",
        }, context)
    today = [r for r in result["body"]["results"] if r["program_id"] == "today"][0]
    return today, refunds, mock_s3, mock_upd


# --- synthesize_kurdish level: stage classification + attempted accounting ---

@patch("kurdish_tts.get_api_key", return_value="k")
@patch("kurdish_tts.urlopen")
def test_first_chunk_network_failure_retains_that_chunk(mock_open, _key):
    """A network failure on chunk 1 retains chunk-1 chars (request was submitted)."""
    mock_open.side_effect = URLError("connection reset")  # all attempts fail
    from kurdish_tts import chunk_text
    script = "Hevok yekem. " * 120  # multi-chunk
    chunks = chunk_text(script)
    try:
        _synthesize_kurdish(script)
        assert False, "expected TTSPartialResultError"
    except TTSTimeBudgetError:
        assert False, "network failure must not be a time-budget error"
    except TTSPartialResultError as e:
        assert e.stage == "chunk_request"
        assert e.completed_chunks == 0
        assert e.attempted_chars == len(chunks[0])  # chunk 1 submitted
        assert e.total_chunks == len(chunks)


@patch("kurdish_tts.get_api_key", return_value="k")
@patch("kurdish_tts.urlopen")
def test_later_chunk_network_failure_retains_earlier_and_current(mock_open, _key):
    """Chunk 1 OK, chunk 2 network-fails -> attempted = chunk1 + chunk2."""
    from kurdish_tts import chunk_text
    script = "Hevok yekem. " * 120
    chunks = chunk_text(script)
    calls = {"n": 0}

    def side_effect(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _ok_resp_factory(_OK_WAV)(req, timeout)
        raise URLError("drop on chunk 2")

    mock_open.side_effect = side_effect
    try:
        _synthesize_kurdish(script)
        assert False, "expected TTSPartialResultError"
    except TTSPartialResultError as e:
        assert not isinstance(e, TTSTimeBudgetError)
        assert e.stage == "chunk_request"
        assert e.completed_chunks == 1
        assert e.attempted_chars == len(chunks[0]) + len(chunks[1])


@patch("kurdish_tts.get_api_key", return_value="k")
@patch("kurdish_tts.urlopen")
def test_malformed_provider_wav_after_submit_is_validation_stage(mock_open, _key):
    """A parseable-but-invalid WAV response (request received) -> wav_validation
    stage, retained. The provider returned a well-formed WAV container at an
    UNSUPPORTED sample rate, so it fails _validate_wav inside synthesize_chunk
    (message contains "WAV"), not the min-size guard."""
    bad = make_wav(b"\x01\x00" * 1000, framerate=8000)  # unsupported rate, >=100 bytes
    mock_open.side_effect = _ok_resp_factory(bad)
    from kurdish_tts import chunk_text
    script = "Hevok yekem. " * 120
    chunks = chunk_text(script)
    try:
        _synthesize_kurdish(script)
        assert False, "expected TTSPartialResultError"
    except TTSPartialResultError as e:
        assert e.stage == "wav_validation"
        assert e.completed_chunks == 0
        assert e.attempted_chars == len(chunks[0])


@patch("kurdish_tts.get_api_key", return_value="k")
@patch("kurdish_tts.urlopen")
def test_mixed_sample_rate_assembly_failure_retains_all_submitted(mock_open, _key):
    """All chunks succeed individually but differ in rate -> assembly stage, retain all."""
    from kurdish_tts import chunk_text
    script = "Hevok yekem. " * 120
    chunks = chunk_text(script)
    wav_22k = make_wav(b"\x01\x00" * 1000, framerate=22050)
    wav_24k = make_wav(b"\x02\x00" * 1000, framerate=24000)
    calls = {"n": 0}

    def side_effect(req, timeout=None):
        calls["n"] += 1
        return _ok_resp_factory(wav_22k if calls["n"] == 1 else wav_24k)(req, timeout)

    mock_open.side_effect = side_effect
    try:
        _synthesize_kurdish(script)
        assert False, "expected TTSPartialResultError"
    except TTSPartialResultError as e:
        assert e.stage == "assembly"
        assert e.completed_chunks == e.total_chunks == len(chunks)
        assert e.attempted_chars == sum(len(c) for c in chunks)


# --- batch handler level: refunds, stages, s3 flags, single-refund ---

def test_batch_failure_before_first_request_full_refund():
    """Reservation confirmed but no provider request possible -> full refund.

    Here the API key lookup fails inside synthesis before any HTTP call; the
    handler cannot know any request succeeded, so it refunds the full amount.
    """
    from lambda_function import handle_kurdish_batch
    refunds = []
    script = "Hevok yekem. " * 60
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve", return_value=True), \
         patch("quota.get_usage", return_value=0), \
         patch("quota.refund", side_effect=lambda chars, month_key=None: refunds.append(chars)), \
         patch("kurdish_tts.get_api_key", side_effect=TTSError("secret unavailable")), \
         patch("kurdish_tts.urlopen") as mock_open:
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": script, "daily_audio_meta": {},
        }
        result = handle_kurdish_batch({
            "generate_kurdish_batch": True, "dry_run": False,
            "date": "2026-10-03", "max_chars": 18000, "request_id": "unit",
        }, None)
        mock_open.assert_not_called()
    today = [r for r in result["body"]["results"] if r["program_id"] == "today"][0]
    assert today["status"] == "failed_partial"
    assert today["stage"] == "chunk_request" or today["attempted_chars"] == 0
    assert today["attempted_chars"] == 0
    assert today["refunded_chars"] == today["chars"]
    assert refunds == [today["chars"]]
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()


def test_batch_later_chunk_network_failure_partial_refund_no_publish():
    from kurdish_tts import chunk_text
    script = "Hevok yekem. " * 120
    chunks = chunk_text(script)
    calls = {"n": 0}

    def side_effect(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _ok_resp_factory(_OK_WAV)(req, timeout)
        raise URLError("drop later chunk")

    today, refunds, mock_s3, mock_upd = _run_batch(script, side_effect)
    assert today["status"] == "failed_partial"
    assert today["stage"] == "chunk_request"
    assert today["attempted_chars"] == len(chunks[0]) + len(chunks[1])
    assert today["refunded_chars"] == today["chars"] - today["attempted_chars"]
    assert today["s3_object_created"] is False
    assert refunds == [today["refunded_chars"]]  # single refund
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()


def test_batch_s3_upload_failure_retains_full_refund_zero():
    script = "Rojbaş. Ev Dengbêj e."  # single chunk, synthesis succeeds
    today, refunds, mock_s3, mock_upd = _run_batch(
        script, _ok_resp_factory(_OK_WAV), s3_error=Exception("S3 down"))
    assert today["status"] == "failed_upload"
    assert today["stage"] == "s3_upload"
    assert today["attempted_chars"] == today["chars"]
    assert today["refunded_chars"] == 0
    assert today["s3_object_created"] is False
    assert refunds == []  # nothing refunded
    mock_upd.assert_not_called()  # no DB write, no url_ku


def test_batch_db_update_failure_retains_full_reports_s3_object():
    script = "Rojbaş. Ev Dengbêj e."  # single chunk
    today, refunds, mock_s3, mock_upd = _run_batch(
        script, _ok_resp_factory(_OK_WAV), db_error=Exception("DDB throttled"))
    assert today["status"] == "failed_db_update"
    assert today["stage"] == "dynamodb_update"
    assert today["attempted_chars"] == today["chars"]
    assert today["refunded_chars"] == 0
    assert today["s3_object_created"] is True
    assert "s3_key" in today and today["s3_key"].startswith("daily/2026-10-03_ku_")
    assert refunds == []  # retain full reservation
    mock_s3.put_object.assert_called_once()  # upload did happen


def test_batch_success_retains_full_no_refund():
    script = "Rojbaş. Ev Dengbêj e."
    today, refunds, mock_s3, mock_upd = _run_batch(script, _ok_resp_factory(_OK_WAV))
    assert today["status"] == "success"
    assert "audio_url_ku" in today
    assert refunds == []
    mock_s3.put_object.assert_called_once()
    mock_upd.assert_called_once()


def test_batch_deadline_behavior_still_partial_refund():
    """Deadline exhaustion still yields time_budget_exhausted with partial refund."""
    import kurdish_tts
    script = "Hevok yekem. " * 120
    need = kurdish_tts.KURDISH_TTS_TIMEOUT + kurdish_tts.KURDISH_TTS_SAFETY_MARGIN
    # Fit chunk 1 (pre-guard + attempt), then starve chunk 2 pre-guard.
    ctx = _FakeContext([need + 50, need + 50, need - 1])
    today, refunds, mock_s3, mock_upd = _run_batch(
        script, _ok_resp_factory(_OK_WAV), context=ctx)
    assert today["status"] == "time_budget_exhausted"
    assert today["stage"] == "time_budget"
    assert today["refunded_chars"] == today["chars"] - today["attempted_chars"]
    assert today["s3_object_created"] is False
    assert refunds == [today["refunded_chars"]]  # single refund
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()


def test_batch_no_double_refund_on_any_stage():
    """Across stages, quota.refund is called at most once per program."""
    from kurdish_tts import chunk_text
    script = "Hevok yekem. " * 120
    calls = {"n": 0}

    def side_effect(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _ok_resp_factory(_OK_WAV)(req, timeout)
        raise URLError("drop")

    today, refunds, _, _ = _run_batch(script, side_effect)
    assert len(refunds) == 1  # exactly one refund call


def test_batch_dry_run_zero_side_effects_general():
    """Dry run with a context still performs zero synthesis/quota/S3/DB."""
    from lambda_function import handle_kurdish_batch
    with patch("lambda_function._get_briefing_for_batch") as mock_brief, \
         patch("lambda_function._get_program_for_batch", return_value=None), \
         patch("lambda_function.s3_client") as mock_s3, \
         patch("lambda_function._update_briefing_ku_audio") as mock_upd, \
         patch("quota.reserve") as mock_reserve, \
         patch("quota.refund") as mock_refund, \
         patch("quota.get_usage", return_value=0):
        mock_brief.return_value = {
            "briefing_date": "2026-10-03", "generated_at": "T",
            "daily_audio_script_ku": "Rojbaş. " * 50, "daily_audio_meta": {},
        }
        with patch.dict("sys.modules", {"kurdish_tts": MagicMock()}):
            sys.modules["kurdish_tts"].synthesize_kurdish = MagicMock()
            result = handle_kurdish_batch({
                "generate_kurdish_batch": True, "dry_run": True,
                "date": "2026-10-03", "max_chars": 5000,
            }, _FakeContext(600))
            sys.modules["kurdish_tts"].synthesize_kurdish.assert_not_called()
    assert result["body"]["status"] == "dry_run"
    mock_s3.put_object.assert_not_called()
    mock_upd.assert_not_called()
    mock_reserve.assert_not_called()
    mock_refund.assert_not_called()
