#!/usr/bin/env python3
"""Phase 0 gateway probes — run ONCE with a real API key before trusting the
config defaults. Answers the nine unknowns the architecture was designed
around, and prints suggested config.yaml changes.

    cd backend
    export GENAI_STUDIO_API_KEY=...          # GenAI Studio → Settings → Account
    ~/venvs/stat350-tutor/bin/python scripts/probe_gateway.py

Read-only against the gateway except a two-token chat call and a tiny
tool-probe; everything is paced through the shared limiter.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _ensure_venv() -> None:
    """Re-exec under the project venv if this interpreter lacks the SDK."""
    try:
        import genai_studio  # noqa: F401
        return
    except ImportError:
        pass
    candidates = [
        os.environ.get("STAT350_VENV"),
        str(Path.home() / "venvs" / "stat350-tutor"),
        "/opt/stat350-tutor/venv",
    ]
    for venv in candidates:
        if not venv:
            continue
        python = Path(venv) / "bin" / "python"
        if python.exists() and str(python) != sys.executable:
            os.execv(str(python), [str(python), *sys.argv])
    sys.exit(
        "This interpreter doesn't have the genai-studio-sdk installed and no "
        "project venv was found.\nEither run with the venv python, e.g.\n"
        "    ~/venvs/stat350-tutor/bin/python scripts/probe_gateway.py\n"
        "or point STAT350_VENV at a venv that has the backend deps installed."
    )


_ensure_venv()

from app.config import load_settings  # noqa: E402
from app.course_map.resolver import CourseMapResolver, normalize_filename  # noqa: E402
from app.gateway import Gateway  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
SUGGESTIONS: list[str] = []


def h(title: str) -> None:
    print(f"\n{'=' * 70}\nPROBE: {title}\n{'=' * 70}")


def main() -> int:
    settings = load_settings()
    if not settings.api_key:
        print("Set GENAI_STUDIO_API_KEY first.")
        return 2
    resolver = CourseMapResolver.from_file(
        settings.backend_dir / "data" / "course_map.json")
    gw = Gateway(settings)

    # ---- 2: KB name → ID resolution ---------------------------------------
    h("2. Knowledge collections resolve by display name")
    try:
        ids = gw.resolve_collections()
        print(f"{OK} webbook     = {ids['webbook']}")
        print(f"{OK} transcripts = {ids['transcripts']}")
    except Exception as exc:
        print(f"{FAIL} {exc}")
        print("   Fix collections: names in config.yaml to match the gateway "
              "exactly, then re-run.")
        return 1

    # ---- 1 & 8: metadata shape per collection ------------------------------
    for key, label in (("webbook", "1. Webbook chunk metadata → rst filename"),
                       ("transcripts", "8. Transcript chunk metadata → video mapping")):
        h(label)
        try:
            payload = gw.retrieval_query(
                "central limit theorem sample mean", [gw.kb_ids[key]], k=3)
            metas = payload.get("metadatas") or []
            flat = metas[0] if metas and isinstance(metas[0], list) else metas
            if not flat:
                print(f"{WARN} no metadata returned; join must use file-index "
                      "fallback (data/kb_file_index.json)")
                continue
            sample = flat[0]
            print("metadata keys:", sorted(sample.keys()))
            print("sample:", json.dumps(sample, default=str)[:400])
            name = sample.get("name") or sample.get("source") or ""
            base = normalize_filename(str(name))
            if key == "webbook":
                res = resolver.resolve_webbook(sample)
                verdict = OK if res.match in ("exact", "number") else \
                    WARN if res.match in ("fuzzy", "title") else FAIL
                print(f"{verdict} '{name}' → normalized '{base}' → "
                      f"{res.title} (match={res.match})")
                if res.match not in ("exact", "number"):
                    SUGGESTIONS.append(
                        "webbook filenames don't join cleanly — inspect "
                        "several metadatas and extend normalize_filename() or "
                        "build the kb_file_index fallback.")
            else:
                res = resolver.resolve_transcript(sample)
                verdict = OK if res.section else WARN
                print(f"{verdict} '{name}' → {res.title} (match={res.match})")
                if not res.section:
                    SUGGESTIONS.append(
                        "transcript filenames don't map to sections — check "
                        "their naming pattern and extend resolve_transcript().")
        except Exception as exc:
            print(f"{FAIL} retrieval failed: {exc}")

    # ---- 10: syllabus in the KB (naming + modality separability) ------------
    h("10. Syllabus content in the knowledge base")
    try:
        payload = gw.retrieval_query(
            "STAT 350 syllabus grading policy homework worth percentage",
            [gw.kb_ids["webbook"]], k=5)
        metas = payload.get("metadatas") or []
        flat = metas[0] if metas and isinstance(metas[0], list) else metas
        names = [str((mm or {}).get("name") or (mm or {}).get("source") or "")
                 for mm in flat]
        syl = [n for n in names if "syllab" in n.lower()]
        if syl:
            print(f"{OK} syllabus chunks retrievable. Filenames:")
            for n in sorted(set(syl)):
                print(f"     {n}")
            has_modality = any(re.search(r"flip|person|online|winter|summer", n, re.I)
                               for n in syl)
            if has_modality:
                print(f"{OK} filenames encode modality — you can refine the syllabus "
                      "golden globs to modality-specific (e.g. *flipped*) and, if "
                      "needed, post-filter retrieval by modality for exact answers.")
            else:
                SUGGESTIONS.append(
                    "Syllabus chunks don't encode modality in the filename — "
                    "modality-correct answers rely on the query bias; verify with "
                    "`eval.py run --golden data/golden_syllabus.yaml`.")
        else:
            print(f"{WARN} no syllabus chunk in the top 5 for a grading query "
                  f"(got: {names}). Syllabus may not be indexed, or is named "
                  "unexpectedly — the tutor will fall back to linking the PDF.")
            SUGGESTIONS.append(
                "Syllabus not clearly retrievable — confirm it's in the "
                "collection, or the syllabus path stays link-only.")
    except Exception as exc:
        print(f"{FAIL} {exc}")

    # ---- 3: multi-collection single call row order --------------------------
    h("3. Single call with both collections — row ↔ collection order")
    try:
        payload = gw.retrieval_query(
            "central limit theorem", [gw.kb_ids["webbook"],
                                      gw.kb_ids["transcripts"]], k=2)
        docs = payload.get("documents") or []
        if docs and isinstance(docs[0], list) and len(docs) == 2:
            print(f"{OK} response keeps {len(docs)} rows — per-collection "
                  "structure PRESERVED.")
            print("   Verify row0 looks like webbook text, row1 like a "
                  "transcript, then set retrieval.single_call: true "
                  "(saves 1 RPM slot per question):")
            for i, row in enumerate(docs):
                head = (row[0][:110] + "…") if row else "(empty)"
                print(f"   row{i}: {head!r}")
            SUGGESTIONS.append(
                "If row order matches collection order above: set "
                "retrieval.single_call: true in config.yaml.")
        else:
            shape = f"{len(docs)} flat items" if docs else "empty"
            print(f"{WARN} rows not per-collection ({shape}) — keep "
                  "retrieval.single_call: false (two calls, labeled).")
    except Exception as exc:
        print(f"{FAIL} {exc}")

    # ---- 4: distance scale ---------------------------------------------------
    h("4. Distance semantics/scale (seeds the strong/weak thresholds)")
    try:
        on = gw.retrieval_query("What is the Central Limit Theorem?",
                                [gw.kb_ids["webbook"]], k=5)
        off = gw.retrieval_query("best pizza toppings for a birthday party",
                                 [gw.kb_ids["webbook"]], k=5)

        def flat_d(p):
            d = p.get("distances") or []
            return [x for row in (d if d and isinstance(d[0], list) else [d])
                    for x in row]
        d_on, d_off = flat_d(on), flat_d(off)
        print(f"on-topic scores : {[round(x, 3) for x in d_on]}")
        print(f"off-topic scores: {[round(x, 3) for x in d_off]}")
        cfg_higher = settings.retrieval.higher_is_better
        if d_on and d_off:
            best_on = max(d_on) if cfg_higher else min(d_on)
            best_off = max(d_off) if cfg_higher else min(d_off)
            on_better = (best_on > best_off) if cfg_higher else (best_on < best_off)
            direction = "higher = better" if cfg_higher else "lower = better"
            if on_better:
                print(f"{OK} {direction} confirmed (config matches). "
                      f"on-topic best {best_on:.3f} vs off-topic best {best_off:.3f}")
                if cfg_higher:
                    strong = round(min(d_on) - 0.02, 3)
                    weak = round(max(d_off) + 0.02, 3)
                else:
                    strong = round(best_on + (best_off - best_on) * 0.35, 3)
                    weak = round(best_on + (best_off - best_on) * 0.75, 3)
                SUGGESTIONS.append(
                    f"Seed thresholds (higher_is_better={cfg_higher}): "
                    f"strong≈{strong}, weak≈{weak} — calibrate with "
                    "`python backend/scripts/eval.py run`.")
            else:
                print(f"{FAIL} on-topic did NOT beat off-topic under "
                      f"higher_is_better={cfg_higher}. FLIP "
                      "retrieval.higher_is_better in config.yaml.")
                SUGGESTIONS.append(
                    f"Set retrieval.higher_is_better: {str(not cfg_higher).lower()} "
                    "— on/off-topic ordering contradicts the current setting.")
    except Exception as exc:
        print(f"{FAIL} {exc}")

    # ---- 5: query-rewriter task endpoint --------------------------------------
    h("5. /api/v1/tasks/queries/completions (server-side query rewriter)")
    try:
        gw.limiter.acquire()
        resp = gw.studio._http_post(
            "/api/v1/tasks/queries/completions",
            json={"model": settings.gateway.model,
                  "messages": [{"role": "user",
                                "content": "what about the second assumption?"}]})
        print(f"{OK} exists (HTTP {resp.status_code}): {resp.text[:200]}")
        SUGGESTIONS.append("Query rewriter exists — consider "
                           "retrieval.rewriter: task_endpoint (costs 1 extra "
                           "request/question; heuristic is free).")
    except Exception as exc:
        print(f"{WARN} not usable ({exc}) — keep retrieval.rewriter: heuristic.")

    # ---- 6: model TTFB + native tool calling ----------------------------------
    h(f"6. {settings.gateway.model}: streamed TTFB and native tool-calling")
    try:
        pad = "You are a helpful tutor. " * 150  # ~4k chars ≈ 1k tokens
        t0 = time.monotonic()
        first, total = None, 0
        gw.limiter.acquire()
        # max_tokens generous: gpt-oss:120b is a reasoning model and may spend
        # a small budget entirely on hidden reasoning, emitting no content.
        for delta in gw.studio.chat_messages(
                [{"role": "system", "content": pad},
                 {"role": "user", "content": "In one sentence, what is a p-value?"}],
                model=settings.gateway.model, stream=True, max_tokens=200):
            if first is None:
                first = time.monotonic() - t0
            total += len(delta)
        elapsed = time.monotonic() - t0
        if first is None:
            print(f"{WARN} stream produced NO content in {elapsed:.1f}s / "
                  f"200 tokens. gpt-oss:120b may be emitting only reasoning "
                  "tokens the SDK filters — verify the default path returns "
                  "visible text, or pick a non-reasoning model for it.")
            SUGGESTIONS.append(
                "Default-path model produced no visible tokens in the probe — "
                "confirm gpt-oss:120b streams content, or set gateway.model to "
                "a non-reasoning chat model.")
        else:
            print(f"{OK} TTFB {first:.1f}s with ~1k-token prompt "
                  f"(expect more with the real ~3-4k prompt; total {total} "
                  f"chars, {elapsed:.1f}s)")
            if first > 8:
                SUGGESTIONS.append(
                    f"TTFB {first:.0f}s is high — trim max passages or test a "
                    "smaller/non-reasoning model for the default path.")
    except Exception as exc:
        print(f"{FAIL} chat failed: {exc}")
    try:
        from genai_studio.agents.client import GenAIStudioClient
        client = GenAIStudioClient(gw.studio,
                                   default_model=settings.gateway.model,
                                   rate_limiter=gw.limiter)
        native = client.probe_native_tools()
        print(f"{OK if native else WARN} native tool-calling: {native}"
              + ("" if native else "  (escalation agent will use ReAct "
                                   "fallback — works, but more steps)"))
    except Exception as exc:
        print(f"{WARN} tool probe failed: {exc}")

    # ---- 7 & 9: manual checks ---------------------------------------------------
    h("7 & 9. Manual checks")
    print("7. SSE buffering: after deploying, run\n"
          "     curl -N -H 'X-Device-Id: 00000000-0000-0000-0000-000000000001' \\\n"
          "          -H 'Content-Type: application/json' \\\n"
          "          -d '{\"message\":\"hi\"}' https://<host>/api/chat\n"
          "   Tokens must appear INCREMENTALLY. If they arrive in one burst,\n"
          "   the fronting proxy buffers — ensure X-Accel-Buffering: no "
          "reaches it / disable proxy_buffering for /api/chat.")
    print("9. Worksheets 14-22 are pattern-derived (verified=false in "
          "course_map.json). Open a couple, e.g.\n"
          "     https://treese41528.github.io/STAT350/Website/worksheets/"
          "worksheet_materials/worksheet17.html\n"
          "   If they 404, fix data/course_map.json and set verified "
          "accordingly.")

    print(f"\n{'=' * 70}\nSUGGESTED CONFIG CHANGES\n{'=' * 70}")
    if SUGGESTIONS:
        for s in SUGGESTIONS:
            print(f"  • {s}")
    else:
        print("  (none — defaults look right)")
    print("\nNext: python backend/scripts/eval.py run   "
          "# calibrate thresholds properly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
