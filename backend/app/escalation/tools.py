"""The 11 formerly-aspirational tools, made real.

Each wraps the deterministic course-map resolver with the SDK's @tool
decorator and returns ToolResult with Source objects, so URLs flow into
AgentResult.sources and re-enter the same citation contract as the default
path. Tools can't hallucinate — they read course_map.json.
"""

from __future__ import annotations

from datetime import datetime, timezone

from genai_studio.agents import Source, ToolResult, tool

from ..course_map.resolver import CourseMapResolver
from ..syllabus import term_for_date


def _src(title: str, url: str | None, snippet: str = "") -> Source:
    return Source(id=url or title, title=title, url=url, snippet=snippet[:200])


def make_course_tools(resolver: CourseMapResolver, term: str = "") -> list:
    """Build the course-structure tool set bound to the resolver.

    `term` is the authoritative current term (config `course.term`); it grounds
    syllabus/date answers so the agent never quotes a different semester.
    """

    @tool(name="get_current_term",
          description="Get the current academic term (semester) and today's "
                      "date — use this to ground any syllabus, schedule, or "
                      "deadline answer in the right semester.")
    def get_current_term() -> ToolResult:
        today = datetime.now(timezone.utc).date()
        derived = term_for_date(today)
        current = term or derived
        note = ""
        if term and term.lower() != derived.lower():
            note = (f" (config term {term!r} differs from the date-derived "
                    f"{derived!r} — trust the configured term)")
        return ToolResult(content=f"Current term: {current}. "
                                  f"Today: {today.isoformat()}.{note}")

    @tool(name="get_lecture_url",
          description="Get the course-website lecture page (and video) for a "
                      "section number like '4.3' or '10.2'.")
    def get_lecture_url(section: str) -> ToolResult:
        sec = resolver.lookup_section(section)
        if sec is None:
            return ToolResult(content=f"No section {section!r} in STAT 350. "
                                      "Sections run 1.1 through 13.4.")
        lines = [f"{sec.number} {sec.title}", f"Lecture page: {sec.lecture_url}"]
        sources = [_src(f"{sec.number} {sec.title}", sec.lecture_url)]
        if sec.video:
            lines.append(f"Video: {sec.video.url}")
            sources.append(_src(f"Video {sec.number}", sec.video.url))
        return ToolResult(content="\n".join(lines), sources=sources)

    @tool(name="get_chapter_overview",
          description="List every section of a chapter (1-13) with titles.")
    def get_chapter_overview(chapter: int) -> ToolResult:
        ch = resolver.lookup_chapter(int(chapter))
        if ch is None:
            return ToolResult(content=f"No chapter {chapter}. Chapters run 1-13.")
        lines = [f"Chapter {ch.number}: {ch.title}"]
        lines += [f"  {s.number} {s.title}" for s in ch.sections.values()]
        ws = resolver.worksheets_for_chapter(ch.number)
        if ws:
            lines.append("Practice: " + ", ".join(f"Worksheet {w.number}" for w in ws))
        return ToolResult(content="\n".join(lines),
                          sources=[_src(f"Chapter {ch.number}: {ch.title}",
                                        ch.index_url)])

    @tool(name="get_worksheet",
          description="Get a practice worksheet (1-22) with its topic and link.")
    def get_worksheet(worksheet_number: int) -> ToolResult:
        ws = resolver.lookup_worksheet(int(worksheet_number))
        if ws is None:
            return ToolResult(content=f"No worksheet {worksheet_number}. "
                                      "Worksheets run 1-22.")
        chs = ", ".join(map(str, ws.chapters)) or "?"
        return ToolResult(
            content=f"Worksheet {ws.number}: {ws.title} (chapters {chs})",
            sources=[_src(f"Worksheet {ws.number}: {ws.title}", ws.url)])

    @tool(name="get_simulation",
          description="Get an interactive simulation link: 'clt', 'ci', or 'power'.")
    def get_simulation(simulation_type: str) -> ToolResult:
        sim = resolver.map.simulations.get(simulation_type.strip().lower())
        if sim is None:
            return ToolResult(content="Simulations available: clt, ci, power.")
        return ToolResult(content=f"{sim.title} — use for {sim.when}.",
                          sources=[_src(sim.title, sim.url)])

    @tool(name="get_syllabus_and_schedule",
          description="Get syllabus PDF + schedule page for a section modality: "
                      "'flipped', 'traditional', 'indy', 'online', or 'winter'.")
    def get_syllabus_and_schedule(modality: str) -> ToolResult:
        syl = resolver.syllabus_for(modality)
        if syl is None:
            return ToolResult(content="Modalities: flipped, traditional, indy, "
                                      "online, winter.")
        return ToolResult(
            content=f"{syl.label}: syllabus and schedule linked.",
            sources=[_src(f"Syllabus — {syl.label}", syl.syllabus_pdf),
                     _src(f"Schedule — {syl.label}", syl.schedule_url)])

    @tool(name="get_exam_info",
          description="Get exam coverage: 1, 2, or 'final'.")
    def get_exam_info(exam: str) -> ToolResult:
        info = resolver.exam_info(str(exam))
        if info is None:
            return ToolResult(content="Exams: 1, 2, final.")
        lines = [info.label] + [f"- {t}" for t in info.topics]
        return ToolResult(content="\n".join(lines),
                          sources=[_src("Exams hub",
                                        resolver.map.hubs.get("exams"))])

    @tool(name="get_r_resources",
          description="Get the R / RStudio guide and function reference hub.")
    def get_r_resources() -> ToolResult:
        url = resolver.map.hubs.get("r_resources")
        return ToolResult(content="R/RStudio guides and function reference hub.",
                          sources=[_src("R & RStudio guides", url)])

    return [get_current_term, get_lecture_url, get_chapter_overview,
            get_worksheet, get_simulation, get_syllabus_and_schedule,
            get_exam_info, get_r_resources]
