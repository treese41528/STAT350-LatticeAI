"""One-time generator: parse the legacy 41KB system prompt into course_map.json.

Usage:
    python -m app.course_map.build_course_map ../system_prompt.txt data/course_map.json

The prompt's URL lines are regular enough for targeted regexes per section.
After generation the JSON is hand-verified once (parity test in
tests/unit/test_course_map.py checks every URL in the prompt landed in the
map) and becomes the source of truth; the prompt file is archived.

Known quirks preserved deliberately:
- Video anchors 9.2 -> #051 and 9.3 -> #050 are swapped relative to section
  order IN THE SOURCE. We copy them verbatim; if the live site disagrees, fix
  the JSON, not this parser.
- Worksheets 14-22 have no explicit URLs in the prompt, only the hub pattern;
  they're emitted with verified=false and pattern URLs to confirm against the
  live site (Phase 0 probe #9).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SITE = "https://treese41528.github.io/STAT350/"
URL_RE = re.compile(r"https://\S+")

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
    "introduction", "intro", "its", "are", "is", "when", "how", "what",
    "between", "&", "—", "-", "→",
}

# Hand-curated aliases so the keyword router finds sections students ask about
# in their own words. Extend freely; parity tests don't cover this.
ALIASES: dict[str, list[str]] = {
    "4.4": ["bayes", "bayes rule", "total probability"],
    "4.3": ["conditional", "given that"],
    "5.6": ["binomial"],
    "5.7": ["poisson"],
    "6.4": ["normal", "z score", "z-score", "bell curve"],
    "6.6": ["exponential"],
    "7.3": ["clt", "central limit theorem"],
    "9.2": ["confidence interval", "ci"],
    "9.3": ["sample size", "margin of error"],
    "10.1": ["type i", "type ii", "power", "alpha", "beta"],
    "10.4": ["p-value", "p value", "significance"],
    "11.3": ["pooled"],
    "11.4": ["unpooled", "welch"],
    "11.5": ["paired", "paired samples", "paired differences"],
    "12.1": ["anova"],
    "12.4": ["tukey", "multiple comparison", "family-wise"],
    "13.2": ["regression", "least squares", "r-squared"],
    "13.1": ["correlation", "scatter", "pearson"],
    "13.3": ["slope", "intercept", "f-test", "diagnostics"],
    "13.4": ["prediction interval", "robustness"],
}

MODALITY_SYLLABUS_LABELS = {
    "winter": "Syllabus Winter",
    "flipped": "Flipped",
    "traditional": "In-Person",
    "indy": "In-Person",          # Indy shares the in-person syllabus, own schedule
    "online": "Online",
}

MODALITY_SCHEDULE_LABELS = {
    "traditional": "Traditional Lecture\"",
    "indy": "Indianapolis",
    "flipped": "Flipped",
    "online": "Asynchronous Online",
    "winter": "Winter Session",
}


def _keywords(title: str, number: str) -> list[str]:
    words = [w.strip(".,()").lower() for w in re.split(r"[\s/—–-]+", title)]
    kws = [w for w in words if len(w) > 2 and w not in STOPWORDS]
    kws.extend(ALIASES.get(number, []))
    # dedupe, keep order
    seen: set[str] = set()
    out = []
    for k in kws:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _basename(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")


def _heading_pos(text: str, heading: str) -> int:
    """Position of a heading at line start (inline mentions don't count)."""
    m = re.search(rf"^{re.escape(heading)}", text, re.M)
    return m.start() if m else -1


_ABBREV = {
    "ci": "confidence interval", "cb": "confidence bound",
    "ht": "hypothesis test", "rvs": "random variables", "rv": "random variable",
    "pmfs": "probability mass functions", "pdfs": "probability density functions",
    "cdfs": "cumulative distribution functions", "clt": "central limit theorem",
    "slr": "simple linear regression", "sd": "standard deviation",
    "iqr": "interquartile range", "fwer": "family-wise error rates",
}


def _norm_title(title: str) -> str:
    words = re.split(r"[^\w]+", title.lower())
    return " ".join(_ABBREV.get(w, w) for w in words if w)


def _tokens(text: str) -> set[str]:
    # light stemming (strip plural 's') so "intervals" matches "interval"
    return {w.rstrip("s") for w in _norm_title(text).split()
            if len(w) > 2 and w not in STOPWORDS}


def _video_section_score(video_title: str, section: dict) -> float:
    """Char-ratio OR token containment (incl. section keywords) — short video
    titles like "Paired Samples" must still match long section titles."""
    from difflib import SequenceMatcher
    char_ratio = SequenceMatcher(None, _norm_title(video_title),
                                 _norm_title(section["title"])).ratio()
    vtok = _tokens(video_title)
    stok = _tokens(section["title"]) | {w.rstrip("s")
                                        for kw in section.get("keywords", [])
                                        for w in _norm_title(kw).split()}
    containment = len(vtok & stok) / max(1, len(vtok))
    return max(char_ratio, containment)


def build(prompt_text: str) -> dict:
    text = prompt_text

    # ---- chapters & sections (lecture URL map) -----------------------------
    chapters: dict[str, dict] = {}
    # Chapter heading: "4. Probability" followed (within a few lines) by
    # "Chapter page: URL"
    chap_iter = list(re.finditer(
        r"^(\d{1,2})\.\s+([^\n]+?)\s*\n+Chapter page:\s*(https://\S+)",
        text, re.M))
    for i, m in enumerate(chap_iter):
        num, title, index_url = int(m.group(1)), m.group(2).strip(), m.group(3)
        end = chap_iter[i + 1].start() if i + 1 < len(chap_iter) else \
            _heading_pos(text, "REFERENCE PAGES ON VIDEO VIEWER")
        block = text[m.end():end]
        sections: dict[str, dict] = {}
        for sm in re.finditer(
                r"^(\d{1,2}\.\d)\s+(.+?)\s*→\s*(https://\S+)", block, re.M):
            snum, stitle, surl = sm.group(1), sm.group(2).strip(), sm.group(3)
            sections[snum] = {
                "number": snum, "title": stitle, "lecture_url": surl,
                "rst_basename": _basename(surl), "video": None,
                "extra_videos": [], "keywords": _keywords(stitle, snum),
            }
        chapters[str(num)] = {"number": num, "title": title,
                              "index_url": index_url, "sections": sections}

    # ---- video viewer -------------------------------------------------------
    videos: dict[str, dict] = {}
    vstart = _heading_pos(text, "REFERENCE PAGES ON VIDEO VIEWER")
    vend = _heading_pos(text, "GO-DEEPER COURSE MAP")
    vblock = text[vstart:vend]
    for vm in re.finditer(
            r"^([\d.]+|Course Intro|Intro to R|Video Home)\s*(.*?)\s*→?\s*(https://\S*video_viewer\.html(?:#\d+)?)",
            vblock, re.M):
        key_raw, vtitle, vurl = vm.group(1).strip(), vm.group(2).strip(), vm.group(3)
        anchor = "#" + vurl.split("#")[1] if "#" in vurl else ""
        key = {"Course Intro": "0.intro", "Intro to R": "0.r",
               "Video Home": "home"}.get(key_raw, key_raw.rstrip("."))
        videos[key] = {"anchor": anchor, "url": vurl,
                       "title": vtitle.rstrip(":").strip() or key_raw}

    # Attach videos to sections BY TITLE SIMILARITY, not by number: the video
    # list's numbering drifts from the lecture numbering (video 11.5 is Welch
    # but section 11.5 is paired samples; ch. 12 videos are offset; 9.2/9.3
    # anchors are swapped). Title matching resolves all of these correctly and
    # leaves genuinely unmatched videos unattached rather than mislabeled.
    for key, video in videos.items():
        m_num = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{1,2}))?$", key)
        if not m_num:
            continue
        ch = m_num.group(1)
        sections = chapters.get(ch, {}).get("sections", {})
        if not sections:
            continue

        # Sub-videos ("6.3.1 Example 1") attach to their parent section by
        # number — their titles carry no signal.
        if m_num.group(3):
            parent = sections.get(f"{ch}.{m_num.group(2)}")
            if parent is not None:
                parent["extra_videos"].append(video)
                continue

        numeric_sec = sections.get(key)
        best_sec, best_ratio = None, 0.0
        for sec in sections.values():
            ratio = _video_section_score(video["title"], sec)
            if ratio > best_ratio:
                best_sec, best_ratio = sec, ratio
        # Prefer the numerically-corresponding section on near-ties; only
        # abandon it when its title clearly disagrees (the 11.5-Welch /
        # ch-12-offset cases).
        if numeric_sec is not None:
            numeric_ratio = _video_section_score(video["title"], numeric_sec)
            if numeric_ratio >= 0.45 and numeric_ratio >= best_ratio - 0.15:
                best_sec, best_ratio = numeric_sec, numeric_ratio
        if best_sec is None or best_ratio < 0.45:
            continue  # ambiguous — keep in videos{} only, never mislabel
        if best_sec["video"] is not None:
            best_sec["extra_videos"].append(video)
        else:
            best_sec["video"] = video

    # ---- worksheets ----------------------------------------------------------
    worksheets: dict[str, dict] = {}
    # explicit entries: "Worksheet N: Title[:]\nURL" or same-line URL
    for wm in re.finditer(
            r"Worksheet\s+(\d{1,2}):\s*([^\n:]+?)[:\s]*\n?\s*(https://\S+worksheet\d+\.html)",
            text):
        n, title, url = int(wm.group(1)), wm.group(2).strip(), wm.group(3)
        worksheets[str(n)] = {"number": n, "title": title, "url": url,
                              "chapters": [], "verified": True}

    # worksheet-chapter mapping: "Chapter 4 (Probability): Worksheets 2, 3, 4"
    for cm in re.finditer(
            r"Chapter\s+(\d{1,2})\s*\([^)]*\):\s*Worksheets?\s+([\d,\s]+)", text):
        ch = int(cm.group(1))
        for n in re.findall(r"\d+", cm.group(2)):
            n = str(int(n))
            if n not in worksheets:
                # 14-22 come only from the chapter map (no explicit URL in the
                # prompt); their pattern URLs were confirmed live 2026-07-11
                # (worksheets 1-22 all return 200), so mark them verified.
                worksheets[n] = {
                    "number": int(n), "title": f"Worksheet {n}",
                    "url": f"{SITE}Website/worksheets/worksheet_materials/worksheet{n}.html",
                    "chapters": [], "verified": True,
                }
            worksheets[n]["chapters"].append(ch)

    # ---- simulations ---------------------------------------------------------
    sims_src = {
        "clt": ("Central Limit Theorem simulation",
                "CLT intuition or sample-size effects"),
        "ci": ("Confidence-interval coverage simulation",
               "CI coverage, width, and method comparisons"),
        "power": ("Statistical power simulation",
                  "hypothesis-testing trade-offs or design planning"),
    }
    sim_urls = {
        "clt": re.search(r"https://\S+ShinyApps/CLT\.html", text),
        "ci": re.search(r"https://\S+ShinyApps/CI_Simulator\.html", text),
        "power": re.search(r"https://\S+ShinyApps/Power_Simulator\.html", text),
    }
    simulations = {
        key: {"key": key, "title": sims_src[key][0], "url": m.group(0),
              "when": sims_src[key][1]}
        for key, m in sim_urls.items() if m
    }

    # ---- syllabi & schedules -------------------------------------------------
    syllabus_pdfs = {m.group(1): m.group(2) for m in re.finditer(
        r"\"([^\"]+)\":\s*(https://\S+\.pdf)", text)}
    schedule_urls = {m.group(1): m.group(2) for m in re.finditer(
        r"\"([^\"]+)\":\s*(https://\S+StudentSchedule\S*\.html)", text)}

    def find_pdf(needle: str, term: str = "SPRING 2026") -> str:
        # Prefer the current term's syllabus; fall back to any matching label.
        for label, url in syllabus_pdfs.items():
            if needle.lower() in label.lower() and term.lower() in label.lower():
                return url
        for label, url in syllabus_pdfs.items():
            if needle.lower() in label.lower():
                return url
        return ""

    def find_sched(needle: str) -> str:
        for label, url in schedule_urls.items():
            if needle.lower() in label.lower():
                return url
        return ""

    syllabi = {
        "flipped": {"modality": "flipped", "label": "Flipped",
                    "syllabus_pdf": find_pdf("Flipped"),
                    "schedule_url": find_sched("Flipped")},
        "traditional": {"modality": "traditional", "label": "Traditional Lecture",
                        "syllabus_pdf": find_pdf("In-Person"),
                        "schedule_url": schedule_urls.get("Traditional Lecture", "")},
        "indy": {"modality": "indy", "label": "Traditional Lecture (Indianapolis)",
                 "syllabus_pdf": find_pdf("In-Person"),
                 "schedule_url": find_sched("Indianapolis")},
        "online": {"modality": "online", "label": "Asynchronous Online",
                   "syllabus_pdf": find_pdf("Online"),
                   "schedule_url": find_sched("Asynchronous Online")},
        "winter": {"modality": "winter", "label": "Winter Session (Asynchronous Online)",
                   "syllabus_pdf": find_pdf("Winter"),
                   "schedule_url": find_sched("Winter")},
    }

    # ---- exams ----------------------------------------------------------------
    exams: dict[str, dict] = {}
    exam_block = text[_heading_pos(text, "EXAM COVERAGE QUICK REFERENCE"):
                      _heading_pos(text, "WORKSHEET-CHAPTER MAPPING")]
    for em in re.finditer(
            r"(Exam\s+(\d)|Final Exam)\s*\(([^)]*)\):\s*\n((?:- .*\n?)*)",
            exam_block):
        key = em.group(2) or "final"
        label = em.group(1)
        coverage = em.group(3)
        topics = [t.strip("- ").strip() for t in em.group(4).strip().splitlines()]
        ch_nums = [int(x) for x in re.findall(r"\d+", coverage)]
        chapters_list = list(range(ch_nums[0], ch_nums[1] + 1)) if len(ch_nums) == 2 \
            else ch_nums
        exams[key] = {"key": key, "label": f"{label} ({coverage})",
                      "chapters": chapters_list, "topics": topics}

    # ---- catalog courses -------------------------------------------------------
    catalog: list[dict] = []
    cat_block = text[_heading_pos(text, "GO-DEEPER COURSE MAP"):
                     _heading_pos(text, "HOW TO SUGGEST A COURSE")]
    for cm in re.finditer(
            r"—\s*(.+?)\s*→\s*(STAT\s*\d{5})\s*\(([^)]+)\)\s*\n\s*(https://\S+)",
            cat_block):
        topics = [t.strip() for t in cm.group(1).split(",")]
        catalog.append({"code": cm.group(2), "title": cm.group(3),
                        "url": cm.group(4), "topics": topics})
    # STAT 41800 (Tim's course) isn't in the legacy system_prompt.txt GO-DEEPER
    # block; add it explicitly so a regenerated map keeps it. It's the computational
    # / data-science option — NOT the immediate next course (it also requires a
    # probability course, STAT 41600, first; 416/417 are the natural next steps).
    # Its number is also hard-coded in grounding/citations.py:_CATALOG_CODE_RE —
    # keep the two in sync.
    catalog.append({
        "code": "STAT 41800",
        "title": "Computational Methods in Data Science",
        "url": "https://treese41528.github.io/ComputationalDataScience/Website/index.html",
        "topics": ["Monte Carlo simulation", "maximum likelihood estimation",
                   "generalized linear models", "multiple and multivariate linear models",
                   "bootstrap and resampling", "permutation tests", "cross-validation",
                   "Bayesian inference", "MCMC and credible intervals",
                   "large language models in data science"],
    })

    # ---- hubs -----------------------------------------------------------------
    def hub(pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(0) if m else ""

    hubs = {
        "home": hub(r"https://\S+Website/index\.html"),
        "intro": hub(r"https://\S+Website/course-intro\.html"),
        "exams": hub(r"https://\S+exams/exams_index\.html"),
        "r_resources": hub(r"https://\S+r_computer_assignments\.html"),
        "worksheets": hub(r"https://\S+worksheets/worksheets_index\.html"),
        "video_home": hub(r"https://\S+video_viewer\.html(?=\s)"),
        "website_root": SITE + "Website/",
    }

    return {
        "version": "spring-2026",
        "site_base": SITE,
        "chapters": chapters,
        "worksheets": worksheets,
        "simulations": simulations,
        "syllabi": syllabi,
        "exams": exams,
        "catalog_courses": catalog,
        "hubs": hubs,
        "videos": videos,
        "allowlist_hosts": ["treese41528.github.io", "catalog.purdue.edu"],
    }


def overlay_youtube(course_map: dict, rst_dir: Path) -> int:
    """Replace section video links with DIRECT YouTube URLs extracted from the
    webbook rst sources (the Video Viewer is a general tool — its #anchors do
    not deep-link to individual videos, so direct links serve students better).

    File naming: chapterN_N-M-....rst → section N.M. The first embed on a page
    becomes the section's primary video; the rest become extra_videos (their
    titles may carry the video-numbering, e.g. file 13-2 hosts videos titled
    13.3–13.5 — that's the known video/section numbering offset; the FILE is
    what determines which page they live on). The top-level videos{} map keeps
    the old viewer anchors for reference/URL-parity.
    """
    iframe_re = re.compile(r"<iframe(.*?)</iframe>", re.S)
    src_re = re.compile(
        r'src="https://www\.youtube\.com/embed/([\w-]+)(?:\?([^"]*))?"')
    title_re = re.compile(r'title="([^"]*)"')
    list_re = re.compile(r"list=([\w-]+)")

    def watch_url(vid: str, query: str | None) -> str:
        lm = list_re.search(query or "")
        return (f"https://www.youtube.com/watch?v={vid}&list={lm.group(1)}"
                if lm else f"https://www.youtube.com/watch?v={vid}")

    n_overlaid = 0
    for f in sorted(rst_dir.glob("chapter*_*.rst")):
        m = re.match(r"chapter(\d{1,2})_(\d{1,2})-(\d{1,2})", f.stem)
        if not m:
            continue
        section = f"{int(m.group(2))}.{int(m.group(3))}"
        sec = course_map["chapters"].get(m.group(1), {}) \
            .get("sections", {}).get(section)
        if sec is None:
            continue
        vids = []
        for im in iframe_re.finditer(f.read_text(encoding="utf-8",
                                                 errors="replace")):
            block = im.group(1)
            sm = src_re.search(block)
            if not sm:
                continue
            tm = title_re.search(block)
            title = (tm.group(1).strip() if tm else "") or \
                f"{sec['number']} {sec['title']}"
            vids.append({"anchor": "", "url": watch_url(sm.group(1), sm.group(2)),
                         "title": title.removesuffix(" Video").strip()})
        if not vids:
            continue
        old_anchor = (sec.get("video") or {}).get("anchor", "")
        vids[0]["anchor"] = old_anchor       # keep the viewer anchor for reference
        sec["video"] = vids[0]
        sec["extra_videos"] = vids[1:]
        n_overlaid += 1
    return n_overlaid


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parents[3].parent / "system_prompt.txt"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        Path(__file__).resolve().parents[2] / "data" / "course_map.json"
    rst_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else \
        Path("/mnt/c/CommonFiles/STAT_350_Website/rst_files_for_chatbot")
    course_map = build(src.read_text(encoding="utf-8"))
    if rst_dir.is_dir():
        n = overlay_youtube(course_map, rst_dir)
        print(f"Overlaid direct YouTube links on {n} sections from {rst_dir}")
    else:
        print(f"NOTE: rst dir {rst_dir} not found — keeping Video Viewer links")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(course_map, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    n_sections = sum(len(c["sections"]) for c in course_map["chapters"].values())
    print(f"Wrote {dst}: {len(course_map['chapters'])} chapters, "
          f"{n_sections} sections, {len(course_map['worksheets'])} worksheets, "
          f"{len(course_map['videos'])} videos, "
          f"{len(course_map['catalog_courses'])} catalog courses")


if __name__ == "__main__":
    main()
