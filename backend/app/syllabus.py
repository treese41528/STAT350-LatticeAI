"""Ground syllabus answers in the correct (term, modality).

The knowledge collection holds several terms × modalities of near-identical
syllabi, so embedding similarity alone cannot reliably pick the right one.
Instead we retrieve broadly and then KEEP ONLY passages whose source filename
matches the current term and the student's section — and if none match, the
caller links the authoritative PDF rather than quote a possibly-wrong term.

The current term is authoritative from config (`course.term`); the professor
sets it each deployment. `term_for_date` is a safety net used only to warn at
startup when config looks stale (e.g. forgotten at a semester rollover).
"""

from __future__ import annotations

import re
from datetime import date

# filename tokens that identify each section's syllabus (Phase-0 probe #10
# confirms the real KB names; the local sources are e.g.
# "Syllabus_SPRING_2026_Flipped.md", "SyllabusSPRING_2026_In-Person.md").
MODALITY_TOKENS: dict[str, tuple[str, ...]] = {
    "flipped": ("flipped",),
    "traditional": ("in-person", "inperson", "in person"),
    "indy": ("in-person", "inperson", "in person"),   # Indy uses the in-person syllabus
    "online": ("online",),
    "winter": ("winter",),
    "summer": ("summer",),
}

# Winter/Summer are self-identifying sessions; other sections must also match
# the current term's season + year.
SESSION_MODALITIES = {"winter", "summer"}


def _norm(s: str) -> str:
    return re.sub(r"[\s_]+", "-", s.strip().lower())


def term_tokens(term: str) -> list[str]:
    """"SPRING 2026" -> ["spring", "2026"]."""
    return [t for t in re.split(r"[\s_\-]+", term.strip().lower()) if t]


def term_for_date(d: date) -> str:
    """Rough academic-term mapping — a SAFETY NET only, never authoritative."""
    y, m, day = d.year, d.month, d.day
    if m == 12:
        return f"WINTER {y}"
    if m <= 4 or (m == 5 and day < 15):
        return f"SPRING {y}"
    if (m == 5 and day >= 15) or m in (6, 7, 8):
        return f"SUMMER {y}"
    return f"FALL {y}"


def syllabus_matches(filename: str, term: str, modality: str | None) -> bool:
    """True if a syllabus source file is the right (term, modality)."""
    base = _norm(filename)
    if "syllab" not in base:
        return False
    mod = (modality or "").lower()
    mod_toks = MODALITY_TOKENS.get(mod, ())
    if mod_toks and not any(_norm(t) in base for t in mod_toks):
        return False
    if mod in SESSION_MODALITIES:
        return True  # season token already disambiguates the term
    return all(tok in base for tok in term_tokens(term))


def _source_name(passage) -> str:
    meta = getattr(passage, "meta", {}) or {}
    return str(meta.get("name") or meta.get("source") or meta.get("file") or "")


def select_syllabus_passages(passages, term: str, modality: str | None) -> list:
    """Keep only passages from the current-term, this-section syllabus."""
    return [p for p in passages if syllabus_matches(_source_name(p), term, modality)]
