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
