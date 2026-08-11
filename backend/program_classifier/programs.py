"""
Dengbej AI — Program Classification Model

Defines the editorial program taxonomy and classification logic for
mapping news stories to Dengbej listening programs.

Programs:
  today        — Today's main news (all top stories)
  kurdistan    — Cross-regional Kurdish affairs
  world        — Global/international news
  middle-east  — Broader Middle East region
  turkey       — Turkey (general, non-Kurdish-specific)
  bakur        — Kurdish issues in Turkey (Northern Kurdistan)
  rojava       — Kurdish issues in Syria (Rojava / NE Syria)
  basur        — Kurdish issues in Iraq (Kurdistan Region / Southern Kurdistan)
  rojhilat     — Kurdish issues in Iran (Eastern Kurdistan)

Important distinctions:
  - bakur ≠ turkey: Kurdish-specific vs general Turkish affairs
  - rojava ≠ syria: Kurdish-specific vs general Syrian affairs
  - basur ≠ iraq: Kurdish-specific vs general Iraqi affairs
  - rojhilat ≠ iran: Kurdish-specific vs general Iranian affairs
  - rojhilat ≠ middle-east: Kurdish regional vs broader Middle East
  - kurdistan = cross-regional Kurdish (may include bakur + rojava + basur + rojhilat + diaspora)

Multi-program membership:
  A story may belong to multiple programs simultaneously.
  Example: Kurdish peace process in Turkey → turkey + bakur + kurdistan
"""

from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class Program:
    """A Dengbej editorial program/topic."""
    id: str
    label_ku: str
    label_en: str
    description: str
    group: str  # "general" or "kurdish-regions"
    available: bool = False


# ─── Program Registry ─────────────────────────────────────────────────────────

PROGRAMS = [
    Program(
        id="today",
        label_ku="Nûçeyên Îro",
        label_en="Today's News",
        description="Top 5 daily stories across all topics",
        group="general",
        available=True,
    ),
    Program(
        id="kurdistan",
        label_ku="Behsa Kurdistanê bike",
        label_en="About Kurdistan",
        description="Cross-regional Kurdish affairs (Bakur + Rojava + Başûr + Rojhilat + diaspora)",
        group="general",
        available=False,
    ),
    Program(
        id="world",
        label_ku="Behsa dinyayê bike",
        label_en="World News",
        description="Global/international stories",
        group="general",
        available=False,
    ),
    Program(
        id="middle-east",
        label_ku="Behsa Rojhilata Navîn bike",
        label_en="Middle East",
        description="Broader Middle East regional news",
        group="general",
        available=False,
    ),
    Program(
        id="turkey",
        label_ku="Behsa Tirkiyeyê bike",
        label_en="About Turkey",
        description="General Turkish politics, economy, society (non-Kurdish-specific)",
        group="general",
        available=False,
    ),
    Program(
        id="bakur",
        label_ku="Behsa Bakur bike",
        label_en="Northern Kurdistan",
        description="Kurdish-related news in Turkey: communities, politics, language, culture, rights",
        group="kurdish-regions",
        available=False,
    ),
    Program(
        id="rojava",
        label_ku="Behsa Rojava bike",
        label_en="Rojava",
        description="Kurdish-related news in northern/northeastern Syria: administration, security, culture",
        group="kurdish-regions",
        available=False,
    ),
    Program(
        id="basur",
        label_ku="Behsa Başûr bike",
        label_en="Southern Kurdistan",
        description="Kurdistan Region of Iraq: KRG, Erbil, Sulaymaniyah, Duhok, Kurdish institutions",
        group="kurdish-regions",
        available=False,
    ),
    Program(
        id="rojhilat",
        label_ku="Behsa Rojhilat bike",
        label_en="Eastern Kurdistan",
        description="Kurdish-related news in Iran: communities, rights, culture, politics",
        group="kurdish-regions",
        available=False,
    ),
]

PROGRAM_MAP = {p.id: p for p in PROGRAMS}
PROGRAM_IDS = [p.id for p in PROGRAMS]


# ─── Classification Result ────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    """Result of classifying a story into programs."""
    programs: Set[str] = field(default_factory=set)
    confidence: float = 0.0
    reasoning: str = ""

    def belongs_to(self, program_id: str) -> bool:
        return program_id in self.programs


# ─── Classification Logic ─────────────────────────────────────────────────────

# Kurdish-relevance indicators by region (for deterministic pre-filtering)
BAKUR_INDICATORS = {
    "pkk", "hdp", "dem party", "dem partisi", "kurdish turkey",
    "diyarbakir", "amed", "southeast turkey", "southeastern turkey",
    "kurdish language turkey", "kurdish rights turkey", "ocalan", "öcalan",
    "bakur", "northern kurdistan", "kurdish peace process",
    "kurdish workers party", "partiya karkerên kurdistanê",
}

ROJAVA_INDICATORS = {
    "rojava", "northeast syria", "northeastern syria", "sdf",
    "syrian democratic forces", "ypg", "pyd", "autonomous administration",
    "qamishli", "qamişlo", "hasakah", "kobane", "kobanê", "afrin", "efrîn",
    "manbij", "tel abyad", "serêkaniyê",
}

BASUR_INDICATORS = {
    "basur", "southern kurdistan", "kurdistan region", "krg",
    "kurdistan regional government", "erbil", "hewlêr", "sulaymaniyah",
    "silêmanî", "duhok", "peshmerga", "pêşmerge", "puk", "kdp",
    "barzani", "talabani", "halabja", "kirkuk", "kerkûk",
}

ROJHILAT_INDICATORS = {
    "rojhilat", "eastern kurdistan", "kurdish iran", "iranian kurdistan",
    "kolbar", "kurdish rights iran", "mahabad", "sanandaj", "sinê",
    "ilam", "Kermanshah", "kurdistan province iran", "pdki", "pjak",
    "komala", "iranian kurds",
}

MIDDLE_EAST_INDICATORS = {
    "middle east", "gulf", "arab", "iran", "iraq", "syria", "yemen",
    "saudi", "jordan", "egypt", "lebanon", "israel", "palestine", "gaza",
    "hormuz", "strait", "opec",
}

TURKEY_INDICATORS = {
    "turkey", "türkiye", "tirkiye", "ankara", "istanbul", "erdogan",
    "turkish", "ak party", "chp", "mhp",
}


def classify_story_deterministic(headline: str, summary: str, category: str = "") -> ClassificationResult:
    """
    Deterministic pre-classification of a story into programs.

    This is a FAST first pass. For production use, Bedrock-assisted
    classification would follow for ambiguous cases.

    Returns programs the story likely belongs to based on keyword/entity matching.
    """
    text = f"{headline} {summary} {category}".lower()
    programs = set()
    reasons = []

    # Kurdish regional programs
    if any(ind in text for ind in BAKUR_INDICATORS):
        programs.add("bakur")
        programs.add("kurdistan")
        reasons.append("Kurdish-Turkey indicators found")

    if any(ind in text for ind in ROJAVA_INDICATORS):
        programs.add("rojava")
        programs.add("kurdistan")
        reasons.append("Rojava/NE Syria indicators found")

    if any(ind in text for ind in BASUR_INDICATORS):
        programs.add("basur")
        programs.add("kurdistan")
        reasons.append("Kurdistan Region/Iraq indicators found")

    if any(ind in text for ind in ROJHILAT_INDICATORS):
        programs.add("rojhilat")
        programs.add("kurdistan")
        reasons.append("Kurdish-Iran indicators found")

    # General programs
    if any(ind in text for ind in TURKEY_INDICATORS):
        programs.add("turkey")
        reasons.append("Turkey indicators found")

    if any(ind in text for ind in MIDDLE_EAST_INDICATORS):
        programs.add("middle-east")
        reasons.append("Middle East indicators found")

    # World is a fallback — most international stories qualify
    if not programs or category in ("world", "conflict", "economy", "climate", "technology"):
        programs.add("world")

    # Today's news always includes top stories regardless of topic
    programs.add("today")

    return ClassificationResult(
        programs=programs,
        confidence=0.7 if len(programs) > 2 else 0.85,
        reasoning="; ".join(reasons) if reasons else "General/world news",
    )


def get_program(program_id: str) -> Optional[Program]:
    """Get a program by its stable ID."""
    return PROGRAM_MAP.get(program_id)


def get_available_programs() -> List[Program]:
    """Get all currently available programs."""
    return [p for p in PROGRAMS if p.available]


def get_all_programs() -> List[Program]:
    """Get all defined programs."""
    return list(PROGRAMS)
