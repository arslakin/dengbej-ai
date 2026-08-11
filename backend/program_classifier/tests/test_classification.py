"""
Tests for Dengbej program classification.

Tests the editorial distinction between:
- bakur vs general turkey
- rojava vs general syria
- basur vs general iraq
- rojhilat vs general iran
- rojhilat vs middle-east (Rojhilata Navîn)
- kurdistan cross-regional aggregation
- legitimate multi-program membership
- irrelevant country stories excluded from Kurdish regional programs
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from programs import (
    classify_story_deterministic,
    get_program,
    get_all_programs,
    PROGRAM_IDS,
    PROGRAM_MAP,
    ClassificationResult,
)


# ─── Test: Program Registry ──────────────────────────────────────────────────

def test_nine_programs_defined():
    """Should have exactly 9 programs."""
    assert len(get_all_programs()) == 9


def test_all_program_ids_stable():
    """Program IDs should be stable ASCII strings without Kurdish characters."""
    expected = {"today", "kurdistan", "world", "middle-east", "turkey",
                "bakur", "rojava", "basur", "rojhilat"}
    assert set(PROGRAM_IDS) == expected


def test_program_ids_no_special_chars():
    """IDs should contain only lowercase ASCII, digits, and hyphens."""
    import re
    for pid in PROGRAM_IDS:
        assert re.match(r'^[a-z0-9-]+$', pid), f"Invalid ID: {pid}"


def test_rojhilat_distinct_from_middle_east():
    """rojhilat and middle-east must be separate programs."""
    assert "rojhilat" in PROGRAM_MAP
    assert "middle-east" in PROGRAM_MAP
    assert PROGRAM_MAP["rojhilat"].id != PROGRAM_MAP["middle-east"].id
    assert "Iran" in PROGRAM_MAP["rojhilat"].description
    assert "Middle East" in PROGRAM_MAP["middle-east"].description


# ─── Test: Bakur vs General Turkey ────────────────────────────────────────────

def test_pkk_story_classified_bakur():
    """PKK/Kurdish peace process story → bakur + kurdistan + turkey."""
    result = classify_story_deterministic(
        headline="Turkey MPs back historic law on reintegrating PKK militants",
        summary="Parliament approves conditional amnesty for PKK members",
        category="politics"
    )
    assert "bakur" in result.programs, f"Expected bakur, got {result.programs}"
    assert "kurdistan" in result.programs
    assert "turkey" in result.programs


def test_general_turkish_economy_not_bakur():
    """General Turkish economic story → turkey, NOT bakur."""
    result = classify_story_deterministic(
        headline="Turkish lira strengthens on central bank rate decision",
        summary="Turkey's central bank holds interest rates steady at 50%",
        category="economy"
    )
    assert "turkey" in result.programs
    assert "bakur" not in result.programs, f"General Turkish economy should not be bakur: {result.programs}"


def test_erdogan_general_not_bakur():
    """Erdogan story without Kurdish content → turkey, NOT bakur."""
    result = classify_story_deterministic(
        headline="Erdogan visits Berlin for trade talks",
        summary="Turkish president discusses EU-Turkey trade agreement",
        category="politics"
    )
    assert "turkey" in result.programs
    assert "bakur" not in result.programs


# ─── Test: Rojava vs General Syria ────────────────────────────────────────────

def test_sdf_story_classified_rojava():
    """SDF/NE Syria Kurdish story → rojava + kurdistan."""
    result = classify_story_deterministic(
        headline="SDF forces repel ISIS attack in northeastern Syria",
        summary="Syrian Democratic Forces engage remnant ISIS cells near Hasakah",
        category="conflict"
    )
    assert "rojava" in result.programs
    assert "kurdistan" in result.programs


def test_damascus_story_not_rojava():
    """Damascus-focused story → middle-east or world, NOT rojava."""
    result = classify_story_deterministic(
        headline="Damascus announces new trade agreement with UAE",
        summary="Syrian government signs economic cooperation deal",
        category="economy"
    )
    assert "rojava" not in result.programs, f"Damascus trade story should not be rojava: {result.programs}"


# ─── Test: Başûr vs General Iraq ──────────────────────────────────────────────

def test_krg_story_classified_basur():
    """KRG/Erbil story → basur + kurdistan."""
    result = classify_story_deterministic(
        headline="KRG announces new oil export agreement",
        summary="Kurdistan Regional Government signs deal with Turkish pipeline operator",
        category="economy"
    )
    assert "basur" in result.programs
    assert "kurdistan" in result.programs


def test_baghdad_story_not_basur():
    """Baghdad-focused story → middle-east, NOT basur."""
    result = classify_story_deterministic(
        headline="Iraq parliament passes new budget law",
        summary="Baghdad legislators approve annual spending after months of debate",
        category="politics"
    )
    assert "basur" not in result.programs, f"Baghdad budget should not be basur: {result.programs}"


# ─── Test: Rojhilat vs General Iran ──────────────────────────────────────────

def test_kurdish_iran_classified_rojhilat():
    """Kurdish rights in Iran → rojhilat + kurdistan."""
    result = classify_story_deterministic(
        headline="Iranian Kurdish political prisoner released after 10 years",
        summary="PDKI member freed from prison in Sanandaj",
        category="human-rights"
    )
    assert "rojhilat" in result.programs
    assert "kurdistan" in result.programs


def test_tehran_nuclear_not_rojhilat():
    """Tehran nuclear story → middle-east, NOT rojhilat."""
    result = classify_story_deterministic(
        headline="Iran nuclear talks resume in Vienna",
        summary="Tehran and world powers discuss uranium enrichment limits",
        category="politics"
    )
    assert "rojhilat" not in result.programs, f"Nuclear talks should not be rojhilat: {result.programs}"


# ─── Test: Rojhilat vs Rojhilata Navîn (Middle East) ─────────────────────────

def test_rojhilat_and_middle_east_independent():
    """A Kurdish-Iran story should be rojhilat but not necessarily middle-east by Kurdish indicators."""
    result = classify_story_deterministic(
        headline="Kolbar killed at Iranian border",
        summary="Kurdish porter shot by Iranian border forces near Rojhilat",
        category="human-rights"
    )
    assert "rojhilat" in result.programs
    # It might also be middle-east due to "iran" keyword, which is acceptable
    # But the key test is that rojhilat is classified independently


def test_gulf_war_not_rojhilat():
    """Gulf/Middle East military story → middle-east, NOT rojhilat."""
    result = classify_story_deterministic(
        headline="US naval fleet enters Persian Gulf amid tensions",
        summary="Pentagon deploys carrier group to Gulf region",
        category="conflict"
    )
    assert "middle-east" in result.programs
    assert "rojhilat" not in result.programs


# ─── Test: Kurdistan Cross-Regional ──────────────────────────────────────────

def test_kurdistan_includes_bakur():
    """Bakur story should also be in kurdistan."""
    result = classify_story_deterministic(
        headline="Kurdish language education expanded in Diyarbakir",
        summary="New Kurmanji-medium schools open in southeastern Turkey",
        category="culture"
    )
    assert "bakur" in result.programs
    assert "kurdistan" in result.programs


def test_kurdistan_includes_rojava():
    """Rojava story should also be in kurdistan."""
    result = classify_story_deterministic(
        headline="Autonomous administration holds elections in Qamishli",
        summary="Voters in northeastern Syria elect local council",
        category="politics"
    )
    assert "rojava" in result.programs
    assert "kurdistan" in result.programs


def test_kurdistan_includes_basur():
    """Başûr story should also be in kurdistan."""
    result = classify_story_deterministic(
        headline="Peshmerga forces conduct operation near Kirkuk",
        summary="KRG security forces target ISIS cells",
        category="conflict"
    )
    assert "basur" in result.programs
    assert "kurdistan" in result.programs


def test_kurdistan_includes_rojhilat():
    """Rojhilat story should also be in kurdistan."""
    result = classify_story_deterministic(
        headline="Kurdish protests spread across Mahabad",
        summary="Demonstrations in Iranian Kurdish cities over rights",
        category="human-rights"
    )
    assert "rojhilat" in result.programs
    assert "kurdistan" in result.programs


# ─── Test: Multi-Program Membership ──────────────────────────────────────────

def test_multi_program_pkk_turkey_bakur_kurdistan():
    """PKK story should legitimately belong to turkey + bakur + kurdistan."""
    result = classify_story_deterministic(
        headline="Ocalan calls for PKK disarmament from prison",
        summary="Kurdish leader Abdullah Ocalan sends message via lawyers in Turkey",
        category="politics"
    )
    assert "turkey" in result.programs
    assert "bakur" in result.programs
    assert "kurdistan" in result.programs


def test_multi_program_krg_middle_east():
    """KRG oil deal may belong to basur + kurdistan + middle-east."""
    result = classify_story_deterministic(
        headline="KRG oil exports resume through Iraq pipeline",
        summary="Kurdistan Region reaches agreement with Baghdad on oil revenue sharing",
        category="economy"
    )
    assert "basur" in result.programs
    assert "kurdistan" in result.programs
    # Iraq keyword triggers middle-east


# ─── Test: Irrelevant Stories Excluded ────────────────────────────────────────

def test_unrelated_us_story_not_kurdish():
    """US domestic story → world only, not any Kurdish program."""
    result = classify_story_deterministic(
        headline="US Supreme Court rules on healthcare law",
        summary="American court decision affects insurance coverage for millions",
        category="politics"
    )
    assert "bakur" not in result.programs
    assert "rojava" not in result.programs
    assert "basur" not in result.programs
    assert "rojhilat" not in result.programs
    assert "kurdistan" not in result.programs


def test_european_story_not_kurdish():
    """European story without Kurdish angle → world, not Kurdish programs."""
    result = classify_story_deterministic(
        headline="EU agrees on new climate targets",
        summary="European Union leaders commit to reducing emissions by 2030",
        category="climate"
    )
    assert "bakur" not in result.programs
    assert "rojava" not in result.programs
    assert "basur" not in result.programs
    assert "rojhilat" not in result.programs
    assert "kurdistan" not in result.programs


def test_classification_result_belongs_to():
    """ClassificationResult.belongs_to() should work correctly."""
    result = ClassificationResult(programs={"bakur", "kurdistan", "turkey"})
    assert result.belongs_to("bakur")
    assert result.belongs_to("kurdistan")
    assert result.belongs_to("turkey")
    assert not result.belongs_to("rojava")
    assert not result.belongs_to("world")


# ─── Run Tests ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_functions = [v for k, v in globals().items() if k.startswith("test_")]
    passed = 0
    failed = 0

    print("Running Program Classification tests...\n")

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
