"""Deterministic intent router — zero LLM cost.

Intents:
  resource_lookup   "link to 4.3", "worksheet 5", "CLT video"  -> answered from
                    the course map, NO LLM call
  syllabus_schedule syllabus/schedule/deadline/policy questions -> course-map
                    links (+ modality prompt if unknown), NO LLM call
  exam_info         "what's on exam 2"                          -> course-map
                    template, NO LLM call
  smalltalk         greetings/thanks                            -> canned reply
  concept_question  everything else                             -> full pipeline
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..course_map.resolver import CourseMapResolver
from ..course_map.schema import SectionEntry

_SMALLTALK_RE = re.compile(
    r"^\s*((hi|hello|hey|yo)( there| everyone| bot)?|thanks?( a lot| so much)?|"
    r"thank you|ty|good (morning|afternoon|evening)|"
    r"who are you|what can you do|help)\s*[!.?]*\s*$", re.I)

_SYLLABUS_RE = re.compile(
    r"\b(syllabus|schedule|deadline|due date|office hours?|grading|grade breakdown|"
    r"late\s+(work|policy|homework|assignment|submission)|polic(y|ies)|attendance|"
    r"when is|what day|exam date|"
    r"how much (is|are).*(worth|count)|weighted?|make.?up|makeup|"
    r"drop(ped|s)?\b.{0,20}\b(quiz|quizzes|grade|score|lowest)|"
    r"lowest\s+(quiz|quizzes|grade|score)|"
    r"how many (exams|quizzes|midterms)|final exam|participation|edfinity|proctor)\b", re.I)

# Pure "where is it / give me the link" requests -> just return links.
_SYLLABUS_LOCATE_RE = re.compile(
    r"\b(where('?s| is| can i find)|link|url|pdf|download|send me|give me|pull up|"
    r"show me|copy of|get me)\b.{0,30}\b(syllabus|schedule)\b|"
    r"\b(syllabus|schedule)\b.{0,20}\b(link|url|pdf|page|website)\b", re.I)

_EXAM_RE = re.compile(
    r"\b(what(?:'s| is| will be)? (?:covered )?on (?:the )?(exam\s*[123]|final|midterm\s*[12])|"
    r"(exam\s*[123]|final exam|midterm\s*[12]) cover|study (?:guide )?for (?:the )?"
    r"(exam\s*[123]|final|midterm\s*[12]))\b", re.I)

_RESOURCE_RE = re.compile(
    r"\b(link|url|page|where (?:is|can i find)|show me|open|pull up|give me)\b", re.I)
_WORKSHEET_RE = re.compile(r"\bworksheets?\s*#?\s*(\d{1,2})\b", re.I)
# Section numbers are 1.x–13.x. Constrain the chapter part to 1–13 so a
# STATISTICAL decimal — an alpha level (0.05), a p-value, a test statistic —
# is NOT misread as a section reference and does not force resource_lookup on a
# genuine problem-solving question ("test at alpha=0.05 …").
_SECTION_REF_RE = re.compile(r"\b(?:section|lecture|chapter)?\s*((?:1[0-3]|[1-9])\.\d{1,2})\b")
_CHAPTER_REF_RE = re.compile(r"\bchapter\s*(\d{1,2})\b", re.I)
_VIDEO_RE = re.compile(r"\b(video|watch|recording)\b", re.I)
_SIM_RE = re.compile(r"\b(simulation|simulator|shiny|interactive|applet)\b", re.I)

_QUESTION_WORDS_RE = re.compile(
    r"\b(why|how|explain|what does|what is|when do|difference|confused|understand|"
    r"help me|solve|compute|calculate|interpret|prove)\b", re.I)


@dataclass
class Route:
    intent: str
    sections: list[SectionEntry] = field(default_factory=list)
    worksheet: int | None = None
    chapter: int | None = None
    exam_key: str | None = None
    wants_video: bool = False
    wants_simulation: bool = False
    needs_modality: bool = False


def route(message: str, resolver: CourseMapResolver,
          modality: str | None = None) -> Route:
    msg = message.strip()
    sections = resolver.sections_for_text(msg)

    if _SMALLTALK_RE.match(msg):
        return Route(intent="smalltalk")

    exam_m = _EXAM_RE.search(msg)
    if exam_m:
        blob = exam_m.group(0).lower()
        num = re.search(r"[123]", blob)
        key = "final" if "final" in blob else (num.group(0) if num else "1")
        if key == "3":
            key = "final"
        return Route(intent="exam_info", exam_key=key, sections=sections)

    if _SYLLABUS_RE.search(msg):
        if _SYLLABUS_LOCATE_RE.search(msg):
            # pure "where is the syllabus / link to the schedule" -> links only
            return Route(intent="syllabus_schedule", sections=sections,
                         needs_modality=modality is None)
        # a policy/logistics question -> quote from the syllabus (needs modality)
        return Route(intent="syllabus_content", sections=sections,
                     needs_modality=modality is None)

    ws_m = _WORKSHEET_RE.search(msg)
    sec_m = _SECTION_REF_RE.search(msg)
    ch_m = _CHAPTER_REF_RE.search(msg)
    # Pure lookup: mentions a concrete artifact (worksheet/section/chapter/
    # simulation — or a keyword-matched topic asked for as a video/sim) plus
    # a lookup verb, and doesn't read like a conceptual question.
    has_artifact = bool(ws_m or sec_m or ch_m or _SIM_RE.search(msg)
                        or (sections and (_VIDEO_RE.search(msg)
                                          or _SIM_RE.search(msg))))
    if (has_artifact
            and (_RESOURCE_RE.search(msg) or _VIDEO_RE.search(msg) or _SIM_RE.search(msg))
            and not _QUESTION_WORDS_RE.search(msg)):
        return Route(
            intent="resource_lookup",
            sections=sections,
            worksheet=int(ws_m.group(1)) if ws_m else None,
            chapter=int(ch_m.group(1)) if ch_m else None,
            wants_video=bool(_VIDEO_RE.search(msg)),
            wants_simulation=bool(_SIM_RE.search(msg)),
        )

    return Route(intent="concept_question", sections=sections,
                 worksheet=int(ws_m.group(1)) if ws_m else None)
