"""Eval harness — retrieval quality AND answer quality.

    python backend/scripts/eval.py run     [--golden data/golden_questions.yaml] [--k 8]
    python backend/scripts/eval.py replay  [--since 2026-08-01] [--sample 300]
    python backend/scripts/eval.py judge   [--golden data/golden_syllabus.yaml] [--limit 20]

`run` scores the professor-authored golden set (hit@k, MRR, per-chapter,
distance distributions) and STORES an eval_runs row — retrieval quality over
re-chunk/re-index history becomes a trend line, not a vibe. It also prints
suggested strong/weak thresholds from the observed distance distributions.

`replay` re-runs logged real queries (queries only — no user join) against
the current index and reports the score-distribution shift vs. what was
logged: the regression gate before flipping any KB/chunking change.

`judge` drives the REAL pipeline (`run_turn`, same intent router) to produce
the exact answer a student gets, then has an independent LLM judge score it on
six rubric dimensions (correctness, grounded, citations, scope, pedagogy,
addressed) — measuring whether the tutor is any GOOD, not just whether
retrieval hit. See `app/eval/judge.py`.

All arms are paced through the shared RateLimiter (sequential; `run`/`replay`
~3s/query, `judge` ~13s/question — it adds a generation + a judge call).
Requires GENAI_STUDIO_API_KEY.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime, timezone

import yaml

from ..config import load_settings
from ..course_map.resolver import CourseMapResolver, normalize_filename
from ..db import models as m
from ..db.engine import make_engine, make_session_factory
from ..gateway import Gateway
from ..grounding.retrieve import retrieve

HARNESS_VERSION = "1"


def _quantiles(vals: list[float]) -> dict:
    if not vals:
        return {}
    vs = sorted(vals)
    q = lambda p: vs[min(len(vs) - 1, int(p * len(vs)))]
    return {"p10": q(.10), "p25": q(.25), "p50": q(.50),
            "p75": q(.75), "p90": q(.90)}


def _match(expected: list[str], got_files: list[str]) -> int | None:
    """Rank (1-based) of the first retrieved file matching any expected
    basename glob-ish pattern; None if absent."""
    import fnmatch
    norm_expected = [e.lower() for e in expected]
    for rank, f in enumerate(got_files, start=1):
        base = normalize_filename(f)
        for pat in norm_expected:
            if fnmatch.fnmatch(base, pat) or pat in base:
                return rank
    return None


def cmd_run(args) -> int:
    settings = load_settings()
    if not settings.api_key:
        print("GENAI_STUDIO_API_KEY not set — cannot run live eval.")
        return 2
    resolver = CourseMapResolver.from_file(
        settings.backend_dir / "data" / "course_map.json")
    gateway = Gateway(settings)
    gateway.resolve_collections()

    golden_path = settings.resolve_path(args.golden)
    golden = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    questions = golden["questions"]
    print(f"Golden set: {len(questions)} questions (version "
          f"{golden.get('version', '?')}), k={args.k}")

    cfg = settings.retrieval.model_copy()
    cfg.k_webbook = args.k
    cfg.k_transcripts = args.k

    hits, rrs, top_dists, hit_dists = [], [], [], []
    per_chapter: dict[str, dict] = {}
    per_difficulty: dict[str, dict] = {}
    weak_count = 0
    # out-of-scope questions: success = correctly refused (tier no_evidence)
    oos_total, oos_correct, oos_scores = 0, 0, []
    miss_lines: list[str] = []

    for i, q in enumerate(questions, 1):
        # mirror the pipeline: syllabus questions retrieve with a modality bias
        query = q["question"]
        if q.get("modality") and q.get("type") == "syllabus":
            query = f"STAT 350 {q['modality']} section syllabus — {query}"
        rr = retrieve(gateway, resolver, query, cfg)
        top = rr.top_distance
        if q.get("out_of_scope"):
            oos_total += 1
            correct = rr.tier == "no_evidence"
            oos_correct += int(correct)
            if top is not None:
                oos_scores.append(top)
            mark = "✓" if correct else "✗"
            line = (f"  [{i:3}/{len(questions)}] {mark} OOS refused={correct} "
                    f"top={top if top is not None else '-':<8} {q['question'][:56]}")
            print(line)
            if not correct:
                miss_lines.append(line)
            continue

        files = [str(p.meta.get("name") or p.meta.get("source") or "")
                 for p in rr.passages]
        rank = _match(q.get("expected_sources", []), files)
        hit = rank is not None and rank <= args.k
        hits.append(hit)
        rrs.append(1.0 / rank if rank else 0.0)
        if top is not None:
            top_dists.append(top)
            if hit:
                hit_dists.append(top)
        if rr.tier == "no_evidence":
            weak_count += 1
        ch = str(q.get("chapter", "?"))
        entry = per_chapter.setdefault(ch, {"n": 0, "hits": 0})
        entry["n"] += 1
        entry["hits"] += int(hit)
        diff = str(q.get("difficulty", "?"))
        de = per_difficulty.setdefault(diff, {"n": 0, "hits": 0})
        de["n"] += 1
        de["hits"] += int(hit)
        mark = "✓" if hit else "✗"
        line = (f"  [{i:3}/{len(questions)}] {mark} rank={rank or '-':<3} "
                f"top={top if top is not None else '-':<8} {q['question'][:56]}")
        print(line)
        if not hit:
            miss_lines.append(line + f"   [want {q.get('expected_sources')}]")

    n_in = len(hits)
    hit_rate = sum(hits) / n_in if n_in else 0.0
    mrr = sum(rrs) / n_in if n_in else 0.0
    weak_rate = weak_count / n_in if n_in else 0.0

    print("\n===== RESULTS =====")
    print(f"in-scope: {n_in}   hit@{args.k}: {hit_rate:.3f}   MRR: {mrr:.3f}   "
          f"weak-rate: {weak_rate:.3f}")
    if oos_total:
        print(f"out-of-scope: {oos_total}   refusal-accuracy: "
              f"{oos_correct / oos_total:.3f}   (correctly weak/refused)")
    for ch in sorted(per_chapter, key=lambda c: (c == '?', c.zfill(2))):
        e = per_chapter[ch]
        flag = "  <-- LOW" if e["n"] and e["hits"] / e["n"] < 0.8 else ""
        print(f"  chapter {ch:>2}: {e['hits']}/{e['n']}{flag}")
    if per_difficulty:
        print("  by difficulty: " + "  ".join(
            f"{d}={e['hits']}/{e['n']}" for d, e in sorted(per_difficulty.items())))
    higher = settings.retrieval.higher_is_better
    print(f"top-score quantiles (in-scope hits, higher_is_better={higher}):",
          _quantiles(hit_dists))
    if oos_scores:
        print("top-score quantiles (out-of-scope):", _quantiles(oos_scores))
    if hit_dists and oos_scores:
        hq, oq = _quantiles(hit_dists), _quantiles(oos_scores)
        overlap = (hq["p10"] <= oq["p90"]) if higher else (hq["p90"] >= oq["p10"])
        # weak protects in-scope RECALL: sit just below the weakest real hits so
        # a question that retrieved the right section isn't falsely refused.
        # strong = median of hits (top half answers with no hedge).
        if higher:
            weak = round(hq["p10"] - 0.05, 3)
            strong = round(hq["p50"], 3)
        else:
            weak = round(hq["p90"] + 0.05, 3)
            strong = round(hq["p50"], 3)
        print(f"\nSuggested thresholds (protect in-scope recall) → "
              f"strong: {strong:.3f}  weak: {weak:.3f}")
        if overlap:
            print(f"  NOTE: in-scope hits (p10={hq['p10']:.3f}) and out-of-scope "
                  f"(p90={oq['p90']:.3f}) OVERLAP. A similarity threshold cannot "
                  "separate stats-adjacent out-of-scope questions — scope-guarding "
                  "belongs in the system prompt (the model reads the passages), "
                  "not the threshold. Set weak only to catch genuinely-empty "
                  "retrieval.")
    elif hit_dists:
        qs = _quantiles(hit_dists)
        strong, weak = (qs["p25"], max(0.0, qs["p10"] - 0.03)) if higher \
            else (qs["p75"], min(0.99, qs["p90"] * 1.15))
        print(f"\nSuggested thresholds → strong: {strong:.3f}  weak: {weak:.3f}   "
              "(add out_of_scope questions for a gap-based estimate)")
    if miss_lines:
        print(f"\n----- {len(miss_lines)} MISSES (fix golden globs or KB gaps) -----")
        for line in miss_lines:
            print(line)

    engine = make_engine(settings)
    from ..db.engine import ensure_schema
    ensure_schema(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        session.add(m.EvalRun(
            golden_set_version=str(golden.get("version", "?")),
            index_version=args.index_version, k=args.k,
            hit_rate=hit_rate, mrr=mrr, weak_rate=weak_rate,
            per_chapter={c: f"{e['hits']}/{e['n']}"
                         for c, e in per_chapter.items()},
            harness_version=HARNESS_VERSION))
        session.commit()
    print("Stored eval_runs row.")
    return 0 if hit_rate >= args.gate else 1


def cmd_replay(args) -> int:
    settings = load_settings()
    if not settings.api_key:
        print("GENAI_STUDIO_API_KEY not set — cannot run live replay.")
        return 2
    resolver = CourseMapResolver.from_file(
        settings.backend_dir / "data" / "course_map.json")
    gateway = Gateway(settings)
    gateway.resolve_collections()

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    from sqlalchemy import select
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) \
        if args.since else None
    with session_factory() as session:
        q = select(m.RetrievalEvent.rewritten_query, m.RetrievalEvent.top_score)
        if since is not None:
            q = q.where(m.RetrievalEvent.created_at >= since)
        rows = session.execute(q).all()
    seen, pairs = set(), []
    for query, old_top in rows:
        if query and query not in seen:
            seen.add(query)
            pairs.append((query, old_top))
    pairs = pairs[: args.sample]
    if not pairs:
        print("No logged queries to replay.")
        return 0

    higher = settings.retrieval.higher_is_better
    print(f"Replaying {len(pairs)} logged queries against the current index…")
    old_tops, new_tops, regressions = [], [], 0
    for i, (query, old_top) in enumerate(pairs, 1):
        rr = retrieve(gateway, resolver, query, settings.retrieval)
        if old_top is not None and rr.top_distance is not None:
            old_tops.append(old_top)
            new_tops.append(rr.top_distance)
            regressed = (rr.top_distance < old_top - 0.05) if higher \
                else (rr.top_distance > old_top + 0.05)
            regressions += int(regressed)
        if i % 25 == 0:
            print(f"  …{i}/{len(pairs)}")

    print("\n===== REPLAY =====")
    print("old top-score:", _quantiles(old_tops))
    print("new top-score:", _quantiles(new_tops))
    if old_tops:
        delta = statistics.mean(new_tops) - statistics.mean(old_tops)
        better = "higher = better" if higher else "lower = better"
        print(f"mean shift: {delta:+.4f}  ({better})   "
              f"regressed: {regressions}/{len(old_tops)}")
    return 0


def _print_judge_report(s: dict) -> None:
    from .judge import DIMENSIONS
    print("\n===== ANSWER-JUDGE RESULTS =====")
    if not s.get("n"):
        print(f"no answers judged ({s.get('errors', 0)} errors).")
        return
    print(f"judged: {s['n']}   errors: {s['errors']}   "
          f"mean score: {s['mean_score']:.3f} (0-1)")
    v = s["verdicts"]
    print(f"verdicts: pass {v['pass']} / borderline {v['borderline']} / fail {v['fail']}"
          f"   refusals: {s['refusals']}")
    dm = s["dimension_means"]
    print("by dimension (mean of 0-2):")
    print("  " + "   ".join(f"{d}={dm[d]:.2f}" for d in DIMENSIONS))
    weakest = min(dm, key=dm.get)
    print(f"  weakest: {weakest} ({dm[weakest]:.2f})")
    pc = s["per_chapter_mean"]
    if len(pc) > 1:
        print("by chapter (mean score): " + "  ".join(
            f"{c}={pc[c]:.2f}" + ("*" if pc[c] < 0.6 else "")
            for c in sorted(pc, key=lambda c: (c == "?", c.zfill(2)))))
    print(f"\n----- {len(s['worst'])} WEAKEST ANSWERS -----")
    for w in s["worst"]:
        mod = f" [{w['modality']}]" if w.get("modality") else ""
        print(f"  [{w['verdict']:10} {w['score']:.2f}] {w['question']}{mod}")
        print(f"       issue: {w['issue']}")


def cmd_judge(args) -> int:
    import json

    from .judge import (DIMENSIONS, JudgedItem, build_judge, generate_answer,
                        judge_answer, overall_score, summarize)

    settings = load_settings()
    if not settings.api_key:
        print("GENAI_STUDIO_API_KEY not set — cannot run the live answer-judge.")
        return 2
    resolver = CourseMapResolver.from_file(
        settings.backend_dir / "data" / "course_map.json")
    gateway = Gateway(settings)
    gateway.resolve_collections()
    tutor_core = (settings.backend_dir / "prompts" / "tutor_core.md").read_text(
        encoding="utf-8")

    golden = yaml.safe_load(settings.resolve_path(args.golden).read_text(encoding="utf-8"))
    questions = golden["questions"]
    if args.limit:
        questions = questions[: args.limit]
    judge_model = args.judge_model or settings.gateway.model
    print(f"Answer-judge: {len(questions)} questions (version "
          f"{golden.get('version', '?')})   judge model = {judge_model}")

    judge = build_judge(gateway, settings, model=args.judge_model)

    items: list = []
    detail: list = []
    errors = 0
    for i, q in enumerate(questions, 1):
        try:
            ar = generate_answer(gateway, resolver, settings, tutor_core, q)
        except Exception as exc:                                   # noqa: BLE001
            errors += 1
            print(f"  [{i:3}/{len(questions)}] gen-error {type(exc).__name__}: {exc}")
            continue
        v = judge_answer(judge, q, ar)
        if v is None:
            errors += 1
            print(f"  [{i:3}/{len(questions)}] judge-error (no verdict) — "
                  f"{q['question'][:50]}")
            continue
        score = overall_score(v)
        items.append(JudgedItem(
            question=q["question"], chapter=q.get("chapter"), kind=ar.kind,
            modality=ar.modality, refused=ar.refused, tier=ar.tier,
            verdict=v, score=score, answer=ar.answer))
        dims = " ".join(f"{d[:4]}={getattr(v, d)}" for d in DIMENSIONS)
        flag = "" if v.verdict == "pass" else f"  <-- {v.verdict}: {v.main_issue}"
        print(f"  [{i:3}/{len(questions)}] {v.verdict:10} {score:.2f}  {dims}{flag}")
        detail.append({
            "question": q["question"], "type": q.get("type"),
            "chapter": q.get("chapter"), "modality": ar.modality, "kind": ar.kind,
            "intent": ar.intent, "refused": ar.refused, "tier": ar.tier,
            "score": round(score, 3), "verdict": v.verdict,
            "main_issue": v.main_issue,
            "dimensions": {d: getattr(v, d) for d in DIMENSIONS},
            "expected_answer": q.get("expected_answer"),
            "hallucinated_markers": ar.hallucinated_markers, "answer": ar.answer})

    summary = summarize(items, errors=errors)
    _print_judge_report(summary)

    if args.out:
        out_path = settings.resolve_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(
            {"version": golden.get("version"), "judge_model": judge_model,
             "summary": summary, "items": detail}, indent=2), encoding="utf-8")
        print(f"\nWrote {len(detail)} judged answers → {out_path}")

    return 0 if summary.get("mean_score", 0.0) >= args.gate else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="eval.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="score the golden set")
    p_run.add_argument("--golden", default="data/golden_questions.yaml")
    p_run.add_argument("--k", type=int, default=8)
    p_run.add_argument("--gate", type=float, default=0.0,
                       help="exit nonzero if hit-rate falls below this")
    p_run.add_argument("--index-version", default=None)
    p_run.set_defaults(fn=cmd_run)
    p_rep = sub.add_parser("replay", help="re-run logged queries")
    p_rep.add_argument("--since", default=None)
    p_rep.add_argument("--sample", type=int, default=300)
    p_rep.set_defaults(fn=cmd_replay)
    p_judge = sub.add_parser("judge",
                             help="LLM-judge the GENERATED answers (quality, not retrieval)")
    p_judge.add_argument("--golden", default="data/golden_syllabus.yaml",
                         help="question set; golden_syllabus.yaml has reference answers")
    p_judge.add_argument("--limit", type=int, default=0,
                         help="judge only the first N questions (0 = all)")
    p_judge.add_argument("--judge-model", default=None,
                         help="judge model (default: the tutor model; a different "
                              "model reduces self-preference bias)")
    p_judge.add_argument("--out", default="data/answer_eval_report.json",
                         help="write per-answer detail JSON here ('' to skip)")
    p_judge.add_argument("--gate", type=float, default=0.0,
                         help="exit nonzero if the mean score falls below this")
    p_judge.set_defaults(fn=cmd_judge)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
