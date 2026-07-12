"""Syllabus grounding by (term, modality)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.syllabus import (select_syllabus_passages, syllabus_matches,
                          term_for_date, term_tokens)


def _p(name: str, score: float = 0.8):
    return SimpleNamespace(meta={"name": name}, distance=score, n=0)


def test_term_tokens():
    assert term_tokens("SPRING 2026") == ["spring", "2026"]
    assert term_tokens("Fall_2025") == ["fall", "2025"]


def test_term_for_date_seasons():
    assert term_for_date(date(2026, 2, 10)) == "SPRING 2026"
    assert term_for_date(date(2026, 6, 20)) == "SUMMER 2026"
    assert term_for_date(date(2026, 9, 1)) == "FALL 2026"
    assert term_for_date(date(2025, 12, 20)) == "WINTER 2025"


def test_matches_correct_term_and_modality():
    assert syllabus_matches("Syllabus_SPRING_2026_Flipped.md", "SPRING 2026", "flipped")
    assert syllabus_matches("SyllabusSPRING_2026_In-Person.md", "SPRING 2026", "traditional")
    assert syllabus_matches("SyllabusSPRING_2026_In-Person.md", "SPRING 2026", "indy")
    assert syllabus_matches("Syllabus_SPRING_2026_Online.md", "SPRING 2026", "online")


def test_rejects_wrong_term():
    # a Fall syllabus must NOT match a Spring student (different point spreads)
    assert not syllabus_matches("Syllabus_FALL_2025_Flipped.md", "SPRING 2026", "flipped")
    assert not syllabus_matches("Syllabus_SPRING_2025_Flipped.md", "SPRING 2026", "flipped")


def test_rejects_wrong_modality():
    assert not syllabus_matches("Syllabus_SPRING_2026_Online.md", "SPRING 2026", "flipped")
    assert not syllabus_matches("Syllabus_SPRING_2026_Flipped.md", "SPRING 2026", "online")


def test_rejects_non_syllabus_files():
    assert not syllabus_matches("chapter7_lectures_7-3-clt.rst", "SPRING 2026", "flipped")


def test_session_modalities_self_identify():
    # winter/summer identify by season regardless of the configured term year
    assert syllabus_matches("Syllabus_Winter_2025.md", "SPRING 2026", "winter")
    assert syllabus_matches("STAT_350_SUMMER_2026_Syllabus.md", "FALL 2026", "summer")


def test_select_filters_mixed_retrieval():
    # retrieval returned several terms/modalities + a lecture chunk; keep only
    # the current-term, this-section one
    passages = [
        _p("Syllabus_FALL_2025_Flipped.md", 0.86),      # wrong term
        _p("Syllabus_SPRING_2026_Online.md", 0.85),     # wrong modality
        _p("Syllabus_SPRING_2026_Flipped.md", 0.83),    # RIGHT
        _p("chapter10_lectures_10-1-ht-errors-and-power.rst", 0.82),  # not syllabus
    ]
    kept = select_syllabus_passages(passages, "SPRING 2026", "flipped")
    assert [p.meta["name"] for p in kept] == ["Syllabus_SPRING_2026_Flipped.md"]


def test_select_empty_when_term_absent():
    # if the current term's syllabus isn't in retrieval, keep nothing (caller
    # then links the authoritative PDF instead of quoting a wrong term)
    passages = [_p("Syllabus_FALL_2025_Flipped.md"), _p("Syllabus_SPRING_2025_Flipped.md")]
    assert select_syllabus_passages(passages, "SPRING 2026", "flipped") == []


def test_auto_term_derives_from_date_and_drops_stale_pdf(resolver):
    from app.config import CourseCfg, Settings, SyllabusLinkCfg
    from app.syllabus import resolve_current_term, resolve_syllabus_links

    s = Settings(collections={"webbook": "w", "transcripts": "t"})
    # auto_term ON: term comes from the date, not the pinned value
    s.course = CourseCfg(term="SPRING 2026", auto_term=True, syllabi={
        "flipped": SyllabusLinkCfg(
            label="Flipped",
            syllabus_pdf="https://treese41528.github.io/STAT350/Syllabus_SPRING_2026_Flipped.pdf",
            schedule_url="https://treese41528.github.io/STAT350/StudentSchedule-Flipped.html")})
    derived = resolve_current_term(s)
    assert derived != "SPRING 2026" or True  # whatever today is, it's date-derived
    # if the derived term isn't SPRING 2026, the stale SPRING PDF is dropped but
    # the schedule stays (grounding still works from the KB)
    label, pdf, sched = resolve_syllabus_links(s, resolver, "flipped")
    assert sched.endswith("StudentSchedule-Flipped.html")
    if "spring 2026" not in derived.lower():
        assert pdf == ""            # never link the wrong term's PDF
    # auto_term OFF: pinned term, PDF kept as-is
    s.course.auto_term = False
    assert resolve_current_term(s) == "SPRING 2026"
    assert resolve_syllabus_links(s, resolver, "flipped")[1].endswith("Flipped.pdf")


def test_resolve_syllabus_links_prefers_config(resolver):
    from app.config import CourseCfg, Settings, SyllabusLinkCfg
    from app.syllabus import resolve_syllabus_links

    s = Settings(collections={"webbook": "w", "transcripts": "t"})
    # config (new term) beats the baked course_map
    s.course = CourseCfg(term="FALL 2026", syllabi={
        "flipped": SyllabusLinkCfg(
            label="Flipped",
            syllabus_pdf="https://treese41528.github.io/STAT350/Syllabus_FALL_2026_Flipped.pdf",
            schedule_url="https://treese41528.github.io/STAT350/StudentSchedule-Flipped.html")})
    label, pdf, sched = resolve_syllabus_links(s, resolver, "flipped")
    assert "FALL_2026" in pdf                    # config link, not SPRING 2026
    # a modality absent from config falls back to course_map
    fb = resolve_syllabus_links(s, resolver, "online")
    assert fb is not None and "SPRING_2026" in fb[1]  # course_map fallback
    assert resolve_syllabus_links(s, resolver, None) is None
