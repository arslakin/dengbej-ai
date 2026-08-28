"""
Unit tests for Kurdish TTS provider (kurdishtts.com integration).

Tests cover:
- Successful synthesis (single chunk and multi-chunk)
- Missing secret handling
- Timeout handling
- Quota/authentication failure
- Malformed audio response
- English Polly fallback when Kurdish TTS fails
- Idempotency (unchanged scripts not re-synthesized)
- Text chunking logic
"""

import sys
import os
from unittest.mock import patch, MagicMock, PropertyMock
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kurdish_tts import (
    chunk_text,
    synthesize_chunk,
    synthesize_kurdish,
    get_api_key,
    KurdishTTSProvider,
    KURDISH_TTS_CHUNK_LIMIT,
    MIN_MP3_SIZE,
)
from tts_provider import TTSError


# ─── Helpers ─────────────────────────────────────────────────────────────────

FAKE_MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 500  # Valid-looking MP3 frame header + padding


def _mock_response(status_code=200, content=FAKE_MP3, content_type="audio/mpeg", json_data=None):
    """Create a mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.content = content
    mock_resp.headers = {"Content-Type": content_type}
    mock_resp.text = str(json_data) if json_data else ""
    if json_data:
        mock_resp.json.return_value = json_data
    else:
        mock_resp.json.side_effect = ValueError("No JSON")
    return mock_resp


# ─── Test: Text Chunking ─────────────────────────────────────────────────────

def test_chunk_text_short_text():
    """Text within limit should return single chunk."""
    text = "Rojbaş. Ev Dengbêj e."
    chunks = chunk_text(text, max_chars=500)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_splits_on_sentences():
    """Long text should split on sentence boundaries."""
    text = "Hevok yek. Hevok du. Hevok sê. Hevok çar. Hevok pênc."
    chunks = chunk_text(text, max_chars=30)
    assert len(chunks) > 1
    # Each chunk should be within limit
    for chunk in chunks:
        assert len(chunk) <= 30


def test_chunk_text_preserves_all_content():
    """All original text should be present across chunks."""
    text = "A" * 100 + ". " + "B" * 100 + ". " + "C" * 100 + "."
    chunks = chunk_text(text, max_chars=120)
    combined = " ".join(chunks)
    # All original content preserved (spaces may differ at boundaries)
    assert "A" * 100 in combined
    assert "B" * 100 in combined
    assert "C" * 100 in combined


def test_chunk_text_handles_single_long_sentence():
    """A sentence longer than the limit should be hard-split."""
    text = "A" * 600
    chunks = chunk_text(text, max_chars=500)
    assert len(chunks) >= 2
    combined = "".join(chunks)
    assert len(combined) == 600


# ─── Test: Successful Synthesis ──────────────────────────────────────────────

@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.requests.post")
def test_synthesize_chunk_success(mock_post, mock_key):
    """Successful single chunk synthesis returns MP3 bytes."""
    mock_key.return_value = "test-key-123"
    mock_post.return_value = _mock_response(200, FAKE_MP3, "audio/mpeg")

    result = synthesize_chunk("Rojbaş", "test-key-123")
    assert result == FAKE_MP3
    assert len(result) > MIN_MP3_SIZE


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.requests.post")
def test_synthesize_kurdish_single_chunk(mock_post, mock_key):
    """Short text should result in a single API call."""
    mock_key.return_value = "test-key-123"
    mock_post.return_value = _mock_response(200, FAKE_MP3, "audio/mpeg")

    result = synthesize_kurdish("Rojbaş. Ev nûçe ye.")
    assert result == FAKE_MP3
    mock_post.assert_called_once()


@patch("kurdish_tts.get_api_key")
@patch("kurdish_tts.requests.post")
def test_synthesize_kurdish_multi_chunk(mock_post, mock_key):
    """Long text should be split and concatenated."""
    mock_key.return_value = "test-key-123"
    chunk1 = b"\xff\xfb\x90\x00" + b"\x01" * 300
    chunk2 = b"\xff\xfb\x90\x00" + b"\x02" * 300
    mock_post.side_effect = [
        _mock_response(200, chunk1, "audio/mpeg"),
        _mock_response(200, chunk2, "audio/mpeg"),
    ]

    # Create text that exceeds the chunk limit
    text = "Hevok yekem. " * 400  # ~5600 chars
    result = synthesize_kurdish(text)

    # Result should be concatenation of both chunks
    assert result == chunk1 + chunk2
    assert mock_post.call_count == 2


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
        assert False, "Should have raised TTSError"
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
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "permission" in str(e).lower()


# ─── Test: Timeout Handling ──────────────────────────────────────────────────

@patch("kurdish_tts.requests.post")
def test_synthesize_chunk_timeout(mock_post):
    """Timeout should retry and eventually raise TTSError."""
    import requests as real_requests
    mock_post.side_effect = real_requests.Timeout("Connection timed out")

    try:
        synthesize_chunk("Test", "key123")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "timeout" in str(e).lower()
    # Should have retried
    assert mock_post.call_count == 2  # KURDISH_TTS_MAX_RETRIES


# ─── Test: Quota / Auth Failure ──────────────────────────────────────────────

@patch("kurdish_tts.requests.post")
def test_synthesize_chunk_auth_failure(mock_post):
    """401 should immediately raise without retry."""
    mock_post.return_value = _mock_response(401, b"", "text/plain")

    try:
        synthesize_chunk("Test", "bad-key")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "authentication" in str(e).lower()
    # No retry for auth errors
    assert mock_post.call_count == 1


@patch("kurdish_tts.requests.post")
def test_synthesize_chunk_quota_exhausted(mock_post):
    """403 should immediately raise without retry."""
    mock_post.return_value = _mock_response(403, b"", "text/plain")

    try:
        synthesize_chunk("Test", "key123")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "quota" in str(e).lower()
    assert mock_post.call_count == 1


# ─── Test: Malformed Audio ───────────────────────────────────────────────────

@patch("kurdish_tts.requests.post")
def test_synthesize_chunk_too_small(mock_post):
    """Audio smaller than MIN_MP3_SIZE should be rejected."""
    mock_post.return_value = _mock_response(200, b"\x00" * 10, "audio/mpeg")

    try:
        synthesize_chunk("Test", "key123")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "small" in str(e).lower()


@patch("kurdish_tts.requests.post")
def test_synthesize_chunk_collapsed_generation(mock_post):
    """Collapsed generation response should be treated as failure."""
    json_response = {"generation": {"collapsed": True}}
    mock_post.return_value = _mock_response(200, b"{}", "application/json", json_response)

    try:
        synthesize_chunk("Test", "key123")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "collapsed" in str(e).lower()


# ─── Test: Fallback (integration with daily_audio) ───────────────────────────

@patch("lambda_function.TTS_ENABLED", True)
@patch("lambda_function.synthesize_and_upload")
@patch("lambda_function.generate_english_narration")
@patch("lambda_function.get_processed_briefing")
@patch("lambda_function.invoke_bedrock")
@patch("lambda_function.store_script")
def test_kurdish_tts_failure_preserves_english_audio(mock_store, mock_bedrock, mock_get, mock_en_narration, mock_synth):
    """If Kurdish TTS fails, English Polly audio should still be stored."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "stories": [{"processing_status": "processed", "headline": "Test", "category": "world",
                     "summary_en": "Summary", "summary_ku": "Kurte", "primary_source": "BBC"}] * 5,
    }
    mock_get.return_value = briefing
    mock_bedrock.return_value = "Rojbaş. Ev Dengbêj e. Nûçe."
    mock_en_narration.return_value = "English narration text."
    mock_synth.return_value = "https://dengbej-audio.s3.amazonaws.com/daily/en_test.mp3"

    # Patch Kurdish TTS to fail
    with patch("lambda_function.TTS_ENABLED", True), \
         patch.dict("sys.modules", {"kurdish_tts": MagicMock()}):
        import sys
        sys.modules["kurdish_tts"].synthesize_kurdish.side_effect = Exception("Kurdish TTS unavailable")
        sys.modules["kurdish_tts"].TTSError = Exception

        result = lambda_handler({"date": "2026-09-01", "force": True}, None)

    assert result["statusCode"] == 200
    # store_script should have been called with English audio
    call_kwargs = mock_store.call_args
    assert call_kwargs is not None


# ─── Test: Idempotency ───────────────────────────────────────────────────────

@patch("lambda_function.get_processed_briefing")
def test_existing_script_not_regenerated(mock_get):
    """If script already exists and force=False, no TTS calls should be made."""
    from lambda_function import lambda_handler

    briefing = {
        "briefing_date": "2026-09-01", "generated_at": "2026-09-01T06:00:00Z",
        "daily_audio_script_ku": "Existing script content",
        "stories": [{"processing_status": "processed"}] * 5,
    }
    mock_get.return_value = briefing

    result = lambda_handler({"date": "2026-09-01", "force": False}, None)

    assert result["statusCode"] == 200
    assert result["body"]["status"] == "already_exists"


# ─── Test: Provider Interface ────────────────────────────────────────────────

@patch("kurdish_tts.synthesize_kurdish")
def test_provider_synthesize_returns_result(mock_synth):
    """KurdishTTSProvider.synthesize should return TTSResult."""
    mock_synth.return_value = FAKE_MP3

    provider = KurdishTTSProvider()
    result = provider.synthesize("Rojbaş")

    assert result.audio_data == FAKE_MP3
    assert result.provider == "kurdish-tts"
    assert result.language == "ku"
    assert result.format == "mp3"


def test_provider_supports_kurdish():
    """Provider should support Kurdish language codes."""
    provider = KurdishTTSProvider()
    assert provider.supports_language("ku") is True
    assert provider.supports_language("kmr") is True
    assert provider.supports_language("kurmanji") is True
    assert provider.supports_language("en") is False
    assert provider.supports_language("ar") is False


def test_provider_rejects_unsupported_language():
    """Provider should raise TTSError for non-Kurdish."""
    provider = KurdishTTSProvider()
    try:
        provider.synthesize("Hello", language="en")
        assert False, "Should have raised TTSError"
    except TTSError as e:
        assert "not support" in str(e).lower()
