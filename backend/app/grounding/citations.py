"""Citation contract + link linting.

The model cites [n]; the app maps n → passage → real URL. Any URL the model
emits anyway is removed unless it's in the course-map allowlist (defense in
depth — the prompt already forbids URLs).
"""

from __future__ import annotations

import re

from ..course_map.resolver import CourseMapResolver
from .retrieve import Passage

_MARKER_RE = re.compile(r"\[(\d{1,2})\]")
# case-insensitive: HTTP://… / Https://… must be caught too, else the frontend
# (which matches schemes case-insensitively) renders it as a live link.
_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)
_BEYOND_RE = re.compile(r">>>\s*BEYOND STAT 350 SCOPE.*?<<<", re.S)
_CATALOG_CODE_RE = re.compile(r"\bSTAT\s*(41600|41700|51200|51400|42000|51300)\b")

REMOVED_PLACEHOLDER = "[link removed — see Sources]"


def extract_markers(text: str) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for m in _MARKER_RE.finditer(text):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def validate_markers(text: str, passages: list[Passage]) -> tuple[list[int], list[int]]:
    """Returns (resolved_markers, unresolved_markers). Unresolved = the model
    cited a passage number that doesn't exist — the prompt-quality tripwire."""
    valid = {p.n for p in passages}
    markers = extract_markers(text)
    return ([n for n in markers if n in valid],
            [n for n in markers if n not in valid])


def lint_links(text: str, resolver: CourseMapResolver) -> tuple[str, list[str]]:
    removed: list[str] = []

    def _sub(m: re.Match) -> str:
        url = m.group(0)
        if resolver.is_allowed_url(url):
            return url
        removed.append(url)
        return REMOVED_PLACEHOLDER

    return _URL_RE.sub(_sub, text), removed


def detect_beyond_scope(text: str) -> bool:
    return bool(_BEYOND_RE.search(text))


def catalog_card_for(text: str, resolver: CourseMapResolver) -> dict | None:
    """When the model used the BEYOND banner and named a catalog course, the
    app attaches the (correct) catalog link."""
    if not detect_beyond_scope(text):
        return None
    m = _CATALOG_CODE_RE.search(text)
    if not m:
        return None
    code_num = m.group(1)
    for course in resolver.map.catalog_courses:
        if code_num in course.code.replace(" ", ""):
            return {"kind": "catalog", "title": f"{course.code}: {course.title}",
                    "url": course.url, "meta": "Purdue catalog — go deeper"}
    return None


def citations_payload(passages: list[Passage]) -> list[dict]:
    items = []
    for p in passages:
        items.append({
            "n": p.n,
            "source": p.collection,
            "title": (p.resolved.title if p.resolved else p.collection.title()),
            "snippet": p.text[:240].strip(),
            "similarity": round(p.similarity, 3),
            "url": p.resolved.url if p.resolved else None,
        })
    return items


def resources_payload(passages: list[Passage], resolver: CourseMapResolver,
                      extra_sections=None) -> list[dict]:
    sections = []
    seen: set[str] = set()
    for p in passages:
        sec = p.resolved.section if p.resolved else None
        if sec and sec.number not in seen:
            seen.add(sec.number)
            sections.append(sec)
    for sec in extra_sections or []:
        if sec.number not in seen:
            seen.add(sec.number)
            sections.append(sec)
    cards = resolver.cards_for_sections(sections[:4])
    return [c.to_dict() for c in cards]
