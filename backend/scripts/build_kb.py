#!/usr/bin/env python3
"""Build (or resume building) a knowledge collection from the webbook rst
sources + markdown syllabi, via the SDK's RAG API.

    export GENAI_STUDIO_API_KEY=...
    python backend/scripts/build_kb.py --dry-run        # list what would upload
    python backend/scripts/build_kb.py                  # create + upload + link
    python backend/scripts/build_kb.py --resume         # continue into existing KB

Defaults build "STAT 350 Knowledge Base (SUMMER 2026)" from:
  rst:      /mnt/c/CommonFiles/STAT_350_Website/rst_files_for_chatbot/*.rst
  syllabi:  /mnt/c/CommonFiles/Webbooks/STAT 350 Syllabus Info/*.md

SDK workflow per file (see RAGError docstring in genai_studio):
  upload_file() -> add_file_to_knowledge_base() ... then indexing is async
  server-side. Filenames are preserved, which is what the app's citation join
  (resolver) and the (term, modality) syllabus filter key on.

The OLD collection is never touched — it stays as instant rollback. After a
successful build, follow the printed NEXT STEPS (config.yaml switch + probe +
eval replay regression gate) before pointing students at the new collection.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from app.config import load_settings  # noqa: E402

DEFAULT_NAME = "STAT 350 Knowledge Base (SUMMER 2026)"
DEFAULT_RST = "/mnt/c/CommonFiles/STAT_350_Website/rst_files_for_chatbot"
DEFAULT_SYL = "/mnt/c/CommonFiles/Webbooks/STAT 350 Syllabus Info"
# Linking a file triggers SYNCHRONOUS chunking + embedding server-side, which
# for a big chapter (50KB+) can exceed a short timeout. Give it real room; the
# verify-after-timeout logic below recovers even when the POST times out but the
# link actually landed.
KB_TIMEOUT_S = 90
# Let an upload's content extraction finish before we try to link it (linking
# too soon returns "content is empty" even for a file that HAS content).
SETTLE_S = 2.0
# Bounded link retries. A ReadTimeout is the slow embedding step and usually
# still lands; a retry returns 200 or 'duplicate content' (both == linked).
MAX_LINK_ATTEMPTS = 3
EMPTY_RESETTLE_S = 4.0               # after a fresh re-upload on an "empty" error
RETRY_WAIT = 3.0
# Pace EVERY file operation — this gateway responds to bursts by hanging or
# dropping requests, which looks like a frozen script.
PACE_S = 0.75
# Files with less extractable prose than this are navigation stubs (a title +
# a `.. toctree::`); the server extracts nothing from them → "content is empty".
# Skip them up front: they carry zero retrieval value and only waste retries.
MIN_PROSE_CHARS = 40
OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, httpx.TimeoutException)


def _is_empty_content(exc: Exception) -> bool:
    s = str(exc).lower()
    return "empty" in s and "content" in s and "duplicate" not in s


def _is_duplicate_content(exc: Exception) -> bool:
    """The gateway rejects a file whose CONTENT already exists in the KB with
    '400: Duplicate content detected'. That means it's ALREADY linked — success,
    not failure. (This is how a --resume run recognises finished files, since
    the /files listing is capped at 30 and can't enumerate them.)"""
    return "duplicate content" in str(exc).lower()


def prose_chars(path: Path) -> int:
    """Rough count of extractable prose, mirroring what the server's content
    extractor keeps: drop rst/md directives, field lists, section-underline
    rules, and toctree entry slugs. A toctree-only index stub scores ~0."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    total = 0
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("..") or s.startswith(":"):
            continue                                   # blank / directive / field
        if set(s) <= set("=-~*#^\"'`+._ "):
            continue                                   # section underline/overline
        if " " not in s and ("/" in s or "_" in s or s.count("-") >= 2):
            continue                                   # toctree entry / slug path
        total += len(s)
    return total


def make_studio(settings):
    """A dedicated client for KB ops with a SHORT timeout (the Gateway's 120s
    chat timeout turns one hung link call into minutes of silence)."""
    from genai_studio import GenAIStudio
    return GenAIStudio(api_key=settings.api_key,
                       base_url=settings.gateway.base_url,
                       timeout=KB_TIMEOUT_S, connect_timeout=15,
                       validate_model=False)


def collect_files(rst_dir: Path, syl_dir: Path) -> list[Path]:
    files: list[Path] = []
    if rst_dir.is_dir():
        files += sorted(rst_dir.glob("*.rst"))
    if syl_dir.is_dir():
        files += sorted(syl_dir.glob("*.md"))
    return [f for f in files if f.stat().st_size > 0]


def categorize(files: list[Path]) -> dict[str, int]:
    cats: dict[str, int] = {}
    for f in files:
        n = f.name.lower()
        cat = ("syllabus" if "syllab" in n else
               "lecture" if n.startswith("chapter") and "index" not in n else
               "worksheet" if "worksheet" in n else
               "exam" if "exam" in n else
               "r-guide" if n.startswith("r_") else "other")
        cats[cat] = cats.get(cat, 0) + 1
    return cats


import re as _re

_UUID_PREFIX = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_", _re.I)


def _clean(name: str) -> str:
    """Server-side physical filenames carry a 'uuid_' prefix — strip it so
    comparisons against local source names work."""
    return _UUID_PREFIX.sub("", str(name))


def _kb_files(studio, kb_id: str) -> list[dict]:
    """The files linked to the KB, via /knowledge/{id}/files — the authoritative
    endpoint on this gateway. (get_knowledge_base() returns files=null here.)

    NOTE: this endpoint returns only the FIRST 30 items and ignores every
    pagination param, so this is a partial list — use it for a fast first-page
    skip, but count files with kb_file_total() and never treat a name's absence
    here as 'missing'."""
    try:
        data = studio._http_get(f"/api/v1/knowledge/{kb_id}/files").json()
    except Exception:
        return []
    items = data.get("items", data) if isinstance(data, dict) else data
    return [it for it in items if isinstance(it, dict)]


def kb_file_total(studio, kb_id: str) -> int:
    """Authoritative COUNT of files linked to the KB (the /files 'total' field —
    accurate even though 'items' is capped at 30). Returns -1 if unavailable."""
    try:
        data = studio._http_get(f"/api/v1/knowledge/{kb_id}/files").json()
    except Exception:
        return -1
    if isinstance(data, dict) and isinstance(data.get("total"), int):
        return data["total"]
    return len(data.get("items", data)) if isinstance(data, dict) else len(data)


# --- link manifest ---------------------------------------------------------
# This gateway can't enumerate a KB's files (the /files listing caps at 30 and
# ignores pagination), so a resume can't tell from the server WHICH files are
# already linked. Re-linking an already-present file usually 400s as "duplicate"
# but SOMETIMES silently adds a second copy — so we must not blindly re-process.
# The fix: remember what we linked in a small local manifest, keyed by KB id.
STATE_PATH = Path(__file__).resolve().parent / ".build_kb_state.json"


def load_manifest(kb_id: str) -> set[str]:
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")).get(kb_id, []))
    except Exception:
        return set()


def save_manifest(kb_id: str, names: set[str]) -> None:
    try:
        state = {}
        if STATE_PATH.exists():
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state[kb_id] = sorted(names)
        STATE_PATH.write_text(json.dumps(state, indent=0), encoding="utf-8")
    except Exception as exc:
        print(f"   {WARN}couldn't persist link manifest ({exc})")


def linked_filenames(studio, kb_id: str) -> set[str]:
    """Filenames already linked to the KB (both raw and uuid-stripped forms)."""
    names: set[str] = set()
    for item in _kb_files(studio, kb_id):
        meta = item.get("meta") or {}
        for key in (item.get("filename"), meta.get("name"), item.get("name")):
            if key:
                names.add(str(key))
                names.add(_clean(key))
    return names


def main() -> int:
    ap = argparse.ArgumentParser(prog="build_kb.py")
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--description",
                    default="STAT 350 webbook (rst sources) + syllabi (md) — "
                            "built by backend/scripts/build_kb.py")
    ap.add_argument("--rst-dir", default=DEFAULT_RST)
    ap.add_argument("--syllabus-dir", default=DEFAULT_SYL)
    ap.add_argument("--resume", action="store_true",
                    help="continue into an existing KB with this name "
                         "(uploads only files not already linked)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = collect_files(Path(args.rst_dir), Path(args.syllabus_dir))
    if not files:
        print(f"{FAIL} no files found under {args.rst_dir!r} / {args.syllabus_dir!r}")
        return 2
    cats = categorize(files)
    print(f"Source files: {len(files)}  " +
          "  ".join(f"{k}={v}" for k, v in sorted(cats.items())))

    if args.dry_run:
        for f in files:
            print(f"  would upload: {f.name}  ({f.stat().st_size:,} bytes)")
        print(f"\nDry run only — would build {args.name!r}. "
              "Re-run without --dry-run to execute.")
        return 0

    settings = load_settings()
    if not settings.api_key:
        print("GENAI_STUDIO_API_KEY not set.")
        return 2
    studio = make_studio(settings)

    # ---- find-or-create the KB (idempotent) ---------------------------------
    existing = {kb.name: kb for kb in studio.list_knowledge_bases()}
    if args.name in existing:
        if not args.resume:
            print(f"{FAIL} A knowledge base named {args.name!r} already exists "
                  f"(id={existing[args.name].id}).\n"
                  "   Re-run with --resume to add missing files to it, or pick "
                  "a different --name.")
            return 1
        kb = existing[args.name]
        print(f"{OK} resuming into existing KB {kb.id}")
    else:
        kb = studio.create_knowledge_base(args.name, args.description)
        print(f"{OK} created KB {kb.id}: {kb.name!r}")
        time.sleep(2)  # let creation settle (SDK guidance)

    # Classify sources ONCE: navigation stubs (skip — the server extracts
    # nothing) vs content files (upload + link).
    stubs = [f for f in files if prose_chars(f) < MIN_PROSE_CHARS]
    content = [f for f in files if prose_chars(f) >= MIN_PROSE_CHARS]
    for f in stubs:
        print(f"   {WARN}{f.name}: navigation stub (no extractable prose) — skipped")

    # What's already linked? This gateway can't fully enumerate a KB (30-cap), so
    # union the local manifest (authoritative across runs) with the first page.
    manifest = load_manifest(kb.id)
    already = manifest | linked_filenames(studio, kb.id)
    linked_ct = kb_file_total(studio, kb.id)
    todo = [f for f in content if f.name not in already]
    print(f"   {len(content)} content files; server file count = {linked_ct}; "
          f"{len(content) - len(todo)} recorded already linked")

    # COMPLETENESS GUARD (the important safety net): if the KB already holds at
    # least every content file, do NOT re-process — re-linking a present file can
    # silently add a duplicate copy. Record completeness and skip to verify.
    if linked_ct >= len(content):
        print(f"{OK} KB already complete ({linked_ct} files ≥ {len(content)} "
              "content files) — nothing to add.")
        save_manifest(kb.id, {f.name for f in content})
        todo = []
    elif not todo:
        print(f"{OK} every content file is recorded linked — nothing to add.")

    # Orphan reuse: a previous failed run may have UPLOADED files that never got
    # linked. Link the existing upload instead of re-uploading a duplicate.
    uploaded_by_name: dict[str, str] = {}
    try:
        for fi in studio.list_files():
            uploaded_by_name.setdefault(_clean(fi.filename), fi.id)  # first seen
    except Exception as exc:
        print(f"   {WARN} could not list existing uploads ({exc}) — "
              "will upload fresh copies")

    def link_file(file_id: str, f: Path) -> tuple[str, str]:
        """Link a file, resilient to this gateway's real behaviours.

        Returns (status, detail) where status is:
          'linked' — the file is in the KB (freshly, already-present, or a
                     timeout whose embedding lands server-side);
          'empty'  — a stub the server can't extract, even after a fresh
                     re-upload — skip it, it has no retrieval value;
          'failed' — a real, unexpected error.

        Key gateway facts learned by probing:
          • '400 Duplicate content detected' == the content is ALREADY linked →
            success (this is how --resume recognises finished files).
          • A ReadTimeout is the slow embedding step; it usually still lands, and
            a retry just returns 200 or 'duplicate' — either way linked. We don't
            poll to confirm (the /files list is capped at 30); kb_file_total()
            is the honest end-of-run backstop instead."""
        fname, last, saw_timeout = f.name, "", False
        for attempt in range(MAX_LINK_ATTEMPTS):
            try:
                studio.add_file_to_knowledge_base(kb.id, file_id)
                return "linked", ""
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
                if _is_duplicate_content(exc):
                    return "linked", "already in KB"
                if _is_empty_content(exc):
                    # stub OR a stale/bad orphan upload. Give a content-bearing
                    # file ONE fresh re-upload; still empty → genuine stub → skip.
                    if attempt == 0:
                        try:
                            print(f"      … {fname}: empty content — re-uploading "
                                  "fresh once", flush=True)
                            file_id = studio.upload_file(str(f)).id
                            time.sleep(EMPTY_RESETTLE_S)
                            continue
                        except Exception as up_exc:
                            last = f"re-upload failed: {up_exc}"
                    return "empty", last
                if _is_timeout(exc):
                    saw_timeout = True
                    print(f"      … {fname}: link timed out (embedding is slow) — "
                          "retrying once", flush=True)
                    time.sleep(RETRY_WAIT)
                    continue
                # some other error — brief wait, then retry
                print(f"      … {fname}: {last[:80]} — retrying", flush=True)
                time.sleep(RETRY_WAIT)
        # exhausted. Repeated timeouts almost always still land server-side, so
        # assume linked (kb_file_total at the end is the honest check); a
        # non-timeout error that never resolved is a real failure.
        if saw_timeout:
            return "linked", "assumed linked after repeated timeouts"
        return "failed", last

    # ---- upload + link (only files not already linked) -----------------------
    done = failed = reused = 0
    empty = len(stubs)                      # stubs were reported above
    empty_names: set[str] = {f.name for f in stubs}
    failures: list[tuple[str, str]] = []
    t0 = time.monotonic()
    for i, f in enumerate(todo, 1):
        try:
            file_id = uploaded_by_name.get(f.name)
            if file_id:
                reused += 1
            else:
                try:
                    file_id = studio.upload_file(str(f)).id
                except Exception:
                    time.sleep(2)                       # one upload retry
                    file_id = studio.upload_file(str(f)).id
                time.sleep(SETTLE_S)                    # let processing start
            status, detail = link_file(file_id, f)
            if status == "linked":
                done += 1
                manifest.add(f.name)
                if done % 5 == 0:
                    save_manifest(kb.id, manifest)      # checkpoint progress
            elif status == "empty":
                empty += 1
                empty_names.add(f.name)
                print(f"   {WARN}{f.name}: server reports empty content — skipped",
                      flush=True)
            else:
                failed += 1
                failures.append((f.name, detail))
                print(f"   {FAIL} {f.name}: {detail[:140]}", flush=True)
        except Exception as exc:
            failed += 1
            failures.append((f.name, f"{type(exc).__name__}: {exc}"))
            print(f"   {FAIL} {f.name}: {type(exc).__name__}: {exc}", flush=True)
        if i % 5 == 0 or i == len(todo):
            mins = (time.monotonic() - t0) / 60
            print(f"   [{i:3}/{len(todo)}] linked={done} reused_upload={reused} "
                  f"empty={empty} failed={failed}  ({mins:.1f} min)", flush=True)
        time.sleep(PACE_S)      # pace EVERY iteration — bursts hang this gateway
    save_manifest(kb.id, manifest)          # final checkpoint

    # ---- SERVER-SIDE verification (COUNT-based: the /files list is capped at
    # 30 and ignores pagination, so we can only trust its 'total', never
    # enumerate which files are present) ---------------------------------------
    time.sleep(3)
    expected = content                      # stubs excluded by construction
    linked_total = kb_file_total(studio, kb.id)
    print(f"\nServer reports {linked_total} files linked; "
          f"{len(expected)} content files expected "
          f"({empty} navigation stubs skipped).")
    if linked_total < 0:
        print(f"{WARN} could not read the KB file count — verify in the UI.")
    elif linked_total >= len(expected):
        print(f"{OK} all {len(expected)} content files are linked.")
    else:
        gap = len(expected) - linked_total
        print(f"{WARN} {gap} content file(s) not yet linked — re-run with "
              "--resume. (The endpoint can't list WHICH; already-linked files "
              "are recognised by their 'duplicate content' reply and skip fast.)")

    # ---- wait for indexing, then sanity-check retrieval -----------------------
    print("\nWaiting for server-side indexing…")
    time.sleep(15)
    try:
        payload = studio._http_post(
            "/api/v1/retrieval/query/collection",
            json={"collection_names": [kb.id], "k": 3, "hybrid": False,
                  "query": "central limit theorem sample mean"}).json()
        docs = payload.get("documents") or []
        flat = docs[0] if docs and isinstance(docs[0], list) else docs
        print(f"{OK if flat else WARN} retrieval sanity: {len(flat)} chunks for a "
              "CLT query" + ("" if flat else " — indexing may still be running; "
                             "retry the probe in a few minutes"))
        payload = studio._http_post(
            "/api/v1/retrieval/query/collection",
            json={"collection_names": [kb.id], "k": 5, "hybrid": False,
                  "query": "STAT 350 SUMMER 2026 syllabus grading policy"}).json()
        metas = payload.get("metadatas") or []
        mflat = metas[0] if metas and isinstance(metas[0], list) else metas
        names = {str((m or {}).get("name") or "") for m in mflat}
        hit = any("summer" in n.lower() and "syllab" in n.lower() for n in names)
        print(f"{OK if hit else WARN} SUMMER syllabus retrievable: {hit} "
              f"(top files: {sorted(names)[:3]})")
    except Exception as exc:
        print(f"{WARN} sanity queries failed ({exc}) — retry via probe later")

    print(f"""
================= NEXT STEPS =================
1. backend/config.yaml:
     collections.webbook: "{args.name}"
     course.term: "SUMMER 2026"          (or course.auto_term: true)
     course.syllabi.*: update PDF links when the new PDFs are published
2. python backend/scripts/probe_gateway.py     # joins + syllabus coverage on the NEW collection
3. python backend/scripts/eval.py replay        # REGRESSION GATE vs the old index
   python backend/scripts/eval.py run --index-version summer-2026-v1
4. Restart the app. The old collection is untouched — switching
   collections.webbook back is the instant rollback.
==============================================""")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
