#!/usr/bin/env python3
"""Diagnose a knowledge collection against the local source files.

    export GENAI_STUDIO_API_KEY=...
    python backend/scripts/kb_inventory.py --name "STAT 350 Knowledge Base (SUMMER 2026)"

Reports, per source file: LINKED (in the KB), ORPHAN (uploaded to the server
but never linked — e.g. from an interrupted build), or ABSENT (never uploaded).
Then says exactly what to do (usually: build_kb.py --resume).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from app.config import load_settings  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_kb import (DEFAULT_NAME, DEFAULT_RST, DEFAULT_SYL, _clean,  # noqa: E402
                      categorize, collect_files, linked_filenames)


def main() -> int:
    ap = argparse.ArgumentParser(prog="kb_inventory.py")
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--rst-dir", default=DEFAULT_RST)
    ap.add_argument("--syllabus-dir", default=DEFAULT_SYL)
    args = ap.parse_args()

    settings = load_settings()
    if not settings.api_key:
        print("GENAI_STUDIO_API_KEY not set.")
        return 2
    from build_kb import make_studio
    studio = make_studio(settings)

    kbs = {kb.name: kb for kb in studio.list_knowledge_bases()}
    if args.name not in kbs:
        print(f"No knowledge base named {args.name!r}. Existing:")
        for n in sorted(kbs):
            print(f"  - {n}")
        return 1
    kb = kbs[args.name]

    linked = linked_filenames(studio, kb.id)
    uploaded = set()
    try:
        uploaded = {_clean(fi.filename) for fi in studio.list_files()}
    except Exception as exc:
        print(f"⚠️  could not list global uploads ({exc})")

    sources = collect_files(Path(args.rst_dir), Path(args.syllabus_dir))
    cats = categorize(sources)
    linked_src = [f for f in sources if f.name in linked]
    orphans = [f for f in sources if f.name not in linked and f.name in uploaded]
    absent = [f for f in sources if f.name not in linked and f.name not in uploaded]

    print(f"KB {kb.name!r} (id={kb.id})")
    print(f"  server reports linked files : {len(linked_src)}/{len(sources)} "
          f"of local sources ({'  '.join(f'{k}={v}' for k, v in sorted(cats.items()))})")
    print(f"  ORPHANS (uploaded, not linked): {len(orphans)}")
    for f in orphans[:15]:
        print(f"     {f.name}")
    if len(orphans) > 15:
        print(f"     … and {len(orphans) - 15} more")
    print(f"  ABSENT (never uploaded)       : {len(absent)}")
    for f in absent[:15]:
        print(f"     {f.name}")
    if len(absent) > 15:
        print(f"     … and {len(absent) - 15} more")

    if orphans or absent:
        print("\n→ run:  python backend/scripts/build_kb.py --resume"
              + (f' --name "{args.name}"' if args.name != DEFAULT_NAME else "")
              + "\n  (links orphans without re-uploading; uploads only what's absent;"
                "\n   links now use the same-file-id backoff, so slow server-side"
                "\n   processing no longer causes failures)")
    else:
        print("\n✅ complete — every source file is linked. If the GenAI Studio UI"
              "\n   shows fewer, it may still be indexing; re-check in a few minutes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
