"""Runtime course-map lookups. Everything is deterministic; nothing here can
hallucinate. The model never types URLs — this module supplies them.

The central join: a retrieved chunk's file metadata → published page URL.
Webbook chunks are .rst sources whose basenames match lecture URL basenames
("4-3-conditional-probability"). Fallback chain (Phase 0 probe #1 decides how
often each is needed): exact basename → section-number pattern → fuzzy
basename → fuzzy title → None (caller degrades to a chapter/hub link).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path

from .schema import (CatalogCourse, ChapterEntry, CourseMap, ExamEntry,
                     SectionEntry, SyllabusEntry, WorksheetEntry)

_EXTENSIONS = (".rst", ".txt", ".md", ".html", ".pdf", ".vtt", ".srt", ".docx")
# Open WebUI file uploads are often prefixed "uuid_" or timestamped.
_PREFIX_RE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[_-]|\d{8,}[_-])",
    re.I)
_SECTION_NUM_RE = re.compile(r"(\d{1,2})[.\-_](\d{1,2})")


@dataclass(frozen=True)
class ResolvedSource:
    collection: str                      # webbook | transcript
    title: str
    url: str | None
    video_url: str | None = None
    section: SectionEntry | None = None
    match: str = "exact"                 # exact|number|fuzzy|title|chapter|none


@dataclass
class ResourceCard:
    kind: str                            # lecture|video|worksheet|simulation|syllabus|schedule|exam|catalog
    title: str
    url: str
    meta: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "title": self.title, "url": self.url,
                "meta": self.meta}


def normalize_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    base = _PREFIX_RE.sub("", base)
    for ext in _EXTENSIONS:
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    return base


class CourseMapResolver:
    def __init__(self, course_map: CourseMap):
        self.map = course_map
        self._by_rst: dict[str, SectionEntry] = {}
        self._by_number: dict[str, SectionEntry] = {}
        self._keyword_index: dict[str, list[SectionEntry]] = {}
        self._all_urls: set[str] = set()
        self._index()

    @classmethod
    def from_file(cls, path: str | Path) -> "CourseMapResolver":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(CourseMap(**data))

    def _index(self) -> None:
        for ch in self.map.chapters.values():
            self._all_urls.add(ch.index_url)
            for sec in ch.sections.values():
                self._by_rst[sec.rst_basename.lower()] = sec
                self._by_number[sec.number] = sec
                self._all_urls.add(sec.lecture_url)
                if sec.video:
                    self._all_urls.add(sec.video.url)
                for v in sec.extra_videos:
                    self._all_urls.add(v.url)
                for kw in sec.keywords:
                    self._keyword_index.setdefault(kw.lower(), []).append(sec)
        for ws in self.map.worksheets.values():
            self._all_urls.add(ws.url)
        for sim in self.map.simulations.values():
            self._all_urls.add(sim.url)
        for syl in self.map.syllabi.values():
            self._all_urls.update({syl.syllabus_pdf, syl.schedule_url})
        for cat in self.map.catalog_courses:
            self._all_urls.add(cat.url)
        for v in self.map.videos.values():
            self._all_urls.add(v.url)
        self._all_urls.update(u for u in self.map.hubs.values() if u)
        self._all_urls.discard("")

    # ---- basic lookups -------------------------------------------------------

    def lookup_section(self, number: str) -> SectionEntry | None:
        return self._by_number.get(number.strip())

    def lookup_chapter(self, number: int) -> ChapterEntry | None:
        return self.map.chapters.get(str(number))

    def chapter_of(self, section: SectionEntry) -> ChapterEntry | None:
        return self.lookup_chapter(int(section.number.split(".")[0]))

    def lookup_worksheet(self, number: int) -> WorksheetEntry | None:
        return self.map.worksheets.get(str(number))

    def worksheets_for_chapter(self, chapter: int) -> list[WorksheetEntry]:
        return [w for w in self.map.worksheets.values() if chapter in w.chapters]

    def syllabus_for(self, modality: str) -> SyllabusEntry | None:
        return self.map.syllabi.get(modality.strip().lower())

    def exam_info(self, key: str) -> ExamEntry | None:
        key = key.strip().lower().replace("exam", "").strip()
        if key in {"3", "final exam"}:
            key = "final"
        return self.map.exams.get(key)

    def catalog_for_topic(self, text: str) -> CatalogCourse | None:
        text_l = text.lower()
        best, best_hits = None, 0
        for course in self.map.catalog_courses:
            hits = sum(1 for t in course.topics if t.lower() in text_l)
            if hits > best_hits:
                best, best_hits = course, hits
        return best

    # ---- keyword routing ------------------------------------------------------

    def sections_for_text(self, text: str, limit: int = 3) -> list[SectionEntry]:
        """Rank sections by keyword hits — used for resource suggestions and
        the refusal path's 'closest material' links."""
        text_l = " " + re.sub(r"[^\w\s.-]", " ", text.lower()) + " "
        scores: dict[str, float] = {}
        for kw, secs in self._keyword_index.items():
            if f" {kw} " in text_l or (len(kw) > 4 and kw in text_l):
                for sec in secs:
                    # longer keywords are more specific
                    scores[sec.number] = scores.get(sec.number, 0) + len(kw)
        # explicit section references ("section 4.3", "10.2") win outright
        for m in re.finditer(r"\b(\d{1,2}\.\d{1,2})\b", text):
            if m.group(1) in self._by_number:
                scores[m.group(1)] = scores.get(m.group(1), 0) + 1000
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
        return [self._by_number[n] for n, _ in ranked]

    # ---- retrieval-chunk → URL join --------------------------------------------

    def resolve_webbook(self, meta: dict) -> ResolvedSource:
        name = str(meta.get("name") or meta.get("source") or meta.get("title")
                   or meta.get("file") or "")
        base = normalize_filename(name)
        # Gateway filenames are the repo-relative path with '/' -> '_'
        # (Phase 0 probe #1), e.g. "chapter7_lectures_7-3-clt" or
        # "worksheets_worksheet_materials_worksheet11". Candidate basenames:
        # the whole string and the tail after the last path-join underscore
        # (lecture basenames themselves use hyphens, never underscores).
        candidates = [base]
        if "_" in base:
            candidates.append(base.rsplit("_", 1)[-1])

        # a worksheet source file → its worksheet page
        wm = re.search(r"worksheet[_]?(\d{1,2})(?:\D|$)", base)
        if wm and (ws := self.map.worksheets.get(str(int(wm.group(1))))):
            return ResolvedSource("webbook", f"Worksheet {ws.number}: {ws.title}",
                                  ws.url, None, None, "exact")

        sec = None
        match = "exact"
        for cand in candidates:
            if cand in self._by_rst:
                sec, match = self._by_rst[cand], "exact"
                break
        if sec is None and base:
            m = _SECTION_NUM_RE.search(base)
            if m and f"{int(m.group(1))}.{int(m.group(2))}" in self._by_number:
                sec = self._by_number[f"{int(m.group(1))}.{int(m.group(2))}"]
                match = "number"
        if sec is None and base:
            for cand in candidates:
                close = get_close_matches(cand, list(self._by_rst), n=1, cutoff=0.75)
                if close:
                    sec, match = self._by_rst[close[0]], "fuzzy"
                    break
        if sec is None and base:
            titles = {s.title.lower(): s for s in self._by_number.values()}
            close = get_close_matches(candidates[-1].replace("-", " "),
                                      list(titles), n=1, cutoff=0.6)
            if close:
                sec, match = titles[close[0]], "title"

        if sec is not None:
            return ResolvedSource(
                collection="webbook",
                title=f"{sec.number} {sec.title}",
                url=sec.lecture_url,
                video_url=sec.video.url if sec.video else None,
                section=sec, match=match)
        # chapter-level fallback: "chapter7-something.rst"
        m = re.match(r"^chapter[\s_-]?(\d{1,2})", base)
        if m and (ch := self.lookup_chapter(int(m.group(1)))):
            return ResolvedSource("webbook", ch.title, ch.index_url, None,
                                  None, "chapter")
        return ResolvedSource("webbook", name or "Course webbook",
                              self.map.hubs.get("home"), None, None, "none")

    def resolve_transcript(self, meta: dict) -> ResolvedSource:
        name = str(meta.get("name") or meta.get("source") or meta.get("title")
                   or meta.get("file") or "")
        base = normalize_filename(name)
        sec = None
        m = _SECTION_NUM_RE.search(base)
        if m:
            sec = self._by_number.get(f"{int(m.group(1))}.{int(m.group(2))}")
        if sec is None and base:
            titles = {s.title.lower(): s for s in self._by_number.values()}
            close = get_close_matches(base.replace("-", " ").replace("_", " "),
                                      list(titles), n=1, cutoff=0.5)
            if close:
                sec = titles[close[0]]
        if sec is not None:
            video_url = sec.video.url if sec.video else None
            return ResolvedSource(
                collection="transcript",
                title=f"Lecture {sec.number}: {sec.title}",
                url=video_url or sec.lecture_url,
                video_url=video_url, section=sec,
                match="number" if m else "title")
        return ResolvedSource("transcript", name or "Lecture transcript",
                              self.map.hubs.get("video_home"), None, None, "none")

    # ---- resource cards ----------------------------------------------------------

    def cards_for_sections(self, sections: list[SectionEntry],
                           include_worksheets: bool = True,
                           include_simulations: bool = True) -> list[ResourceCard]:
        cards: list[ResourceCard] = []
        seen: set[str] = set()
        sim_keys: list[str] = []
        for sec in sections:
            ch = self.chapter_of(sec)
            meta = f"Chapter {sec.number.split('.')[0]} · §{sec.number}"
            if sec.lecture_url not in seen:
                seen.add(sec.lecture_url)
                cards.append(ResourceCard("lecture", f"{sec.number} {sec.title}",
                                          sec.lecture_url, meta))
            if sec.video and sec.video.url not in seen:
                seen.add(sec.video.url)
                cards.append(ResourceCard("video", f"Video: {sec.number} {sec.title}",
                                          sec.video.url, meta))
            if include_worksheets and ch:
                for ws in self.worksheets_for_chapter(ch.number)[:2]:
                    if ws.url not in seen:
                        seen.add(ws.url)
                        cards.append(ResourceCard(
                            "worksheet", f"Worksheet {ws.number}: {ws.title}",
                            ws.url, f"Chapter {ch.number}"))
            # simulations by topic
            n = sec.number
            if n.startswith("7."):
                sim_keys.append("clt")
            elif n.startswith("9."):
                sim_keys.append("ci")
            elif n.startswith("10."):
                sim_keys.append("power")
        if include_simulations:
            for key in sim_keys:
                sim = self.map.simulations.get(key)
                if sim and sim.url not in seen:
                    seen.add(sim.url)
                    cards.append(ResourceCard("simulation", sim.title, sim.url,
                                              "Interactive simulation"))
        return cards

    # ---- link linting ---------------------------------------------------------------

    def is_allowed_url(self, url: str) -> bool:
        url = url.rstrip(").,;")
        if url in self._all_urls:
            return True
        m = re.match(r"https?://([^/]+)/", url + "/", re.IGNORECASE)
        return bool(m and m.group(1).lower() in
                    {h.lower() for h in self.map.allowlist_hosts})

    @property
    def all_urls(self) -> frozenset[str]:
        return frozenset(self._all_urls)
