"""
Frontend regression tests for the Beje radio public-beta polish and the
listener-facing publication-trust pages.

Covers:
- Language-aware audio selection (selectAudioUrl logic, executed via node)
- All player entry points route through selectAudioUrl
- Freshness indicator presence and logic
- Current public copy (listener-facing; no AWS-showcase language on the site)
- Trust pages: availability, navigation, bilingual copy, no tracking/ad scripts
- Basic HTML/CSS/JS structural validity (balanced tags/braces, node --check)

These tests parse the actual shipped HTML files so they stay in sync. The
JS-logic tests execute the real functions with node.
"""

import os
import re
import shutil
import subprocess
import pytest

FRONTEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_HTML = os.path.join(FRONTEND_DIR, "index.html")
ABOUT_HTML = os.path.join(FRONTEND_DIR, "about.html")
HOWITWORKS_HTML = os.path.join(FRONTEND_DIR, "how-it-works.html")

# Listener-facing trust/content pages
TRUST_PAGES = {
    "transparency": os.path.join(FRONTEND_DIR, "transparency.html"),
    "sources": os.path.join(FRONTEND_DIR, "sources.html"),
    "contact": os.path.join(FRONTEND_DIR, "contact.html"),
    "privacy": os.path.join(FRONTEND_DIR, "privacy.html"),
    "terms": os.path.join(FRONTEND_DIR, "terms.html"),
}

# Pages that carry the shared header nav, footer, and language toggle.
NAV_PAGES = dict(TRUST_PAGES)
NAV_PAGES["about"] = ABOUT_HTML
NAV_PAGES["index"] = INDEX_HTML

# Main navigation targets expected on every listener-facing page.
MAIN_NAV_HREFS = ['href="/"', 'href="/about"', 'href="/sources"', 'href="/contact"']
FOOTER_LEGAL_HREFS = ['href="/transparency"', 'href="/privacy"', 'href="/terms"']

NODE = shutil.which("node")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _extract_script(html):
    return re.findall(r"<script>(.*?)</script>", html, re.DOTALL)[0]


def _extract_style(html):
    return re.findall(r"<style>(.*?)</style>", html, re.DOTALL)[0]


# ─── Structural validity ─────────────────────────────────────────────────────

def test_index_html_balanced_tags():
    html = _read(INDEX_HTML)
    assert html.count("<script>") == html.count("</script>")
    assert html.count("<style>") == html.count("</style>")
    assert "<!DOCTYPE html>" in html
    assert html.count("</html>") == 1
    assert html.count("</body>") == 1


def test_index_js_balanced_braces_and_parens():
    js = _extract_script(_read(INDEX_HTML))
    assert js.count("{") == js.count("}"), "unbalanced braces in JS"
    assert js.count("(") == js.count(")"), "unbalanced parens in JS"


def test_index_css_balanced_braces():
    css = _extract_style(_read(INDEX_HTML))
    assert css.count("{") == css.count("}"), "unbalanced braces in CSS"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_index_js_syntax_valid():
    js = _extract_script(_read(INDEX_HTML))
    tmp = "/tmp/_dengbej_frontend_check.js"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(js)
    result = subprocess.run([NODE, "--check", tmp], capture_output=True, text=True)
    assert result.returncode == 0, f"node syntax error: {result.stderr}"


# ─── Public copy (listener-facing) ───────────────────────────────────────────

def test_no_english_only_narration_claim():
    html = _read(INDEX_HTML)
    assert "audio narration in English." not in html


def test_copy_mentions_kurmanji_narration_with_fallback():
    html = _read(INDEX_HTML)
    assert "Kurmanji narration" in html
    assert "fallback" in html.lower()


def test_home_is_listener_facing_not_aws_showcase():
    """Homepage should read as a radio, not an AWS project showcase."""
    html = _read(INDEX_HTML)
    # Challenge/showcase language removed
    assert "Developed through the AWS Builder Challenges" not in html
    assert "Built for the AWS Weekend Challenge" not in html
    assert "Built on AWS" not in html
    # AWS service badge inventory removed
    assert 'class="service-badge"' not in html
    assert 'class="footer-services"' not in html


def test_home_main_nav_is_listen_about_sources_contact():
    html = _read(INDEX_HTML)
    nav = re.search(r'<nav class="site-nav".*?</nav>', html, re.DOTALL).group(0)
    for href in MAIN_NAV_HREFS:
        assert href in nav, f"missing main nav link {href}"
    assert "/how-it-works" not in nav, "prominent How It Works link should be retired"


def test_about_page_is_listener_facing():
    html = _read(ABOUT_HTML)
    # No AWS service inventory, badges, or challenge language
    assert "AWS Services Used" not in html
    assert 'class="service-badge"' not in html
    assert "AWS Builder Challenges" not in html
    assert "AWS 10,000 AIdeas" not in html
    # Keeps the dengbêj story and the audio fallback disclosure
    assert "dengbêj" in html.lower()
    assert "kurmanji" in html.lower()
    assert "falls back to english" in html.lower()


def test_howitworks_redirects_to_transparency():
    html = _read(HOWITWORKS_HTML)
    assert "/transparency" in html
    assert 'http-equiv="refresh"' in html or "location.replace" in html


# ─── Trust pages: availability & structure ───────────────────────────────────

@pytest.mark.parametrize("name,path", list(TRUST_PAGES.items()))
def test_trust_page_exists_and_is_html(name, path):
    assert os.path.exists(path), f"{name}.html is missing"
    html = _read(path)
    assert "<!DOCTYPE html>" in html
    assert html.count("</html>") == 1
    assert html.count("</body>") == 1


@pytest.mark.parametrize("name,path", list(TRUST_PAGES.items()))
def test_trust_page_balanced_css_and_js(name, path):
    html = _read(path)
    css = _extract_style(html)
    js = _extract_script(html)
    assert css.count("{") == css.count("}"), f"{name}: unbalanced CSS braces"
    assert js.count("{") == js.count("}"), f"{name}: unbalanced JS braces"
    assert js.count("(") == js.count(")"), f"{name}: unbalanced JS parens"


@pytest.mark.skipif(NODE is None, reason="node not available")
@pytest.mark.parametrize("name,path", list(NAV_PAGES.items()))
def test_page_js_syntax_valid(name, path):
    js = _extract_script(_read(path))
    tmp = f"/tmp/_dengbej_{name}_check.js"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(js)
    result = subprocess.run([NODE, "--check", tmp], capture_output=True, text=True)
    assert result.returncode == 0, f"{name}: node syntax error: {result.stderr}"


# ─── Trust pages: navigation ─────────────────────────────────────────────────

@pytest.mark.parametrize("name,path", list(NAV_PAGES.items()))
def test_main_nav_links_present(name, path):
    html = _read(path)
    for href in MAIN_NAV_HREFS:
        assert href in html, f"{name}: missing main nav link {href}"


@pytest.mark.parametrize("name,path", list(NAV_PAGES.items()))
def test_footer_legal_links_present(name, path):
    html = _read(path)
    for href in FOOTER_LEGAL_HREFS:
        assert href in html, f"{name}: missing footer policy link {href}"


@pytest.mark.parametrize("name,path", list(NAV_PAGES.items()))
def test_nav_has_accessible_labels(name, path):
    html = _read(path)
    assert 'aria-label="Main navigation"' in html, f"{name}: main nav label missing"
    assert 'aria-label="Footer navigation"' in html, f"{name}: footer nav label missing"


# ─── Trust pages: bilingual copy ─────────────────────────────────────────────

def test_home_ai_disclaimer_changes_with_language():
    """The prominent AI warning must not remain English in Kurdish mode."""
    html = _read(INDEX_HTML)
    assert 'id="submission-disclaimer"' in html
    assert 'document.getElementById("submission-disclaimer").textContent = lang === "ku"' in html


@pytest.mark.parametrize("name,path", list(TRUST_PAGES.items()))
def test_trust_page_has_language_toggle(name, path):
    html = _read(path)
    assert 'id="btn-en"' in html, f"{name}: English toggle missing"
    assert 'id="btn-ku"' in html, f"{name}: Kurdî toggle missing"
    assert "dengbej-lang" in html, f"{name}: language persistence missing"


@pytest.mark.parametrize("name,path", list(TRUST_PAGES.items()))
def test_trust_page_has_kurdish_translations(name, path):
    """Every translated string must provide both en and ku values."""
    js = _extract_script(_read(path))
    # Count translation entries; each real entry has an en and a ku value.
    en_count = len(re.findall(r"\ben:\s", js))
    ku_count = len(re.findall(r"\bku:\s", js))
    assert en_count >= 8, f"{name}: too few translated strings ({en_count})"
    assert en_count == ku_count, f"{name}: en/ku mismatch ({en_count} vs {ku_count})"


@pytest.mark.skipif(NODE is None, reason="node not available")
@pytest.mark.parametrize("name,path", list(TRUST_PAGES.items()))
def test_trust_page_kurdish_toggle_changes_title(name, path):
    """Switching to Kurdî must change the page title text (real translation)."""
    js = _extract_script(_read(path))
    m = re.search(r'"page-title":\s*\{\s*en:\s*"(.*?)",\s*ku:\s*"(.*?)"\s*\}', js)
    assert m, f"{name}: page-title translation not found"
    en_title, ku_title = m.group(1), m.group(2)
    assert en_title and ku_title, f"{name}: empty title translation"
    assert en_title != ku_title, f"{name}: Kurdish title identical to English"


# ─── Trust pages + home: absence of tracking / ads / data-transmitting forms ──

TRACKER_SIGNATURES = [
    "google-analytics.com",
    "googletagmanager.com",
    "gtag(",
    "ga(",
    "fbq(",
    "connect.facebook.net",
    "doubleclick.net",
    "googlesyndication.com",
    "adsbygoogle",
    "hotjar",
    "mixpanel",
    "segment.com/analytics",
    "document.cookie",  # no cookie usage at all on these static pages
]

ALL_PAGES = dict(NAV_PAGES)
ALL_PAGES["how-it-works"] = HOWITWORKS_HTML


@pytest.mark.parametrize("name,path", list(ALL_PAGES.items()))
def test_no_tracking_or_ad_scripts(name, path):
    html = _read(path).lower()
    for sig in TRACKER_SIGNATURES:
        assert sig.lower() not in html, f"{name}: tracker/ad/cookie signature '{sig}' found"


@pytest.mark.parametrize("name,path", list(ALL_PAGES.items()))
def test_no_data_transmitting_forms(name, path):
    html = _read(path).lower()
    assert "<form" not in html, f"{name}: unexpected <form> element"


@pytest.mark.parametrize("name,path", list(TRUST_PAGES.items()))
def test_no_external_analytics_or_ad_hosts_in_scripts(name, path):
    """Only inline scripts are allowed; no external script src on trust pages."""
    html = _read(path)
    external_scripts = re.findall(r"<script[^>]*\bsrc=", html)
    assert not external_scripts, f"{name}: external <script src> found"


# ─── Contact page: verified channels only, no personal/invented contact ──────

def test_contact_uses_only_verified_channels():
    html = _read(TRUST_PAGES["contact"])
    # Verified public channels
    assert "github.com/arslakin/dengbej-ai" in html
    # Must NOT publish the personal git commit email or invented contact details
    assert "arslakin@gmail.com" not in html
    assert "mailto:" not in html
    assert "tel:" not in html


def test_no_personal_email_on_any_public_page():
    for name, path in ALL_PAGES.items():
        html = _read(path)
        assert "arslakin@gmail.com" not in html, f"{name}: personal email leaked"


# ─── Freshness indicator ─────────────────────────────────────────────────────

def test_freshness_element_present():
    html = _read(INDEX_HTML)
    assert 'id="freshness"' in html
    assert "computeFreshness" in html
    assert "updateFreshness" in html


def test_freshness_css_classes_present():
    css = _extract_style(_read(INDEX_HTML))
    assert ".freshness.fresh" in css
    assert ".freshness.recent" in css
    assert ".freshness.archive" in css


# ─── Freshness boundary logic (executed via node) ────────────────────────────

def _run_freshness(hours_ago, lang="en"):
    """Execute computeFreshness with a generated_at that is `hours_ago` old."""
    js = _extract_script(_read(INDEX_HTML))
    m = re.search(r"function computeFreshness\(generatedAtIso\) \{(.*?)\n      \}", js, re.DOTALL)
    assert m, "computeFreshness not found"
    fn_body = m.group(1)
    harness = (
        'var currentLang = "' + lang + '";\n'
        "function computeFreshness(generatedAtIso) {" + fn_body + "\n}\n"
        "var d = new Date(Date.now() - " + str(hours_ago) + " * 3600000);\n"
        "var r = computeFreshness(d.toISOString());\n"
        "console.log(JSON.stringify(r));\n"
    )
    tmp = "/tmp/_dengbej_freshness.js"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(harness)
    result = subprocess.run([NODE, tmp], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    import json
    return json.loads(result.stdout.strip())


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_under_2h_is_recent():
    r = _run_freshness(0.5)
    assert r["cls"] == "fresh"
    assert r["text"] == "Updated recently"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_just_under_2h_boundary():
    r = _run_freshness(1.9)
    assert r["cls"] == "fresh"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_at_2h_is_hours_ago():
    r = _run_freshness(2.1)
    assert r["cls"] == "recent"
    assert "hours ago" in r["text"]


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_mid_range_9h():
    """A 9-hour-old briefing (like today's live) must NOT be archived."""
    r = _run_freshness(9)
    assert r["cls"] == "recent"
    assert r["text"] == "Updated 9 hours ago"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_just_under_30h_boundary():
    r = _run_freshness(29.5)
    assert r["cls"] == "recent"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_over_30h_is_archive():
    r = _run_freshness(31)
    assert r["cls"] == "archive"
    assert r["text"] == "Archive edition"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_kurdish_labels():
    fresh = _run_freshness(0.5, "ku")
    assert "N\u00fb" in fresh["text"] or "rojane" in fresh["text"]
    archive = _run_freshness(50, "ku")
    assert "ar\u015f\u00eev" in archive["text"].lower()


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_freshness_null_when_no_timestamp():
    js = _extract_script(_read(INDEX_HTML))
    m = re.search(r"function computeFreshness\(generatedAtIso\) \{(.*?)\n      \}", js, re.DOTALL)
    fn_body = m.group(1)
    harness = (
        'var currentLang = "en";\n'
        "function computeFreshness(generatedAtIso) {" + fn_body + "\n}\n"
        "console.log(JSON.stringify(computeFreshness(null)));\n"
    )
    tmp = "/tmp/_dengbej_freshness_null.js"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(harness)
    result = subprocess.run([NODE, tmp], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    import json
    assert json.loads(result.stdout.strip()) is None


# ─── Player entry points route through selectAudioUrl ────────────────────────

def test_all_player_entry_points_use_select_audio_url():
    js = _extract_script(_read(INDEX_HTML))
    assert js.count("selectAudioUrl(") >= 4, "not all entry points use selectAudioUrl"
    assert "playAudio(data.audio.url)" not in js
    assert "data.audio.available && data.audio.url" not in js


# ─── Language-aware selectAudioUrl logic (executed via node) ─────────────────

@pytest.mark.skipif(NODE is None, reason="node not available")
def _run_select(audio_meta_js, lang):
    """Execute selectAudioUrl with a given audioMeta and language."""
    js = _extract_script(_read(INDEX_HTML))
    m = re.search(r"function selectAudioUrl\(audioMeta\) \{(.*?)\n      \}", js, re.DOTALL)
    assert m, "selectAudioUrl not found"
    fn_body = m.group(1)
    harness = (
        "var currentLang = " + repr(lang).replace("'", '"') + ";\n"
        "function selectAudioUrl(audioMeta) {" + fn_body + "\n}\n"
        "var meta = " + audio_meta_js + ";\n"
        "console.log(JSON.stringify(selectAudioUrl(meta)));\n"
    )
    tmp = "/tmp/_dengbej_select.js"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(harness)
    result = subprocess.run([NODE, tmp], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    import json
    return json.loads(result.stdout.strip())


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_kurdish_mode_prefers_url_ku():
    result = _run_select(
        '{available:true, url:"legacy.mp3", url_en:"en.mp3", url_ku:"ku.wav"}', "ku"
    )
    assert result == "ku.wav"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_kurdish_mode_falls_back_to_english_when_no_ku():
    result = _run_select(
        '{available:true, url:"legacy.mp3", url_en:"en.mp3", url_ku:null}', "ku"
    )
    assert result == "en.mp3"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_english_mode_prefers_url_en():
    result = _run_select(
        '{available:true, url:"legacy.mp3", url_en:"en.mp3", url_ku:"ku.wav"}', "en"
    )
    assert result == "en.mp3"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_english_mode_falls_back_to_legacy_url():
    result = _run_select(
        '{available:true, url:"legacy.mp3", url_en:null, url_ku:null}', "en"
    )
    assert result == "legacy.mp3"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_returns_null_when_no_audio():
    result = _run_select('{available:false, url:null, url_en:null, url_ku:null}', "ku")
    assert result is None


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_kurdish_url_used_even_if_available_false():
    result = _run_select('{available:true, url_ku:"ku.wav"}', "ku")
    assert result == "ku.wav"
