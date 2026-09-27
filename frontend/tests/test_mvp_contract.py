"""Offline contract coverage for the news API and bilingual audio selection."""

import importlib.util
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
INDEX_HTML = ROOT / "frontend" / "index.html"
NEWS_API = ROOT / "backend" / "news_api" / "lambda_function.py"
NODE = subprocess.run(["which", "node"], capture_output=True, text=True).stdout.strip()


def _load_news_api():
    spec = importlib.util.spec_from_file_location("mvp_contract_news_api", NEWS_API)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _api_fixture():
    return {
        "briefing_date": "2026-01-15",
        "generated_at": "2026-01-15T10:00:00Z",
        "stories": [
            {
                "rank": 1,
                "headline": "English headline",
                "headline_ku": "Sernavê Kurdî",
                "category": "world",
                "processing_status": "processed",
                "summary_en": "English summary.",
                "summary_ku": "Kurteya Kurdî.",
                "primary_source": "BBC News",
                "original_url": "https://example.com/story",
                "pub_date": "2026-01-15T08:00:00Z",
                "processed_at": "2026-01-15T09:30:00Z",
                "supporting_sources": [],
            }
        ],
        "daily_audio_meta": {
            "audio_url": "https://audio.example/english.mp3",
            "audio_url_en": "https://audio.example/english.mp3",
            "audio_url_ku": "https://audio.example/kurdish.wav",
        },
    }


def _news_api_response():
    module = _load_news_api()
    event = {
        "rawPath": "/news/today",
        "requestContext": {"http": {"method": "GET", "path": "/news/today"}},
    }
    fixed_now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    with patch.object(module, "briefings_table") as table, patch.object(module, "datetime") as clock:
        table.query.return_value = {"Items": [_api_fixture()]}
        clock.now.return_value = fixed_now
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 200
    return json.loads(response["body"])


def _run_frontend_helper(function_name, function_pattern, args):
    if not NODE:
        pytest.skip("node is not available")

    html = INDEX_HTML.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    match = re.search(function_pattern, script, re.DOTALL)
    assert match, f"{function_name} was not found"
    function = match.group(0)
    harness = (
        'var currentLang = "'
        + args["lang"]
        + '";\n'
        + function
        + "\nconsole.log(JSON.stringify("
        + args["expression"]
        + "));\n"
    )
    result = subprocess.run(
        [NODE, "-e", harness], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip())


def test_news_api_output_and_frontend_language_audio_contract():
    """The API fixture drives Kurdish, English, fallback, and missing-audio states."""
    body = _news_api_response()
    story = body["stories"][0]
    audio = body["daily_audio"]

    assert story["headline"] == "English headline"
    assert story["headline_ku"] == "Sernavê Kurdî"
    assert story["summary_en"] == "English summary."
    assert story["summary_ku"] == "Kurteya Kurdî."
    assert audio["url_ku"] == "https://audio.example/kurdish.wav"
    assert audio["url_en"] == "https://audio.example/english.mp3"

    frontend_script = INDEX_HTML.read_text(encoding="utf-8")
    assert "story.headline_ku || story.headline" in frontend_script
    assert "story.summary_ku || story.summary_en" in frontend_script

    audio_meta = json.dumps(audio)
    assert _run_frontend_helper(
        "selectAudioUrl",
        r"function selectAudioUrl\(audioMeta\) \{.*?\n      \}",
        {"lang": "ku", "expression": f"selectAudioUrl({audio_meta})"},
    ) == audio["url_ku"]
    assert _run_frontend_helper(
        "selectAudioUrl",
        r"function selectAudioUrl\(audioMeta\) \{.*?\n      \}",
        {"lang": "en", "expression": f"selectAudioUrl({audio_meta})"},
    ) == audio["url_en"]

    fallback_meta = json.dumps({**audio, "url_ku": None})
    assert _run_frontend_helper(
        "selectAudioUrl",
        r"function selectAudioUrl\(audioMeta\) \{.*?\n      \}",
        {"lang": "ku", "expression": f"selectAudioUrl({fallback_meta})"},
    ) == audio["url_en"]

    missing_meta = json.dumps({"url": None, "url_en": None, "url_ku": None})
    assert _run_frontend_helper(
        "selectAudioUrl",
        r"function selectAudioUrl\(audioMeta\) \{.*?\n      \}",
        {"lang": "ku", "expression": f"selectAudioUrl({missing_meta})"},
    ) is None
    assert _run_frontend_helper(
        "audioStatusText",
        r"function audioStatusText\(isKurdish, hasAudio\) \{.*?\n      \}",
        {"lang": "ku", "expression": "audioStatusText(false, false)"},
    ) == "Deng — zû tê"
    assert _run_frontend_helper(
        "audioStatusText",
        r"function audioStatusText\(isKurdish, hasAudio\) \{.*?\n      \}",
        {"lang": "en", "expression": "audioStatusText(false, false)"},
    ) == "Audio — coming soon"
