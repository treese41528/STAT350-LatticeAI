"""LLM-as-judge answer eval — score GENERATED tutor answers, not just retrieval.

`app.eval.harness run` measures whether we RETRIEVE the right passages (hit@k).
This measures whether the tutor's ANSWER is any good: correct, grounded in the
retrieved passages, properly cited, in-scope, pedagogically sound, and actually
on-question — via an independent LLM judge scoring six rubric dimensions that
map onto the tutor's real failure modes and the UI feedback tags.

Two halves:
  1. `generate_answer()` — reproduce the pipeline's grounded answer for one
     question (concept + syllabus paths), WITHOUT the DB / recorder / queue:
     just retrieve -> build_messages -> stream_chat -> lint_links. So it grades
     exactly the text a student would see (`done.finalText`).
  2. an SDK `Agent` judge (`output_schema=RubricVerdict`, greedy temp=0) scores
     it against the passages (+ a reference answer for syllabus questions).

Strictly SEQUENTIAL: the ~18 RPM gateway silently drops bursts, so answer-gen
and judge calls share the ONE `Gateway` RateLimiter and run one at a time.
`parallel_agents` would only serialize through that same limiter — no speedup,
more failure surface — so it is deliberately not used here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from ..config import Settings
from ..course_map.resolver import CourseMapResolver
from ..gateway import Gateway
from ..grounding.citations import (citations_payload, lint_links,
                                   resources_payload, validate_markers)
from ..grounding.pipeline import REFUSAL_MESSAGE, _restrict_to_syllabus
from ..grounding.prompt_builder import build_messages
from ..grounding.retrieve import RetrievalResult, retrieve
from ..grounding.rewrite import build_retrieval_query
from ..syllabus import resolve_current_term

DIMENSIONS = ("correctness", "grounded", "citations", "scope", "pedagogy", "addressed")

# ---------------------------------------------------------------------------
# 1. Answer generation (reproduces the pipeline's grounded answer, no DB)
# ---------------------------------------------------------------------------


@dataclass
class AnswerRun:
    question: str
    kind: str                       # "concept" | "syllabus"
    modality: Optional[str]
    answer: str
    refused: bool                   # tier == no_evidence -> tutor declines
    tier: str
    passages: list = field(default_factory=list)          # list[Passage]
    resolved_markers: list = field(default_factory=list)  # [n] that map to a passage
    hallucinated_markers: list = field(default_factory=list)  # [n] with no passage
    citations: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    error: Optional[str] = None


def generate_answer(gateway: Gateway, resolver: CourseMapResolver,
                    settings: Settings, tutor_core: str, q: dict) -> AnswerRun:
    """Question dict -> the grounded answer the student would get. Mirrors
    `pipeline._grounded_answer` minus streaming/telemetry/queue."""
    cfg = settings.retrieval
    modality = q.get("modality")
    kind = "syllabus" if q.get("type") == "syllabus" else "concept"
    term = resolve_current_term(settings)
    rewritten = build_retrieval_query([], q["question"])

    if kind == "syllabus" and modality:
        # Ground in the correct (term, modality): bias the query, retrieve
        # broadly, then keep ONLY this term+section's syllabus passages.
        rewritten = f"STAT 350 {term} {modality} section syllabus — {rewritten}"
        syl_cfg = cfg.model_copy(update={
            "k_webbook": max(cfg.k_webbook, 14), "max_passages": 14,
            "min_transcript_slots": 0})
        rr: RetrievalResult = retrieve(gateway, resolver, rewritten, syl_cfg,
                                       shrink=False, single_call=False)
        _restrict_to_syllabus(rr, term, modality, cfg.higher_is_better)
    else:
        rr = retrieve(gateway, resolver, rewritten, cfg, shrink=False,
                      single_call=getattr(cfg, "single_call", False))

    common = dict(question=q["question"], kind=kind, modality=modality,
                  tier=rr.tier, passages=rr.passages, error=rr.error)

    if rr.tier == "no_evidence":
        # A weak-retrieval refusal IS the pipeline's behaviour here — the judge
        # decides whether declining was appropriate for this question.
        return AnswerRun(answer=REFUSAL_MESSAGE, refused=True,
                         resources=resources_payload(rr.passages, resolver),
                         **common)

    messages = build_messages(
        tutor_core, rr.passages, [], q["question"], modality=modality,
        caveat=(rr.tier == "caveat"), syllabus=(kind == "syllabus"),
        term=term if kind == "syllabus" else None)
    raw = "".join(gateway.stream_chat(messages, max_tokens=settings.generation.max_tokens))
    answer, _removed = lint_links(raw, resolver)
    resolved, hallucinated = validate_markers(answer, rr.passages)
    return AnswerRun(answer=answer, refused=False,
                     resolved_markers=resolved, hallucinated_markers=hallucinated,
                     citations=citations_payload(rr.passages),
                     resources=resources_payload(rr.passages, resolver), **common)


# ---------------------------------------------------------------------------
# 2. The LLM judge
# ---------------------------------------------------------------------------


class RubricVerdict(BaseModel):
    """Flat schema (scalars only) — most reliable to extract+validate from
    gpt-oss:120b, which has no native tool-calling on this gateway."""
    correctness: int = Field(ge=0, le=2)
    grounded: int = Field(ge=0, le=2)
    citations: int = Field(ge=0, le=2)
    scope: int = Field(ge=0, le=2)
    pedagogy: int = Field(ge=0, le=2)
    addressed: int = Field(ge=0, le=2)
    verdict: str            # "pass" | "borderline" | "fail"
    main_issue: str         # single biggest problem, or "none"


JUDGE_SYSTEM = """You are a meticulous grader for the STAT 350 (introductory statistics) AI tutor at Purdue. \
You score the tutor's ANSWER to a student question — not the question itself. You are given the student's question, \
the course passages the tutor retrieved (the GROUND TRUTH it must stay faithful to), the tutor's answer, and — for \
syllabus/logistics questions — the correct reference answer.

Score each of six dimensions as the integer 0, 1, or 2 (0 = fails, 1 = partial, 2 = fully meets):

- correctness: Is the statistics/math right? Correct formulas, test choice, conclusion, notation, and upper-tail \
critical-value convention. If a reference answer is given, does the tutor's value MATCH it for the stated section/modality? \
Wrong number, wrong procedure, or wrong conclusion = 0.
- grounded: Are the claims supported by the retrieved passages? Penalise any fact, number, or attribution the passages \
do not support. If the passages lack the answer and the tutor invented one, score 0.
- citations: Does it cite sources as [n] markers that match the passages and avoid inventing URLs? You are told which \
[n] markers are valid vs. hallucinated (point to no real passage).
- scope: Does it stay within STAT 350 — answering in-scope questions, and for genuinely out-of-scope or graded-assessment \
requests, declining or flagging "beyond scope"? Refusing a fair, in-scope question is a failure, not good caution.
- pedagogy: The right teaching stance FOR THE QUESTION TYPE. For conceptual / problem-solving questions the tutor should \
GUIDE with hints and questions, not dump a full worked solution — a complete solution to a "solve this for me" request is \
a pedagogy failure. For factual / logistics questions (syllabus, what's on the exam), a DIRECT correct answer is right — \
do NOT penalise directness there.
- addressed: Does the answer actually address what was asked (not a tangent, not a non-answer)?

If the tutor REFUSED ("I couldn't find this in the course materials"): that is CORRECT only if the question is genuinely \
outside STAT 350 or asks for graded answers; otherwise correctness and addressed should be low.

Then give:
- verdict: "pass" (a student is well served), "borderline" (usable but flawed), or "fail" (wrong, ungrounded, or unhelpful).
- main_issue: one short phrase naming the single biggest problem, or "none".

Grade ONLY what is present; do not reward length. Be strict about correctness and grounding."""


def build_judge(gateway: Gateway, settings: Settings, model: str | None = None):
    """An SDK Agent that emits a validated RubricVerdict. Reuses the app's ONE
    studio client + RateLimiter so judge calls share the shared-key RPM bucket.
    Default judge model = the tutor model; pass a different one to reduce
    self-preference bias."""
    from genai_studio.agents import Agent, GenAIStudioClient, NullTracer
    client = GenAIStudioClient(
        gateway.studio,
        default_model=model or settings.gateway.model,
        native_tools=False,                 # gpt-oss:120b -> JSON-in-prompt path
        rate_limiter=gateway.limiter,       # SHARE the one bucket per key
    )
    return Agent(client=client, system=JUDGE_SYSTEM, output_schema=RubricVerdict,
                 temperature=0.0, tracer=NullTracer(),
                 sampling={"max_tokens": 2000})   # reasoning model needs headroom


def _passage_block(ar: AnswerRun, limit: int = 8) -> str:
    if not ar.passages:
        return "(none — retrieval found nothing)"
    return "\n\n".join(
        f"[{p.n}] ({p.collection}; {(p.meta or {}).get('name') or (p.meta or {}).get('source') or '?'})"
        f"\n{p.text[:800]}"
        for p in ar.passages[:limit])


def judge_prompt(q: dict, ar: AnswerRun) -> str:
    parts = [f"QUESTION TYPE: {q.get('type', 'concept')}"
             + (f"   |   SECTION/MODALITY: {ar.modality}" if ar.modality else ""),
             f"\nSTUDENT QUESTION:\n{q['question']}"]
    if q.get("expected_answer"):
        parts.append(f"\nCORRECT REFERENCE ANSWER (for this modality):\n{q['expected_answer']}")
    parts.append(f"\nRETRIEVED COURSE PASSAGES (ground truth):\n{_passage_block(ar)}")
    if ar.refused:
        parts.append("\nNOTE: the tutor REFUSED — it said it could not find the material.")
    else:
        parts.append(f"\nCITATION MARKERS — valid: {ar.resolved_markers or 'none'}   "
                     f"hallucinated (no such passage): {ar.hallucinated_markers or 'none'}")
    parts.append(f"\nTUTOR ANSWER:\n{ar.answer}")
    parts.append("\nScore the six dimensions (0/1/2), then give verdict and main_issue.")
    return "\n".join(parts)


def judge_answer(judge, q: dict, ar: AnswerRun) -> Optional[RubricVerdict]:
    """Run the judge; return the verdict, or None on judge error (caller counts
    it as an error rather than a score)."""
    try:
        result = judge.run(judge_prompt(q, ar))
    except Exception:
        return None
    return getattr(result, "output", None)


# ---------------------------------------------------------------------------
# 3. Scoring + aggregation (pure — unit-testable without a gateway)
# ---------------------------------------------------------------------------


def overall_score(v: RubricVerdict) -> float:
    """Mean of the six dimensions normalised to 0..1."""
    return sum(getattr(v, d) for d in DIMENSIONS) / (2 * len(DIMENSIONS))


@dataclass
class JudgedItem:
    question: str
    chapter: object
    kind: str
    modality: Optional[str]
    refused: bool
    tier: str
    verdict: RubricVerdict
    score: float
    answer: str


def summarize(items: list[JudgedItem], errors: int = 0) -> dict:
    """Aggregate judged items into report metrics. Pure function."""
    n = len(items)
    if n == 0:
        return {"n": 0, "errors": errors}
    dim_means = {d: sum(getattr(it.verdict, d) for it in items) / n for d in DIMENSIONS}
    verdicts = {"pass": 0, "borderline": 0, "fail": 0}
    for it in items:
        verdicts[it.verdict.verdict if it.verdict.verdict in verdicts else "borderline"] += 1
    per_chapter: dict = {}
    for it in items:
        key = str(it.chapter) if it.chapter is not None else "?"
        per_chapter.setdefault(key, []).append(it.score)
    per_chapter_mean = {c: sum(v) / len(v) for c, v in per_chapter.items()}
    worst = sorted(items, key=lambda it: it.score)[:min(10, n)]
    return {
        "n": n,
        "errors": errors,
        "mean_score": sum(it.score for it in items) / n,
        "dimension_means": dim_means,
        "verdicts": verdicts,
        "refusals": sum(1 for it in items if it.refused),
        "per_chapter_mean": per_chapter_mean,
        "worst": [
            {"score": round(it.score, 2), "verdict": it.verdict.verdict,
             "issue": it.verdict.main_issue, "question": it.question[:90],
             "modality": it.modality}
            for it in worst
        ],
    }
