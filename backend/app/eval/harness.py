"""Retrieval-quality eval harness.

    python -m app.eval run     [--golden data/golden_questions.yaml] [--k 8]
    python -m app.eval replay  [--since 2026-08-01] [--sample 300]

`run` scores the professor-authored golden set (hit@k, MRR, per-chapter,
distance distributions) and STORES an eval_runs row — retrieval quality over
re-chunk/re-index history becomes a trend line, not a vibe. It also prints
suggested strong/weak thresholds from the observed distance distributions.

`replay` re-runs logged real queries (queries only — no user join) against
the current index and reports the score-distribution shift vs. what was
logged: the regression gate before flipping any KB/chunking change.

Both are paced through the shared RateLimiter (sequential; ~3s/query at
rpm=18). Requires GENAI_STUDIO_API_KEY.
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
    weak_count = 0

    for i, q in enumerate(questions, 1):
        rr = retrieve(gateway, resolver, q["question"], cfg)
        files = [str(p.meta.get("name") or p.meta.get("source") or "")
                 for p in rr.passages]
        rank = _match(q.get("expected_sources", []), files)
        hit = rank is not None and rank <= args.k
        hits.append(hit)
        rrs.append(1.0 / rank if rank else 0.0)
        if rr.top_distance is not None:
            top_dists.append(rr.top_distance)
            if hit:
                hit_dists.append(rr.top_distance)
        if rr.tier == "no_evidence":
            weak_count += 1
        ch = str(q.get("chapter", "?"))
        entry = per_chapter.setdefault(ch, {"n": 0, "hits": 0})
        entry["n"] += 1
        entry["hits"] += int(hit)
        mark = "✓" if hit else "✗"
        print(f"  [{i:3}/{len(questions)}] {mark} rank={rank or '-':<3} "
              f"top={rr.top_distance if rr.top_distance is not None else '-':<8} "
              f"{q['question'][:60]}")

    hit_rate = sum(hits) / len(hits) if hits else 0.0
    mrr = sum(rrs) / len(rrs) if rrs else 0.0
    weak_rate = weak_count / len(questions) if questions else 0.0

    print("\n===== RESULTS =====")
    print(f"hit@{args.k}: {hit_rate:.3f}   MRR: {mrr:.3f}   "
          f"weak-rate: {weak_rate:.3f}")
    for ch in sorted(per_chapter, key=lambda c: (c == '?', c.zfill(2))):
        e = per_chapter[ch]
        print(f"  chapter {ch:>2}: {e['hits']}/{e['n']}")
    print("top-distance quantiles (all):", _quantiles(top_dists))
    print("top-distance quantiles (hits):", _quantiles(hit_dists))
    if hit_dists:
        qs = _quantiles(hit_dists)
        print(f"\nSuggested thresholds → strong: {qs['p75']:.3f}  "
              f"weak: {min(0.99, qs['p90'] * 1.15):.3f}   "
              "(update config.yaml retrieval.thresholds after review)")

    engine = make_engine(settings)
    from ..db.base import Base
    Base.metadata.create_all(engine)
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

    print(f"Replaying {len(pairs)} logged queries against the current index…")
    old_tops, new_tops, regressions = [], [], 0
    for i, (query, old_top) in enumerate(pairs, 1):
        rr = retrieve(gateway, resolver, query, settings.retrieval)
        if old_top is not None and rr.top_distance is not None:
            old_tops.append(old_top)
            new_tops.append(rr.top_distance)
            if rr.top_distance > old_top + 0.05:
                regressions += 1
        if i % 25 == 0:
            print(f"  …{i}/{len(pairs)}")

    print("\n===== REPLAY =====")
    print("old top-distance:", _quantiles(old_tops))
    print("new top-distance:", _quantiles(new_tops))
    if old_tops:
        delta = statistics.mean(new_tops) - statistics.mean(old_tops)
        print(f"mean shift: {delta:+.4f}  (negative = better)   "
              f"regressed >0.05: {regressions}/{len(old_tops)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.eval")
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
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
