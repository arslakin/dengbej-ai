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
    assert "offers english narration if one exists" in html.lower()
    assert "some programs may have no audio yet" in html.lower()


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


# ─── Contact page: "Report a correction" new-issue link + bilingual note ─────

def test_contact_has_report_correction_new_issue_link():
    """Contact must offer a direct, labelled link to the repo's new-issue page."""
    html = _read(TRUST_PAGES["contact"])
    assert 'href="https://github.com/arslakin/dengbej-ai/issues/new"' in html, \
        "missing direct new-issue link"
    assert 'id="link-report-correction"' in html, "report-correction link id missing"
    # Link opens externally and safely.
    m = re.search(r'<a href="https://github.com/arslakin/dengbej-ai/issues/new"[^>]*>', html)
    assert m, "new-issue anchor not found"
    anchor = m.group(0)
    assert 'target="_blank"' in anchor, "new-issue link should open in a new tab"
    assert "noopener" in anchor, "new-issue link missing rel=noopener"


def test_contact_report_link_is_clearly_labelled_both_languages():
    """The link label must be a clear 'report a correction' call in en and ku."""
    js = _extract_script(_read(TRUST_PAGES["contact"]))
    m = re.search(
        r'"link-report-correction":\s*\{\s*en:\s*"(.*?)",\s*ku:\s*"(.*?)"\s*\}', js
    )
    assert m, "link-report-correction translation not found"
    en_label, ku_label = m.group(1), m.group(2)
    assert "correction" in en_label.lower(), "English label must mention correction"
    assert en_label and ku_label and en_label != ku_label, \
        "labels must be present and translated"


def test_contact_discloses_github_signin_bilingually():
    """Honest disclosure that GitHub may require sign-in, in en and ku."""
    html = _read(TRUST_PAGES["contact"])
    assert 'id="p-report-note"' in html, "sign-in disclosure element missing"
    js = _extract_script(html)
    m = re.search(
        r'"p-report-note":\s*\{\s*en:\s*"(.*?)",\s*ku:\s*"(.*?)"\s*\}', js, re.DOTALL
    )
    assert m, "p-report-note translation not found"
    en_note, ku_note = m.group(1), m.group(2)
    assert "sign in" in en_note.lower(), "English note must disclose GitHub sign-in"
    assert en_note and ku_note and en_note != ku_note, \
        "sign-in note must be present and translated"


def test_contact_report_link_makes_no_unsupported_promise():
    """The correction flow must not invent an email or promise a response time."""
    html = _read(TRUST_PAGES["contact"])
    assert "mailto:" not in html
    # No response-time / guarantee language around corrections.
    for phrase in ["within 24 hours", "we will respond", "guaranteed", "response time"]:
        assert phrase.lower() not in html.lower(), f"unsupported promise: {phrase}"


# ─── Regional programs: empty programs stay selectable + empty state ─────────

def _index_script():
    return _extract_script(_read(INDEX_HTML))


def test_program_buttons_are_never_disabled_when_empty():
    """A program with zero stories must NOT be rendered disabled/unclickable.

    Regression guard: previously empty programs (e.g. Bakur, Rojhilat) got
    data-available="false" plus a `disabled` attribute and CSS
    pointer-events:none, which made them unselectable. Selectability must be
    decoupled from story presence.
    """
    js = _index_script()
    # The button template must not inject a disabled attribute.
    m = re.search(r"function renderPrograms\(\) \{(.*?)\n      \}", js, re.DOTALL)
    assert m, "renderPrograms not found"
    body = m.group(1)
    assert "disabled" not in body, "program buttons must not be disabled"
    assert 'data-available="' not in body, "old availability-disabling attribute present"
    # The click handler must not early-return on a disabled button.
    assert "if (btn.disabled) return" not in body, "click handler still gates on disabled"


def test_program_btn_css_does_not_block_pointer_events():
    """Empty-program styling must not disable pointer events or clicks."""
    css = _extract_style(_read(INDEX_HTML))
    # Grab all .program-btn rules and ensure none kill interactivity.
    program_btn_rules = re.findall(r"\.program-btn[^\{]*\{[^\}]*\}", css)
    assert program_btn_rules, "no .program-btn CSS rules found"
    joined = " ".join(program_btn_rules)
    assert "pointer-events: none" not in joined, "program buttons block pointer events"
    assert "cursor: not-allowed" not in joined, "program buttons show not-allowed cursor"


def test_bakur_and_rojhilat_are_defined_selectable_programs():
    """Bakur and Rojhilat must exist in the program list so they can be selected."""
    js = _index_script()
    m = re.search(r"var PROGRAMS = \[(.*?)\];", js, re.DOTALL)
    assert m, "PROGRAMS list not found"
    programs_block = m.group(1)
    assert 'id: "bakur"' in programs_block, "bakur program missing"
    assert 'id: "rojhilat"' in programs_block, "rojhilat program missing"


def test_empty_program_shows_no_current_stories_bilingual():
    """Empty program view + today empty state must show 'No current stories' (EN) and a Kurdish equivalent."""
    js = _index_script()
    # English empty label present.
    assert "No current stories" in js, "English empty state missing"
    # Kurdish empty label present. The source stores Kurdish letters as JS
    # \uXXXX escapes, so match the literal escape sequence (Niha çîrok nînin).
    assert r"Niha \u00E7\u00EErok n\u00EEnin" in js, "Kurdish empty state missing"


def test_empty_program_view_uses_empty_state_not_substitute_stories():
    """The program view empty branch must render the empty state, never fabricate stories."""
    js = _index_script()
    m = re.search(r"function renderProgramView\(data, programId\) \{(.*?)\n      \}", js, re.DOTALL)
    assert m, "renderProgramView not found"
    body = m.group(1)
    # Empty branch keyed on zero stories renders the radio-card-empty block.
    assert "radio-card-empty" in body, "empty-state block missing in program view"
    assert "storyCount === 0" in body, "empty-state condition missing"


def test_navigation_does_not_skip_empty_programs():
    """Prev/next navigation must reach empty programs, not skip them."""
    js = _index_script()
    m = re.search(
        r"function findNextAvailableProgram\(startIdx, direction\) \{(.*?)\n      \}",
        js, re.DOTALL,
    )
    assert m, "findNextAvailableProgram not found"
    body = m.group(1)
    # Must not gate stepping on programAvailability (which would skip empties).
    assert "programAvailability" not in body, "navigation still skips empty programs"


# ─── Source-URL scheme hardening (production-readiness) ──────────────────────

def _run_safe_url(url_literal):
    """Execute the frontend safeUrl() helper via node with a given input."""
    if NODE is None:
        pytest.skip("node not available")
    js = _extract_script(_read(INDEX_HTML))
    m = re.search(r"function safeUrl\(url\) \{.*?\n      \}", js, re.DOTALL)
    assert m, "safeUrl() not found"
    harness = m.group(0) + "\nconsole.log(JSON.stringify(safeUrl(" + url_literal + ")));\n"
    tmp = "/tmp/_dengbej_safeurl.js"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(harness)
    result = subprocess.run([NODE, tmp], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    import json
    return json.loads(result.stdout.strip())


def test_safe_url_helper_exists_and_is_used_for_story_links():
    """Story links must route the source URL through safeUrl() (scheme allow-list)."""
    js = _extract_script(_read(INDEX_HTML))
    assert "function safeUrl(url)" in js, "safeUrl helper missing"
    # Both render paths must sanitize the primary source URL.
    assert js.count("safeUrl(story.primary_source.url)") >= 2, \
        "story links not consistently sanitized"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_safe_url_allows_http_and_https():
    assert _run_safe_url('"https://bbc.co.uk/news/x"') == "https://bbc.co.uk/news/x"
    assert _run_safe_url('"http://example.com/a"') == "http://example.com/a"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_safe_url_blocks_javascript_and_data_schemes():
    """javascript:/data: URLs from untrusted feeds must be neutralized to empty."""
    assert _run_safe_url('"javascript:alert(1)"') == ""
    assert _run_safe_url('"JavaScript:alert(1)"') == ""
    assert _run_safe_url('"data:text/html;base64,PHN2Zz4="') == ""
    assert _run_safe_url("\"  javascript:alert(1)  \"") == ""
    assert _run_safe_url("null") == ""
    assert _run_safe_url('""') == ""


# ─── Desktop listening layout (>=1100px) ────────────────────────────────────
# Bounded desktop-only enhancement: at >=1100px the story list becomes a
# two-column reading grid with a full-width lead story and full-width state
# containers. Mobile/tablet layouts and all behavior must be preserved.

def _desktop_media_block():
    """Return the CSS text inside the @media (min-width: 1100px) block."""
    css = _extract_style(_read(INDEX_HTML))
    idx = css.find("@media (min-width: 1100px)")
    assert idx != -1, "desktop (>=1100px) media query missing"
    # Walk braces to capture the full block body.
    brace_start = css.index("{", idx)
    depth = 0
    for i in range(brace_start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[brace_start + 1:i]
    raise AssertionError("unterminated desktop media block")


def test_desktop_breakpoint_exists_at_1100px():
    css = _extract_style(_read(INDEX_HTML))
    assert "@media (min-width: 1100px)" in css, "desktop breakpoint must be >=1100px"


def test_desktop_widens_main_listening_area():
    block = _desktop_media_block()
    assert "#main-content.container" in block, "desktop should widen the main content container"
    assert "max-width" in block, "desktop main content should set a wider max-width"


def test_desktop_stories_container_is_two_column_grid():
    block = _desktop_media_block()
    assert "#stories-container" in block
    assert "display: grid" in block, "stories container must be a grid on desktop"
    assert "grid-template-columns: 1fr 1fr" in block, "stories grid must be two columns"


def test_desktop_lead_story_spans_full_width():
    block = _desktop_media_block()
    assert "#stories-container > .story:first-child" in block, "lead story rule missing"
    # The lead story and other full-width elements use grid-column: 1 / -1.
    assert "grid-column: 1 / -1" in block, "lead story must span the full grid width"


def test_desktop_state_containers_span_full_grid():
    block = _desktop_media_block()
    assert "#stories-container > .state-container" in block, \
        "loading/error/empty state containers must span the grid on desktop"


def test_desktop_program_card_spans_full_grid():
    block = _desktop_media_block()
    assert "#stories-container > .radio-card" in block, \
        "program radio-card must span the full grid width on desktop"


def test_mobile_and_tablet_breakpoints_preserved():
    """The desktop change must not remove existing mobile/tablet breakpoints."""
    css = _extract_style(_read(INDEX_HTML))
    assert "@media (max-width: 599px)" in css, "mobile breakpoint lost"
    assert "@media (min-width: 600px) and (max-width: 899px)" in css, "tablet breakpoint lost"
    assert "@media (min-width: 900px)" in css, "900px breakpoint lost"
    assert "@media (prefers-reduced-motion: reduce)" in css, "reduced-motion block lost"


def test_desktop_change_does_not_alter_core_behavior_hooks():
    """Behavior-critical IDs/handlers remain present (no JS/markup regression)."""
    html = _read(INDEX_HTML)
    js = _extract_script(html)
    # Listening experience + player + bilingual + audio selection still wired.
    assert 'id="beje-btn"' in html
    assert 'id="stories-container"' in html
    assert 'id="main-content"' in html
    assert 'id="btn-en"' in html and 'id="btn-ku"' in html
    assert "function selectAudioUrl(audioMeta)" in js
    assert "function renderStories(data)" in js
    assert "function renderProgramView(data, programId)" in js


# ─── Mobile Web V1 (320px–430px) ────────────────────────────────────────────

def _mobile_media_block(path=INDEX_HTML):
    """Return the CSS text inside the canonical max-width: 599px block."""
    css = _extract_style(_read(path))
    marker = "@media (max-width: 599px)"
    idx = css.find(marker)
    assert idx != -1, f"mobile media query missing in {os.path.basename(path)}"
    brace_start = css.index("{", idx)
    depth = 0
    for i in range(brace_start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[brace_start + 1:i]
    raise AssertionError("unterminated mobile media block")


def test_mobile_breakpoint_covers_320_to_430_without_touching_tablet():
    css = _extract_style(_read(INDEX_HTML))
    assert "@media (max-width: 599px)" in css
    assert "@media (min-width: 600px) and (max-width: 899px)" in css
    assert "@media (min-width: 1100px)" in css


def test_mobile_program_choices_scroll_horizontally():
    block = _mobile_media_block()
    assert "flex-flow: row nowrap" in block
    assert "overflow-x: auto" in block
    assert "overscroll-behavior-inline: contain" in block
    assert "-webkit-overflow-scrolling: touch" in block
    assert "white-space: nowrap" in block
    assert "scroll-snap-align: start" in block


def test_mobile_primary_controls_meet_minimum_touch_target():
    block = _mobile_media_block()
    assert ".lang-toggle button" in block and "min-height: 44px" in block
    assert ".program-btn" in block
    assert ".beje-btn { width: 100%; min-height: 48px; }" in block
    assert ".player-btn { width: 44px; height: 44px; }" in block
    assert ".player-btn-main { width: 48px; height: 48px; }" in block
    assert ".read-more-btn, .retry-btn" in block
    assert ".footer-nav a, .footer-legal a" in block


def test_mobile_player_respects_safe_area_and_cannot_cover_content():
    block = _mobile_media_block()
    assert "env(safe-area-inset-bottom)" in block
    assert "body { padding-bottom: calc(96px + env(safe-area-inset-bottom)); }" in block
    assert ".player-bar" in block
    assert "padding-bottom: env(safe-area-inset-bottom)" in block
    assert "min-height: 72px" in block


def test_mobile_headlines_remain_readable_without_clamping():
    block = _mobile_media_block()
    assert ".story-headline" in block
    assert "overflow-wrap: anywhere" in block
    assert "-webkit-line-clamp: unset" in block
    assert "overflow: visible" in block


@pytest.mark.parametrize("name,path", list(NAV_PAGES.items()))
def test_listener_pages_keep_language_controls_touch_friendly(name, path):
    block = _mobile_media_block(path)
    assert ".lang-toggle button" in block, f"{name}: mobile language controls missing"
    assert "min-height: 44px" in block, f"{name}: mobile targets below 44px"


def test_mobile_reduced_motion_and_regional_empty_state_preserved():
    html = _read(INDEX_HTML)
    css = _extract_style(html)
    js = _extract_script(html)
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert 'id: "bakur"' in js and 'id: "rojhilat"' in js
    assert "No current stories" in js
    assert r"Niha \u00E7\u00EErok n\u00EEnin" in js
    assert "if (btn.disabled) return" not in js


# ─── PWA foundation ─────────────────────────────────────────────────────────

MANIFEST = os.path.join(FRONTEND_DIR, "manifest.webmanifest")
SERVICE_WORKER = os.path.join(FRONTEND_DIR, "sw.js")
OFFLINE_HTML = os.path.join(FRONTEND_DIR, "offline.html")


def test_manifest_has_required_installable_fields():
    import json
    manifest = json.loads(_read(MANIFEST))
    assert manifest["name"] == "Dengbêj AI"
    assert manifest["short_name"] == "Dengbêj"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#7a3b10"
    assert manifest["background_color"] == "#faf9f7"
    assert manifest["prefer_related_applications"] is False
    assert manifest["lang"] == "ku"


def test_manifest_declares_exact_192_and_512_png_icons():
    import json
    manifest = json.loads(_read(MANIFEST))
    icons = {icon["sizes"]: icon for icon in manifest["icons"]}
    assert set(icons) == {"192x192", "512x512"}
    assert icons["192x192"]["src"] == "/icons/dengbej-192.png"
    assert icons["512x512"]["src"] == "/icons/dengbej-512.png"
    assert all(icon["type"] == "image/png" for icon in icons.values())


def _png_dimensions(path):
    import struct
    with open(path, "rb") as image:
        header = image.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n", f"not a PNG: {path}"
    return struct.unpack(">II", header[16:24])


def test_pwa_icon_files_have_exact_pixel_dimensions():
    icon_dir = os.path.join(FRONTEND_DIR, "icons")
    assert _png_dimensions(os.path.join(icon_dir, "dengbej-192.png")) == (192, 192)
    assert _png_dimensions(os.path.join(icon_dir, "dengbej-512.png")) == (512, 512)


def test_icons_are_reproducibly_derived_from_approved_wordmark():
    generator = _read(os.path.join(FRONTEND_DIR, "icons", "generate_icons.swift"))
    assert 'let wordmark = "DENGBÊJ"' in generator
    assert "#7a3b10" in generator and "#faf9f7" in generator
    assert "no approved portrait" in generator.lower()


def test_every_public_html_page_references_manifest_theme_and_touch_icon():
    pages = sorted(
        os.path.join(FRONTEND_DIR, name)
        for name in os.listdir(FRONTEND_DIR)
        if name.endswith(".html")
    )
    assert pages, "no public HTML pages found"
    for path in pages:
        html = _read(path)
        name = os.path.basename(path)
        assert '<link rel="manifest" href="/manifest.webmanifest">' in html, f"{name}: manifest missing"
        assert '<meta name="theme-color" content="#7a3b10">' in html, f"{name}: theme-color missing"
        assert '<link rel="apple-touch-icon" href="/icons/dengbej-192.png">' in html, f"{name}: touch icon missing"


def test_service_worker_registration_is_feature_detected_and_non_fatal():
    js = _extract_script(_read(INDEX_HTML))
    assert '"serviceWorker" in navigator' in js
    assert 'navigator.serviceWorker.register("/sw.js", { scope: "/" })' in js
    assert ".catch(function()" in js
    assert "registerServiceWorker();" in js


def test_service_worker_never_caches_news_api_or_audio():
    sw = _read(SERVICE_WORKER)
    assert 'url.origin !== self.location.origin' in sw, "cross-origin API/audio must bypass SW"
    assert 'url.pathname.startsWith("/news/")' in sw, "future same-origin news APIs must bypass SW"
    assert 'request.destination === "audio"' in sw
    assert "AUDIO_EXTENSION.test(url.pathname)" in sw
    assert "lambda-url" not in sw, "news API URL must never enter the static cache list"
    assert "audio_url" not in sw


def test_service_worker_uses_network_first_navigation_and_honest_offline_fallback():
    sw = _read(SERVICE_WORKER)
    navigate = sw.index('request.mode === "navigate"')
    assert navigate != -1
    section = sw[navigate:]
    assert section.index("fetch(request)") < section.index("caches.match(request)"), \
        "navigation must be network-first, not stale-cache-first"
    assert 'const OFFLINE_URL = "/offline.html"' in sw
    assert "caches.match(OFFLINE_URL)" in sw
    assert "cache.add(url).catch" in sw, "one cache miss must not break SW installation"


def test_offline_state_is_honest_and_bilingual():
    html = _read(OFFLINE_HTML)
    assert "You’re offline" in html
    assert "Tu niha bê înternet î" in html
    assert "Cached news is not shown as current" in html
    js = _extract_script(_read(INDEX_HTML))
    assert "navigator.onLine === false" in js
    assert "Current stories are unavailable without an internet connection" in js
    assert r"Tu niha b\u00EA \u00EEnternet \u00EE" in js


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_service_worker_javascript_syntax_valid():
    result = subprocess.run([NODE, "--check", SERVICE_WORKER], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ─── Media Session progressive enhancement ──────────────────────────────────

def test_media_session_is_feature_detected_and_initialized():
    js = _extract_script(_read(INDEX_HTML))
    assert 'return "mediaSession" in navigator' in js
    assert 'typeof MediaMetadata === "undefined"' in js
    assert 'typeof navigator.mediaSession.setActionHandler !== "function"' in js
    assert "setupMediaSession();" in js


def test_media_session_exposes_current_program_metadata_and_artwork():
    js = _extract_script(_read(INDEX_HTML))
    assert "function updateMediaSessionMetadata(title)" in js
    assert "navigator.mediaSession.metadata = new MediaMetadata" in js
    assert "title: title" in js
    assert 'artist: "Dengb\\u00EAj AI"' in js
    assert '/icons/dengbej-192.png' in js
    assert '/icons/dengbej-512.png' in js
    assert "updateMediaSessionMetadata(playerTitle.textContent)" in js


def test_media_session_registers_play_pause_previous_next_actions():
    js = _extract_script(_read(INDEX_HTML))
    assert "function setupMediaSession()" in js
    assert "play: function()" in js
    assert "audioPlayer.play()" in js
    assert "pause: function()" in js
    assert "audioPlayer.pause()" in js
    assert "previoustrack: playPrevProgram" in js
    assert "nexttrack: playNextProgram" in js
    assert "navigator.mediaSession.setActionHandler(action, handlers[action])" in js


def test_media_session_updates_playback_state_without_breaking_audio():
    js = _extract_script(_read(INDEX_HTML))
    assert '"playbackState" in navigator.mediaSession' in js
    assert 'audioPlayer.addEventListener("play"' in js
    assert 'updateMediaSessionPlaybackState("playing")' in js
    assert 'audioPlayer.addEventListener("pause"' in js
    assert 'updateMediaSessionPlaybackState("paused")' in js
    assert 'updateMediaSessionPlaybackState("none")' in js
    # Existing selection/fallback behavior remains the source of playback URLs.
    assert "function selectAudioUrl(audioMeta)" in js
    assert js.count("selectAudioUrl(") >= 4


def test_media_session_failures_are_isolated_from_normal_playback():
    js = _extract_script(_read(INDEX_HTML))
    metadata = re.search(
        r"function updateMediaSessionMetadata\(title\) \{(.*?)\n      \}", js, re.DOTALL
    )
    setup = re.search(r"function setupMediaSession\(\) \{(.*?)\n      \}", js, re.DOTALL)
    assert metadata and setup
    assert "try {" in metadata.group(1) and "catch (e)" in metadata.group(1)
    assert "try {" in setup.group(1) and "catch (e)" in setup.group(1)
