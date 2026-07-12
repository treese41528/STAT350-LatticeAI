"""Course-map parity + resolver correctness. The parity test is the guard
that every URL the legacy prompt promised is still reachable via the map."""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROMPT = BACKEND.parent.parent / "system_prompt.txt"

# FALL 2025 syllabi are deliberately superseded by SPRING 2026 versions.
SUPERSEDED = {"Syllabus%20FALL%202025"}


def _walk_urls(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_urls(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_urls(v)
    elif isinstance(obj, str) and obj.startswith("https://"):
        yield obj


def test_every_prompt_url_is_in_the_map(resolver):
    prompt_urls = {u.rstrip('.,)"')
                   for u in re.findall(r"https://\S+", PROMPT.read_text(encoding="utf-8"))}
    prompt_urls = {u for u in prompt_urls
                   if "worksheet#" not in u  # template line, not a URL
                   and not any(s in u for s in SUPERSEDED)}
    map_urls = set(_walk_urls(resolver.map.model_dump()))
    missing = prompt_urls - map_urls
    assert not missing, f"URLs lost from course map: {sorted(missing)}"


def test_every_map_url_passes_its_own_allowlist(resolver):
    for url in resolver.all_urls:
        assert resolver.is_allowed_url(url), url


def test_video_attachments_handle_source_quirks(resolver):
    # primary videos keep the legacy viewer anchor for reference, including the
    # swapped 9.2/9.3 anchors preserved verbatim from the source
    assert resolver.lookup_section("9.2").video.anchor == "#051"
    assert resolver.lookup_section("9.3").video.anchor == "#050"
    assert resolver.lookup_section("12.4").video.anchor == "#073"
    # Welch sub-video rides section 11.4 as an extra (direct YouTube)
    s114 = resolver.lookup_section("11.4")
    assert len(s114.extra_videos) == 1
    assert "npooled" in (s114.extra_videos[0].title or "")
    # sub-videos 6.4.1–6.4.3 attach to 6.4
    assert len(resolver.lookup_section("6.4").extra_videos) == 3


def test_every_section_has_a_direct_youtube_video(resolver):
    # the Video Viewer's #anchors don't deep-link, so every section's primary
    # video must be a DIRECT YouTube watch link (extracted from the rst embeds)
    for ch in resolver.map.chapters.values():
        for sec in ch.sections.values():
            assert sec.video is not None, f"section {sec.number} lost its video"
            assert "youtube.com/watch?v=" in sec.video.url, \
                f"section {sec.number} video is not a direct YouTube link: {sec.video.url}"
            for v in sec.extra_videos:
                assert "youtube.com/watch?v=" in v.url


def test_url_for_rst_fallback_chain(resolver):
    exact = resolver.resolve_webbook({"name": "4-3-conditional-probability.rst"})
    assert exact.match == "exact"
    assert exact.section.number == "4.3"

    prefixed = resolver.resolve_webbook(
        {"name": "0e1f2a3b-1111-2222-3333-444455556666_7-3-clt.rst"})
    assert prefixed.section.number == "7.3"

    number_only = resolver.resolve_webbook({"name": "10-2_something_else.txt"})
    assert number_only.match == "number"
    assert number_only.section.number == "10.2"

    fuzzy = resolver.resolve_webbook({"name": "4-3-conditional-probabilty.rst"})
    assert fuzzy.section is not None and fuzzy.section.number == "4.3"

    nothing = resolver.resolve_webbook({"name": "zzz-unrelated-file.pdf"})
    assert nothing.match in ("none", "chapter")
    assert nothing.url  # still links somewhere safe (hub)


def test_webbook_underscore_path_filenames(resolver):
    # Real gateway metadata: repo path with '/' -> '_' (Phase 0 probe #1).
    lecture = resolver.resolve_webbook({"name": "chapter7_lectures_7-3-clt.rst"})
    assert lecture.match == "exact" and lecture.section.number == "7.3"

    # worksheet source file → worksheet page (not a section)
    ws = resolver.resolve_webbook(
        {"name": "worksheets_worksheet_materials_worksheet11.rst"})
    assert ws.section is None and "worksheet11.html" in ws.url
    assert "Worksheet 11" in ws.title

    # uuid-prefixed filename field
    prefixed = resolver.resolve_webbook(
        {"name": "chapter9_lectures_9-2-ci-sigma-known.rst",
         "filename": "2f73bbd9-c810-4fbb-9068-4792ae1029d8_chapter9_lectures_9-2-ci-sigma-known.rst"})
    assert prefixed.section.number == "9.2"


def test_transcript_srt_filenames(resolver):
    # real transcript naming from the gateway; transcript hits now deep-link to
    # the actual YouTube video, not the general Video Viewer
    hit = resolver.resolve_transcript(
        {"name": "STAT 350 -  Chapter 7.3 Central Limit Theorem CLT.srt"})
    assert hit.section.number == "7.3"
    assert "youtube.com/watch?v=" in hit.video_url


def test_transcript_resolution(resolver):
    hit = resolver.resolve_transcript({"name": "lecture_7-3_transcript.vtt"})
    assert hit.section.number == "7.3"
    assert hit.video_url and "youtube.com/watch?v=" in hit.video_url
    miss = resolver.resolve_transcript({"name": "random_audio.vtt"})
    assert miss.url  # video home fallback


def test_lookup_helpers(resolver):
    assert resolver.lookup_worksheet(3).title.startswith("Conditional")
    assert resolver.worksheets_for_chapter(4) and \
        {w.number for w in resolver.worksheets_for_chapter(4)} == {2, 3, 4}
    assert resolver.exam_info("2").chapters == [7, 8, 9, 10, 11]
    assert resolver.exam_info("final").chapters == [12, 13]
    assert resolver.syllabus_for("winter").schedule_url.endswith(
        "StudentSchedule-Asynchronous-Winter.html")
    # SPRING 2026 syllabi preferred over FALL 2025
    assert "SPRING" in resolver.syllabus_for("flipped").syllabus_pdf


def test_sections_for_text(resolver):
    secs = resolver.sections_for_text("I'm confused about the central limit theorem")
    assert any(s.number == "7.3" for s in secs)
    explicit = resolver.sections_for_text("can you explain section 10.2 to me")
    assert explicit and explicit[0].number == "10.2"


def test_link_allowlist(resolver):
    assert resolver.is_allowed_url(
        "https://treese41528.github.io/STAT350/Website/chapter4/index.html")
    assert resolver.is_allowed_url("https://catalog.purdue.edu/anything")
    assert not resolver.is_allowed_url("https://evil.example.com/page")
    assert not resolver.is_allowed_url("https://en.wikipedia.org/wiki/P-value")
