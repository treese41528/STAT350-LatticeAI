"""The default answer path: one streamed LLM call per concept question,
deterministic answers for everything else.

Yields (event, data) tuples; api/sse.py frames them. Telemetry rides the
recorder (never awaited). The token stream is provisional — `done.finalText`
is canonical after link linting, and the SPA swaps it in.
"""

from __future__ import annotations

import time
import uuid
from typing import AsyncIterator

from ..concurrency import aiter_sync, run_sync
from ..db import models as m
from ..queueing import QueueFullError
from .citations import (catalog_card_for, citations_payload, lint_links,
                        resources_payload, validate_markers)
from .prompt_builder import build_messages
from .retrieve import RetrievalResult, retrieve
from .rewrite import build_retrieval_query
from .router import Route, route
from ..syllabus import (resolve_current_term, resolve_syllabus_links,
                        select_syllabus_passages)

SMALLTALK_REPLY = (
    "Hi! I'm the STAT 350 tutor. I answer from the course webbook and lecture "
    "transcripts and cite my sources. Ask me about a concept, a worksheet, R "
    "code, or what's on an exam — and if you're stuck on a problem, paste it "
    "in and we'll work through it step by step."
)

REFUSAL_MESSAGE = (
    "I couldn't find anything in the STAT 350 course materials that covers "
    "this, so I won't guess. If you think it should be covered, try rephrasing "
    "with the terms the course uses — or use \"Dig deeper\" and I'll search "
    "harder. The closest material I do have is linked below."
)

MODALITY_PROMPT = (
    "Which section of STAT 350 are you enrolled in? **Flipped**, **Traditional "
    "Lecture**, **Traditional Lecture (Indianapolis)**, **Asynchronous Online**, "
    "**Winter Session**, or **Summer Session**? I'll pull the right syllabus and "
    "schedule. (You can also set this once in Settings.)"
)

OVERLOAD_MESSAGE = (
    "The tutor is at capacity right now (it happens before exams!). While you "
    "wait, the linked course materials below are the best place to start — "
    "then try me again in a few minutes."
)

SYLLABUS_FALLBACK = (
    "I couldn't find that specific detail in the syllabus text I can search, so "
    "I don't want to guess on a policy. Your section's official syllabus and "
    "schedule are linked below — they're the authoritative source. If you tell "
    "me the exact policy you're after (grading weights, make-up exams, "
    "deadlines…), I can try again."
)


def _restrict_to_syllabus(rr: RetrievalResult, term: str, modality: str,
                          higher_is_better: bool) -> None:
    """Keep only current-term, this-section syllabus passages, in place. If none
    survive, tier becomes no_evidence so the caller links the official PDF."""
    kept = select_syllabus_passages(rr.passages, term, modality)
    for i, p in enumerate(kept, start=1):
        p.n = i
    rr.passages = kept
    rr.per_collection_counts = {"webbook": len(kept), "transcript": 0}
    if not kept:
        rr.tier = "no_evidence"
        rr.top_distance = rr.mean_distance = None
        return
    scores = [p.distance for p in kept if p.distance is not None]
    rr.top_distance = (max(scores) if higher_is_better else min(scores)) if scores else None
    rr.mean_distance = sum(scores) / len(scores) if scores else None
    # a filename match is authoritative grounding, so treat it as strong
    rr.tier = "strong"


def _syllabus_cards(deps, modality: str | None) -> list[dict]:
    links = resolve_syllabus_links(deps.settings, deps.resolver, modality)
    if links is None:
        return []
    label, pdf, schedule = links
    cards = []
    if pdf:
        cards.append({"kind": "syllabus", "title": f"Syllabus — {label}",
                      "url": pdf, "meta": "Official — authoritative"})
    if schedule:
        cards.append({"kind": "schedule", "title": f"Schedule — {label}",
                      "url": schedule, "meta": None})
    return cards


class TurnContext:
    """Everything the pipeline needs for one question."""

    def __init__(self, deps, *, user_row_id: str, conversation_id: str,
                 history: list[dict], message: str, modality: str | None,
                 shrink: bool, escalation_enabled: bool):
        self.deps = deps
        self.user_row_id = user_row_id
        self.conversation_id = conversation_id
        self.history = history
        self.message = message
        self.modality = modality
        self.shrink = shrink
        self.escalation_enabled = escalation_enabled
        self.reject = False
        self.request_id = str(uuid.uuid4())
        self.user_msg_id = str(uuid.uuid4())
        self.assistant_msg_id = str(uuid.uuid4())


def _persist_user_message(ctx: TurnContext, seq: int) -> None:
    ctx.deps.recorder.emit(m.Message(
        id=ctx.user_msg_id, conversation_id=ctx.conversation_id, seq=seq,
        role="user", content=ctx.message, request_id=ctx.request_id))


def _persist_assistant(ctx: TurnContext, seq: int, *, content: str,
                       answer_kind: str, intent: str,
                       finish_reason: str = "stop", latency_ms: int | None = None,
                       ttft_ms: int | None = None) -> None:
    ctx.deps.recorder.emit(m.Message(
        id=ctx.assistant_msg_id, conversation_id=ctx.conversation_id,
        seq=seq + 1, role="assistant", content=content,
        model=ctx.deps.settings.gateway.model, latency_ms=latency_ms,
        ttft_ms=ttft_ms, finish_reason=finish_reason, answer_kind=answer_kind,
        intent=intent, request_id=ctx.request_id))


def _persist_retrieval(ctx: TurnContext, rr: RetrievalResult,
                       raw_query: str, rewritten: str) -> str:
    rid = str(uuid.uuid4())
    ctx.deps.recorder.emit(m.RetrievalEvent(
        id=rid, request_id=ctx.request_id,
        question_message_id=ctx.user_msg_id,
        conversation_id=ctx.conversation_id,
        raw_query=raw_query, rewritten_query=rewritten,
        k_requested=ctx.deps.settings.retrieval.k_webbook,
        collections_queried=dict(ctx.deps.gateway.kb_ids),
        results=[{
            "collection": p.collection,
            "source_file": str(p.meta.get("name") or p.meta.get("source") or ""),
            "chunk_id": str(p.meta.get("file_id") or p.meta.get("id") or ""),
            "score": p.distance, "rank": p.n,
            "resolved_match": p.resolved.match if p.resolved else "none",
            "v": 1,
        } for p in rr.passages],
        top_score=rr.top_distance, mean_score=rr.mean_distance,
        retrieval_latency_ms=rr.latency_ms, tier=rr.tier,
        weak=rr.tier != "strong",
        weak_reason=(rr.error or ("no_results" if not rr.passages else
                                  "low_top_score" if rr.tier == "no_evidence" else None)),
    ))
    return rid


def _persist_citations(ctx: TurnContext, rr: RetrievalResult, rid: str,
                       final_text: str) -> None:
    resolved, unresolved = validate_markers(final_text, rr.passages)
    by_n = {p.n: p for p in rr.passages}
    for n in resolved:
        p = by_n[n]
        ctx.deps.recorder.emit(m.Citation(
            message_id=ctx.assistant_msg_id, marker=n, retrieval_event_id=rid,
            rank_in_results=n,
            source_file=str(p.meta.get("name") or p.meta.get("source") or ""),
            collection=p.collection, resolved=True))
    for n in unresolved:
        ctx.deps.recorder.emit(m.Citation(
            message_id=ctx.assistant_msg_id, marker=n, retrieval_event_id=rid,
            resolved=False))


async def run_turn(ctx: TurnContext, seq: int) -> AsyncIterator[tuple[str, dict]]:
    deps = ctx.deps
    t_start = time.monotonic()
    yield "meta", {"conversationId": ctx.conversation_id,
                   "messageId": ctx.assistant_msg_id, "mode": "default"}
    _persist_user_message(ctx, seq)

    r: Route = route(ctx.message, deps.resolver, ctx.modality)

    # A syllabus-content question needs the modality first; once known, it goes
    # through the grounded path (below) to QUOTE the syllabus, not just link it.
    if r.intent == "syllabus_content" and r.needs_modality:
        r = Route(intent="syllabus_schedule", sections=r.sections,
                  needs_modality=True)

    # ---- deterministic branches (no LLM, no queue) ---------------------------
    if r.intent == "smalltalk":
        yield "token", {"text": SMALLTALK_REPLY}
        yield "done", {"messageId": ctx.assistant_msg_id, "finishReason": "stop",
                       "finalText": SMALLTALK_REPLY, "flags": {}}
        _persist_assistant(ctx, seq, content=SMALLTALK_REPLY,
                           answer_kind="smalltalk", intent=r.intent,
                           latency_ms=int((time.monotonic() - t_start) * 1000))
        return

    if r.intent in ("resource_lookup", "exam_info", "syllabus_schedule"):
        async for ev in _deterministic_turn(ctx, r, seq, t_start):
            yield ev
        return

    # ---- concept question: retrieval + one streamed LLM call ------------------
    if not deps.gateway_ready:
        text = ("The tutor can't reach the course knowledge base right now. "
                "Please try again shortly — meanwhile the course website links "
                "below are the best resource.")
        cards = [c.to_dict() for c in deps.resolver.cards_for_sections(r.sections[:2])]
        if cards:
            yield "resources", {"resources": cards}
        yield "error", {"code": "gateway_unavailable", "message": text,
                        "retryable": True}
        deps.recorder.emit(m.ErrorEvent(
            scope="app", error_type="gateway_unavailable",
            request_id=ctx.request_id, user_id=ctx.user_row_id,
            conversation_id=ctx.conversation_id))
        return

    try:
        if ctx.reject:
            raise QueueFullError()
        async for ev in _queued_grounded_answer(ctx, r, seq, t_start):
            yield ev
    except QueueFullError:
        cards = [c.to_dict() for c in deps.resolver.cards_for_sections(r.sections[:3])]
        if cards:
            yield "resources", {"resources": cards}
        yield "refusal", {"reason": "out_of_scope", "message": OVERLOAD_MESSAGE}
        yield "done", {"messageId": ctx.assistant_msg_id, "finishReason": "refusal",
                       "finalText": OVERLOAD_MESSAGE, "flags": {"refusal": True}}
        deps.recorder.emit(m.ErrorEvent(
            scope="overload_shed", error_type="queue_full",
            request_id=ctx.request_id, user_id=ctx.user_row_id))
        _persist_assistant(ctx, seq, content=OVERLOAD_MESSAGE,
                           answer_kind="refusal", intent=r.intent,
                           finish_reason="refusal")


# --------------------------------------------------------------------------- #
# deterministic branches
# --------------------------------------------------------------------------- #

async def _deterministic_turn(ctx: TurnContext, r: Route, seq: int,
                              t_start: float) -> AsyncIterator[tuple[str, dict]]:
    deps = ctx.deps
    resolver = deps.resolver
    cards: list[dict] = []
    lines: list[str] = []

    if r.intent == "exam_info":
        exam = resolver.exam_info(r.exam_key or "1")
        if exam:
            lines.append(f"**{exam.label}** covers:")
            lines += [f"- {t}" for t in exam.topics]
            secs = []
            for chn in exam.chapters:
                ch = resolver.lookup_chapter(chn)
                if ch:
                    secs.extend(list(ch.sections.values())[:1])
                for ws in resolver.worksheets_for_chapter(chn)[:1]:
                    cards.append({"kind": "worksheet",
                                  "title": f"Worksheet {ws.number}: {ws.title}",
                                  "url": ws.url, "meta": f"Chapter {chn}"})
            cards = ([{"kind": "exam", "title": "Exams hub — past exams & info",
                       "url": resolver.map.hubs.get("exams", ""), "meta": None}]
                     + cards[:6])
            lines.append("\nWorksheets are the best practice — start with the "
                         "ones linked below, and ask me about any topic you "
                         "want to drill into.")
        else:
            lines.append("I couldn't tell which exam you mean — Exam 1, Exam 2, "
                         "or the Final?")

    elif r.intent == "syllabus_schedule":
        links = resolve_syllabus_links(deps.settings, resolver, ctx.modality) \
            if not r.needs_modality else None
        if links is not None:
            label, pdf, schedule = links
            lines.append(f"Here's the official information for your section "
                         f"(**{label}**) — the link(s) below are the "
                         f"authoritative source for dates and policies.")
            if pdf:
                cards.append({"kind": "syllabus", "title": f"Syllabus — {label}",
                              "url": pdf, "meta": None})
            if schedule:
                cards.append({"kind": "schedule", "title": f"Schedule — {label}",
                              "url": schedule, "meta": None})
        else:
            lines.append(MODALITY_PROMPT)

    else:  # resource_lookup
        sections = r.sections[:3]
        if r.worksheet is not None:
            ws = resolver.lookup_worksheet(r.worksheet)
            if ws:
                cards.append({"kind": "worksheet",
                              "title": f"Worksheet {ws.number}: {ws.title}",
                              "url": ws.url,
                              "meta": f"Chapters {', '.join(map(str, ws.chapters))}"
                                      if ws.chapters else None})
        if r.chapter is not None and not sections:
            ch = resolver.lookup_chapter(r.chapter)
            if ch:
                sections = list(ch.sections.values())[:3]
        cards.extend(c.to_dict() for c in resolver.cards_for_sections(
            sections, include_worksheets=r.worksheet is None,
            include_simulations=r.wants_simulation or True))
        lines.append("Here's what you're looking for:" if cards else
                     "I couldn't match that to a specific course page — can you "
                     "give me a section number (like 7.3) or a topic name?")

    text = "\n".join(lines)
    if cards:
        yield "resources", {"resources": cards}
    yield "token", {"text": text}
    yield "done", {"messageId": ctx.assistant_msg_id, "finishReason": "stop",
                   "finalText": text, "flags": {}}
    _persist_assistant(ctx, seq, content=text, answer_kind="resource_lookup",
                       intent=r.intent,
                       latency_ms=int((time.monotonic() - t_start) * 1000))


# --------------------------------------------------------------------------- #
# grounded LLM branch
# --------------------------------------------------------------------------- #

import asyncio


async def _queued_grounded_answer(ctx: TurnContext, r: Route, seq: int,
                                  t_start: float) -> AsyncIterator[tuple[str, dict]]:
    """Acquire an LLM slot, yielding live queue-position events while waiting."""
    pos_q: asyncio.Queue = asyncio.Queue()

    async def on_position(pos: int) -> None:
        pos_q.put_nowait(pos)

    slot_cm = ctx.deps.llm_queue.slot(on_position)
    enter_task = asyncio.ensure_future(slot_cm.__aenter__())
    entered = False
    try:
        while not enter_task.done():
            await asyncio.wait({enter_task}, timeout=0.25)
            while not pos_q.empty():
                pos = pos_q.get_nowait()
                yield "queue", {"position": pos, "etaSeconds": pos * 8}
        await enter_task  # propagates QueueFullError
        entered = True
        async for ev in _grounded_answer(ctx, r, seq, t_start):
            yield ev
    finally:
        if entered:
            await slot_cm.__aexit__(None, None, None)
        elif enter_task.done() and not enter_task.cancelled() \
                and enter_task.exception() is None:
            # acquired between checks but generator was closed before use
            await slot_cm.__aexit__(None, None, None)
        elif not enter_task.done():
            enter_task.cancel()


async def _grounded_answer(ctx: TurnContext, r: Route, seq: int,
                           t_start: float) -> AsyncIterator[tuple[str, dict]]:
    deps = ctx.deps
    cfg = deps.settings.retrieval

    syllabus_mode = r.intent == "syllabus_content"
    term = resolve_current_term(deps.settings)
    syllabus_cards = _syllabus_cards(deps, ctx.modality) if syllabus_mode else []

    if syllabus_mode:
        yield "status", {"stage": "retrieving", "label": "Checking your syllabus…"}
    else:
        yield "status", {"stage": "retrieving", "label": "Searching course materials…"}
    raw_query = ctx.message
    rewritten = build_retrieval_query(ctx.history, ctx.message)

    if syllabus_mode and ctx.modality:
        # Ground in the correct (term, modality): bias the query, retrieve
        # broadly, then keep ONLY passages whose filename matches this term +
        # section. If none match, tier falls to no_evidence and we link the
        # authoritative PDF — never quote the wrong term.
        rewritten = f"STAT 350 {term} {ctx.modality} section syllabus — {rewritten}"
        syl_cfg = cfg.model_copy(update={
            "k_webbook": max(cfg.k_webbook, 14), "max_passages": 14,
            "min_transcript_slots": 0})
        rr: RetrievalResult = await run_sync(
            retrieve, deps.gateway, deps.resolver, rewritten, syl_cfg,
            shrink=False, single_call=False)
        _restrict_to_syllabus(rr, term, ctx.modality, cfg.higher_is_better)
    else:
        rr = await run_sync(
            retrieve, deps.gateway, deps.resolver, rewritten, cfg,
            shrink=ctx.shrink, single_call=getattr(cfg, "single_call", False))
    rid = _persist_retrieval(ctx, rr, raw_query, rewritten)

    if rr.error and not rr.passages:
        deps.recorder.emit(m.ErrorEvent(
            scope="gateway_retrieval", error_type=rr.error[:64],
            request_id=ctx.request_id, user_id=ctx.user_row_id))

    # ---- weak retrieval → honest refusal, LLM call skipped -------------------
    if rr.tier == "no_evidence":
        cards = syllabus_cards + resources_payload(
            rr.passages, deps.resolver, extra_sections=r.sections[:3])
        if cards:
            yield "resources", {"resources": cards}
        # for syllabus questions, point them at the authoritative PDF rather
        # than a bare refusal
        msg = (SYLLABUS_FALLBACK if syllabus_mode and syllabus_cards
               else REFUSAL_MESSAGE)
        yield "refusal", {"reason": "weak_retrieval", "message": msg}
        yield "done", {"messageId": ctx.assistant_msg_id,
                       "finishReason": "refusal", "finalText": msg,
                       "flags": {"refusal": True}}
        _persist_assistant(ctx, seq, content=msg,
                           answer_kind="refusal", intent=r.intent,
                           finish_reason="refusal",
                           latency_ms=int((time.monotonic() - t_start) * 1000))
        return

    # ---- citations & resources BEFORE tokens ----------------------------------
    yield "citations", {"citations": citations_payload(rr.passages)}
    cards = syllabus_cards + resources_payload(
        rr.passages, deps.resolver, extra_sections=r.sections[:2])
    if cards:
        yield "resources", {"resources": cards}
    yield "status", {"stage": "thinking", "label": "Writing a grounded answer…"}

    messages = build_messages(
        deps.tutor_core, rr.passages, ctx.history, ctx.message,
        modality=ctx.modality, caveat=rr.tier == "caveat", syllabus=syllabus_mode,
        term=term if syllabus_mode else None,
        history_window=deps.settings.generation.history_window)

    gen_cfg = deps.settings.generation
    max_tokens = gen_cfg.max_tokens // 2 if ctx.shrink else gen_cfg.max_tokens

    chunks: list[str] = []
    ttft_ms: int | None = None
    finish_reason = "stop"
    t_llm = time.monotonic()
    try:
        async for delta in aiter_sync(lambda: deps.gateway.stream_chat(
                messages, max_tokens=max_tokens)):
            if ttft_ms is None:
                ttft_ms = int((time.monotonic() - t_llm) * 1000)
            chunks.append(delta)
            yield "token", {"text": delta}
    except GeneratorExit:
        finish_reason = "aborted"
        raise
    except Exception as exc:
        deps.recorder.emit(m.ErrorEvent(
            scope="gateway_chat", error_type=f"{type(exc).__name__}"[:64],
            detail=str(exc)[:500], request_id=ctx.request_id,
            user_id=ctx.user_row_id, conversation_id=ctx.conversation_id))
        yield "error", {"code": "gateway_error",
                        "message": "The model didn't respond — please try again.",
                        "retryable": True}
        _persist_assistant(ctx, seq, content="".join(chunks),
                           answer_kind="rag_answer", intent=r.intent,
                           finish_reason="error")
        return
    finally:
        if finish_reason == "aborted":
            _persist_assistant(ctx, seq, content="".join(chunks),
                               answer_kind="rag_answer", intent=r.intent,
                               finish_reason="aborted",
                               latency_ms=int((time.monotonic() - t_start) * 1000),
                               ttft_ms=ttft_ms)

    raw_text = "".join(chunks)
    final_text, removed = lint_links(raw_text, deps.resolver)
    flags: dict = {"linted": bool(removed)}
    if rr.tier == "caveat":
        flags["caveat"] = True
    catalog_card = catalog_card_for(final_text, deps.resolver)
    if catalog_card:
        flags["beyondScope"] = True
        yield "resources", {"resources": [catalog_card]}

    latency_ms = int((time.monotonic() - t_start) * 1000)
    yield "done", {"messageId": ctx.assistant_msg_id, "finishReason": "stop",
                   "finalText": final_text, "flags": flags}

    _persist_assistant(ctx, seq, content=final_text, answer_kind="rag_answer",
                       intent=r.intent, latency_ms=latency_ms, ttft_ms=ttft_ms)
    _persist_citations(ctx, rr, rid, final_text)
    if removed:
        deps.recorder.emit(m.ErrorEvent(
            scope="app", error_type="linted_url",
            detail="; ".join(removed)[:500], request_id=ctx.request_id))
    deps.recorder.emit_chat_trace({
        "request_id": ctx.request_id,
        "conversation_id": ctx.conversation_id,
        "intent": r.intent, "tier": rr.tier,
        "rewritten_query": rewritten,
        "passages": [{"n": p.n, "collection": p.collection,
                      "meta": p.meta, "text": p.text} for p in rr.passages],
        "system_prompt_chars": len(messages[0]["content"]),
        "answer": final_text, "removed_urls": removed,
        "ttft_ms": ttft_ms, "latency_ms": latency_ms,
    })
