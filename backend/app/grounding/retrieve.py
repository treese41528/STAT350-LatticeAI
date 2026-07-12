"""Retrieval over both knowledge collections, with origin labels and tiering.

We call the gateway's retrieval endpoint per collection (default) so passages
stay labeled webbook vs transcript. `retrieval.single_call: true` (set after
Phase 0 probe #3 confirms row↔collection ordering) fuses them into one request
and saves an RPM slot per question.

Distances are Chroma-style: LOWER is better. Tier thresholds are calibrated by
the eval harness, never guessed.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field

from ..course_map.resolver import CourseMapResolver, ResolvedSource
from ..config import RetrievalCfg
from ..gateway import Gateway


@dataclass
class Passage:
    n: int                      # 1-based citation number, assigned after merge
    collection: str             # webbook | transcript
    text: str
    distance: float | None      # raw gateway score (see RetrievalCfg.higher_is_better)
    meta: dict
    resolved: ResolvedSource | None = None
    similarity: float = 0.5     # 0..1 for the UI meter, set during retrieve()


@dataclass
class RetrievalResult:
    passages: list[Passage] = field(default_factory=list)
    tier: str = "no_evidence"   # strong | caveat | no_evidence
    top_distance: float | None = None
    mean_distance: float | None = None
    latency_ms: int = 0
    per_collection_counts: dict = field(default_factory=dict)
    error: str | None = None


def _flat(arr):
    if not arr:
        return []
    if isinstance(arr[0], list):
        return [x for row in arr for x in row]
    return list(arr)


def _rows(payload: dict, key: str) -> list:
    """Return the row-structure (list per collection) if present, else a
    single flat row."""
    arr = payload.get(key)
    if not arr:
        return []
    if isinstance(arr[0], list):
        return arr
    return [arr]


def _parse_single(payload: dict, collection: str) -> list[Passage]:
    docs = _flat(payload.get("documents"))
    dists = _flat(payload.get("distances"))
    metas = _flat(payload.get("metadatas"))
    out = []
    for i, doc in enumerate(docs):
        out.append(Passage(
            n=0, collection=collection, text=str(doc),
            distance=float(dists[i]) if i < len(dists) and dists[i] is not None else None,
            meta=metas[i] if i < len(metas) and isinstance(metas[i], dict) else {},
        ))
    return out


def _dedupe_key(p: Passage) -> str:
    name = str(p.meta.get("name") or p.meta.get("source") or p.meta.get("file_id") or "")
    prefix = p.text[:120]
    return hashlib.sha1(f"{name}|{prefix}".encode()).hexdigest()


def retrieve(gateway: Gateway, resolver: CourseMapResolver, query: str,
             cfg: RetrievalCfg, *, shrink: bool = False,
             single_call: bool = False) -> RetrievalResult:
    """Blocking; run via run_sync(). Never raises — an error yields an empty
    no_evidence result with .error set (fail-open on discovery)."""
    t0 = time.monotonic()
    k_web = max(1, cfg.k_webbook // 2) if shrink else cfg.k_webbook
    k_tr = max(1, cfg.k_transcripts // 2) if shrink else cfg.k_transcripts
    web_id = gateway.kb_ids.get("webbook")
    tr_id = gateway.kb_ids.get("transcripts")

    passages: list[Passage] = []
    error = None
    try:
        if single_call and web_id and tr_id:
            payload = gateway.retrieval_query(query, [web_id, tr_id],
                                              k=max(k_web, k_tr))
            doc_rows = _rows(payload, "documents")
            dist_rows = _rows(payload, "distances")
            meta_rows = _rows(payload, "metadatas")
            labels = ["webbook", "transcript"]
            for idx, docs in enumerate(doc_rows):
                label = labels[idx] if idx < len(labels) else "webbook"
                sub = {
                    "documents": docs,
                    "distances": dist_rows[idx] if idx < len(dist_rows) else [],
                    "metadatas": meta_rows[idx] if idx < len(meta_rows) else [],
                }
                passages.extend(_parse_single(sub, label))
        else:
            if web_id:
                payload = gateway.retrieval_query(query, [web_id], k=k_web)
                passages.extend(_parse_single(payload, "webbook"))
            if tr_id:
                payload = gateway.retrieval_query(query, [tr_id], k=k_tr)
                passages.extend(_parse_single(payload, "transcript"))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    higher = cfg.higher_is_better

    def clears_weak(score: float) -> bool:
        return score >= cfg.thresholds.weak if higher else score <= cfg.thresholds.weak

    # dedupe, sort best-first (None last), cap with transcript floor
    seen: set[str] = set()
    unique: list[Passage] = []
    for p in passages:
        key = _dedupe_key(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    # best-first: descending score when higher_is_better, else ascending
    unique.sort(key=lambda p: (p.distance is None,
                               -p.distance if (higher and p.distance is not None)
                               else (p.distance if p.distance is not None else 0.0)))

    max_p = max(2, cfg.max_passages // 2) if shrink else cfg.max_passages
    kept: list[Passage] = unique[:max_p]
    # guarantee transcript representation when transcripts cleared the weak bar
    floor = 0 if shrink else cfg.min_transcript_slots
    have_tr = sum(1 for p in kept if p.collection == "transcript")
    if have_tr < floor:
        extra_tr = [p for p in unique[max_p:]
                    if p.collection == "transcript"
                    and p.distance is not None and clears_weak(p.distance)]
        need = min(floor - have_tr, len(extra_tr), len(kept))
        if need > 0:
            # replace the weakest `need` non-transcript tail slots in one shot
            kept[-need:] = extra_tr[:need]

    # label, resolve, and set UI similarity
    for i, p in enumerate(kept, start=1):
        p.n = i
        p.resolved = (resolver.resolve_webbook(p.meta) if p.collection == "webbook"
                      else resolver.resolve_transcript(p.meta))
        if p.distance is None:
            p.similarity = 0.5
        else:
            raw = float(p.distance)
            p.similarity = max(0.0, min(1.0, raw if higher else 1.0 - raw))

    scores = [p.distance for p in kept if p.distance is not None]
    top = (max(scores) if higher else min(scores)) if scores else None
    mean = sum(scores) / len(scores) if scores else None
    if not kept or top is None:
        tier = "no_evidence" if not kept else "caveat"
    elif (top >= cfg.thresholds.strong) if higher else (top <= cfg.thresholds.strong):
        tier = "strong"
    elif clears_weak(top):
        tier = "caveat"
    else:
        tier = "no_evidence"

    return RetrievalResult(
        passages=kept, tier=tier, top_distance=top, mean_distance=mean,
        latency_ms=int((time.monotonic() - t0) * 1000),
        per_collection_counts={
            "webbook": sum(1 for p in kept if p.collection == "webbook"),
            "transcript": sum(1 for p in kept if p.collection == "transcript"),
        },
        error=error,
    )
