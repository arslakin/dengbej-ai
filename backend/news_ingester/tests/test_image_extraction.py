"""
Unit tests for RSS image extraction in the News Ingester.

Tests cover:
- Priority chain: media:content > media:thumbnail > enclosure > null
- URL validation: http/https only, max 2048 chars
- Edge cases: video-only media, relative URLs, missing fields
- Feed-specific behavior: BBC (media_thumbnail), DW (no images), AJ (no images)
- No HTTP fetches or S3 uploads
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lambda_function import extract_source_image_url, _is_valid_image_url


# ─── Test: Priority 1 — media:content with medium="image" ───────────────────

def test_media_content_image_medium():
    """media:content with medium='image' should be extracted."""
    entry = {
        "media_content": [
            {"url": "https://cdn.example.com/photo.jpg", "medium": "image"}
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/photo.jpg"


def test_media_content_no_medium_attribute():
    """media:content with no medium attribute should be treated as image."""
    entry = {
        "media_content": [
            {"url": "https://cdn.example.com/photo.jpg"}
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/photo.jpg"


def test_media_content_video_only_falls_through():
    """media:content with medium='video' should NOT be extracted; fall through."""
    entry = {
        "media_content": [
            {"url": "https://cdn.example.com/video.mp4", "medium": "video"}
        ],
        "media_thumbnail": [
            {"url": "https://cdn.example.com/thumb.jpg"}
        ]
    }
    # Should fall through to media_thumbnail
    assert extract_source_image_url(entry) == "https://cdn.example.com/thumb.jpg"


def test_media_content_takes_priority_over_thumbnail():
    """media:content (image) takes priority over media:thumbnail."""
    entry = {
        "media_content": [
            {"url": "https://cdn.example.com/full.jpg", "medium": "image"}
        ],
        "media_thumbnail": [
            {"url": "https://cdn.example.com/thumb.jpg"}
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/full.jpg"


# ─── Test: Priority 2 — media:thumbnail ─────────────────────────────────────

def test_media_thumbnail_extracted():
    """media:thumbnail URL should be extracted when no media:content image."""
    entry = {
        "media_thumbnail": [
            {"url": "https://ichef.bbci.co.uk/news/240/photo.jpg", "width": "240", "height": "134"}
        ]
    }
    assert extract_source_image_url(entry) == "https://ichef.bbci.co.uk/news/240/photo.jpg"


def test_media_thumbnail_bbc_format():
    """BBC-style media_thumbnail should be correctly extracted."""
    entry = {
        "media_thumbnail": [
            {"width": "240", "height": "134", "url": "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/abc123.jpg"}
        ]
    }
    result = extract_source_image_url(entry)
    assert result == "https://ichef.bbci.co.uk/ace/standard/240/cpsprodpb/abc123.jpg"


# ─── Test: Priority 3 — enclosure with image type ───────────────────────────

def test_enclosure_image_type():
    """Enclosure with image MIME type should be extracted."""
    entry = {
        "enclosures": [
            {"href": "https://media.example.com/photo.jpg", "type": "image/jpeg"}
        ]
    }
    assert extract_source_image_url(entry) == "https://media.example.com/photo.jpg"


def test_enclosure_url_field():
    """Enclosure using 'url' field instead of 'href' should work."""
    entry = {
        "enclosures": [
            {"url": "https://media.example.com/photo.png", "type": "image/png"}
        ]
    }
    assert extract_source_image_url(entry) == "https://media.example.com/photo.png"


def test_enclosure_non_image_skipped():
    """Enclosure with non-image type should be skipped."""
    entry = {
        "enclosures": [
            {"href": "https://media.example.com/audio.mp3", "type": "audio/mpeg"}
        ]
    }
    assert extract_source_image_url(entry) is None


def test_thumbnail_takes_priority_over_enclosure():
    """media:thumbnail takes priority over enclosure."""
    entry = {
        "media_thumbnail": [
            {"url": "https://cdn.example.com/thumb.jpg"}
        ],
        "enclosures": [
            {"href": "https://cdn.example.com/enclosure.jpg", "type": "image/jpeg"}
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/thumb.jpg"


# ─── Test: No image available → null ────────────────────────────────────────

def test_no_media_fields_returns_none():
    """Entry with no media fields should return None."""
    entry = {"title": "Test headline", "link": "https://example.com/article"}
    assert extract_source_image_url(entry) is None


def test_empty_entry_returns_none():
    """Completely empty entry should return None."""
    entry = {}
    assert extract_source_image_url(entry) is None


def test_dw_style_no_images():
    """DW entries have no image fields — should return None."""
    entry = {
        "title": "Germany announces new policy",
        "link": "https://dw.com/article",
        "summary": "Description text",
        "tags": [{"term": "politics"}],
    }
    assert extract_source_image_url(entry) is None


# ─── Test: URL Validation ────────────────────────────────────────────────────

def test_valid_https_url():
    """HTTPS URL should be valid."""
    assert _is_valid_image_url("https://cdn.example.com/img.jpg") is True


def test_valid_http_url():
    """HTTP URL should be valid."""
    assert _is_valid_image_url("http://cdn.example.com/img.jpg") is True


def test_relative_url_invalid():
    """Relative URL should be invalid."""
    assert _is_valid_image_url("/images/photo.jpg") is False


def test_empty_url_invalid():
    """Empty string should be invalid."""
    assert _is_valid_image_url("") is False


def test_none_url_invalid():
    """None should be invalid."""
    assert _is_valid_image_url(None) is False


def test_ftp_url_invalid():
    """FTP URL should be invalid."""
    assert _is_valid_image_url("ftp://cdn.example.com/img.jpg") is False


def test_oversized_url_invalid():
    """URL exceeding 2048 chars should be invalid."""
    long_url = "https://cdn.example.com/" + "a" * 2040
    assert _is_valid_image_url(long_url) is False


def test_url_at_2048_limit_valid():
    """URL at exactly 2048 chars should be valid."""
    url = "https://cdn.example.com/" + "a" * (2048 - len("https://cdn.example.com/"))
    assert len(url) == 2048
    assert _is_valid_image_url(url) is True


# ─── Test: Edge Cases ────────────────────────────────────────────────────────

def test_media_content_invalid_url_falls_through():
    """media:content with invalid URL should fall through to thumbnail."""
    entry = {
        "media_content": [
            {"url": "/relative/path.jpg", "medium": "image"}
        ],
        "media_thumbnail": [
            {"url": "https://cdn.example.com/fallback.jpg"}
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/fallback.jpg"


def test_whitespace_url_stripped():
    """URLs with leading/trailing whitespace should be stripped."""
    entry = {
        "media_thumbnail": [
            {"url": "  https://cdn.example.com/photo.jpg  "}
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/photo.jpg"


def test_multiple_media_content_first_image_wins():
    """First qualifying media:content element should win."""
    entry = {
        "media_content": [
            {"url": "https://cdn.example.com/video.mp4", "medium": "video"},
            {"url": "https://cdn.example.com/photo1.jpg", "medium": "image"},
            {"url": "https://cdn.example.com/photo2.jpg", "medium": "image"},
        ]
    }
    assert extract_source_image_url(entry) == "https://cdn.example.com/photo1.jpg"


# ─── Run Tests ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_functions = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0

    for test_fn in test_functions:
        try:
            test_fn()
            print(f"  ✅ {test_fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {test_fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ {test_fn.__name__}: EXCEPTION: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
    if failed > 0:
        sys.exit(1)
