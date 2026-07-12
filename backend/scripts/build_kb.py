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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from app.config import load_settings  # noqa: E402

DEFAULT_NAME = "STAT 350 Knowledge Base (SUMMER 2026)"
DEFAULT_RST = "/mnt/c/CommonFiles/STAT_350_Website/rst_files_for_chatbot"
DEFAULT_SYL = "/mnt/c/CommonFiles/Webbooks/STAT 350 Syllabus Info"
PAUSE_S = 0.25          # gentle pacing between file-API calls
OK, WARN, FAIL = "✅", "⚠️ ", "❌"


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


def linked_filenames(studio, kb_id: str) -> set[str]:
    """Filenames already linked to the KB (defensive: raw_response shape is
    server-version dependent)."""
    try:
        raw = studio.get_knowledge_base(kb_id).raw_response or {}
    except Exception:
        return set()
    names: set[str] = set()
    for item in raw.get("files") or []:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta") or {}
        for key in (item.get("filename"), meta.get("name"), item.get("name")):
            if key:
                names.add(str(key))
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
    from app.gateway import Gateway
    studio = Gateway(settings).studio

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

    already = linked_filenames(studio, kb.id)
    if already:
        print(f"   {len(already)} files already linked — skipping duplicates")

    # ---- upload + link -------------------------------------------------------
    done = failed = skipped = 0
    failures: list[tuple[str, str]] = []
    for i, f in enumerate(files, 1):
        if f.name in already:
            skipped += 1
            continue
        try:
            info = studio.upload_file(str(f))
            time.sleep(PAUSE_S)
            studio.add_file_to_knowledge_base(kb.id, info.id)
            done += 1
        except Exception as exc:                      # retry once
            time.sleep(2)
            try:
                info = studio.upload_file(str(f))
                time.sleep(PAUSE_S)
                studio.add_file_to_knowledge_base(kb.id, info.id)
                done += 1
            except Exception as exc2:
                failed += 1
                failures.append((f.name, f"{type(exc2).__name__}: {exc2}"))
        if i % 10 == 0 or i == len(files):
            print(f"   [{i:3}/{len(files)}] uploaded+linked={done} "
                  f"skipped={skipped} failed={failed}")
        time.sleep(PAUSE_S)

    for name, err in failures:
        print(f"   {FAIL} {name}: {err[:120]}")

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
