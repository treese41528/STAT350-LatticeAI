"""'Dig deeper' — the SDK agent loop, streamed as SSE status events.

Agent ReAct chatter is never forwarded to the student. Tool activity maps to
`status` events; the final vetted text is re-emitted as `token` events so the
SPA renders it through the identical code path; tool Sources feed the same
citations/resources contract; link linting still applies.
"""

from __future__ import annotations

import queue as _queue
import threading
import time
import uuid
from typing import AsyncIterator

from genai_studio.agents import Agent, Budget, Cancel, JsonlTracer
from genai_studio.agents.client import GenAIStudioClient
from genai_studio.agents.events import (Final, StepFinished, ToolCallFinished,
                                        ToolCallStarted)
from genai_studio.agents.tools import make_kb_search_tool
from genai_studio.agents.tools.general import calculator
from genai_studio.agents.tools.http import make_http_get

from ..api.deps import AppDeps
from ..db import models as m
from ..grounding.citations import lint_links
from ..syllabus import resolve_current_term
from .tools import make_course_tools

TOOL_LABELS = {
    "kb_search": "Searching course materials…",
    "get_lecture_url": "Looking up the lecture page…",
    "get_chapter_overview": "Checking the chapter outline…",
    "get_worksheet": "Finding practice worksheets…",
    "get_simulation": "Finding the right simulation…",
    "get_syllabus_and_schedule": "Pulling the syllabus…",
    "get_exam_info": "Checking exam coverage…",
    "get_r_resources": "Finding R resources…",
    "calculator": "Computing…",
    "fetch_course_page": "Reading a course page…",
}

_SENTINEL = object()


def build_agent(deps: AppDeps, trace_path: str) -> Agent:
    esc = deps.settings.escalation
    model = esc.model or deps.settings.gateway.model
    client = GenAIStudioClient(deps.gateway.studio, default_model=model,
                               rate_limiter=deps.gateway.limiter)
    kb_search = make_kb_search_tool(
        deps.gateway.studio, list(deps.gateway.kb_ids.values()),
        k=4, rate_limiter=deps.gateway.limiter)
    fetch_course_page = make_http_get(
        allow_hosts=["treese41528.github.io"], name="fetch_course_page")
    return Agent(
        client=client,
        tools=[kb_search,
               *make_course_tools(
                   deps.resolver,
                   term=resolve_current_term(deps.settings),
                   syllabi=deps.settings.course.syllabi),
               calculator,
               fetch_course_page],
        model=model,
        system=deps.escalation_prompt,
        max_steps=esc.max_steps,
        temperature=esc.temperature,   # greedy — SDK guidance for tool use
        tracer=JsonlTracer(trace_path),
    )


async def run_escalation(deps: AppDeps, *, question: str, context_hint: str,
                         user_row_id: str, conversation_id: str,
                         source_message_id: str, seq: int,
                         trigger: str) -> AsyncIterator[tuple[str, dict]]:
    run_id = str(uuid.uuid4())
    result_msg_id = str(uuid.uuid4())
    traces_dir = deps.traces_dir
    traces_dir.mkdir(parents=True, exist_ok=True)
    trace_path = str(traces_dir / f"esc-{run_id}.jsonl")

    yield "meta", {"conversationId": conversation_id,
                   "messageId": result_msg_id, "mode": "deep"}
    yield "status", {"stage": "escalated",
                     "label": "Digging deeper — this takes a bit longer…"}

    esc = deps.settings.escalation
    prompt = question if not context_hint else (
        f"{question}\n\n(Context: the quick answer attempt said: "
        f"{context_hint[:400]})")

    agent = build_agent(deps, trace_path)
    cancel = Cancel()
    budget = Budget(max_tokens=esc.max_tokens, max_tool_calls=esc.max_tool_calls)

    events: _queue.Queue = _queue.Queue(maxsize=256)
    stop_flag = threading.Event()

    def pump() -> None:
        try:
            for ev in agent.stream(prompt, budget=budget, cancel=cancel):
                # blocking put with a stop check so a disconnected consumer
                # (queue full, never drained) can't hang this thread forever
                while not stop_flag.is_set():
                    try:
                        events.put(ev, timeout=0.5)
                        break
                    except _queue.Full:
                        continue
                if stop_flag.is_set():
                    return
        except Exception as exc:
            try:
                events.put(exc, timeout=1)
            except _queue.Full:
                pass
        finally:
            try:
                events.put(_SENTINEL, timeout=1)
            except _queue.Full:
                pass

    thread = threading.Thread(target=pump, daemon=True, name="escalation")
    thread.start()

    import asyncio
    t0 = time.monotonic()
    deadline = t0 + esc.timeout_s
    result = None
    tools_used: list[str] = []
    steps = 0
    error: Exception | None = None

    try:
        while True:
            if time.monotonic() > deadline:
                cancel.cancel()
                yield "status", {"stage": "escalated",
                                 "label": "Taking too long — wrapping up…"}
                deadline = time.monotonic() + 15  # grace to unwind
            try:
                ev = events.get_nowait()
            except _queue.Empty:
                await asyncio.sleep(0.2)
                continue
            if ev is _SENTINEL:
                break
            if isinstance(ev, Exception):
                error = ev
                break
            if isinstance(ev, ToolCallStarted):
                tools_used.append(ev.name)
                yield "status", {"stage": "tool",
                                 "label": TOOL_LABELS.get(ev.name,
                                                          f"Using {ev.name}…")}
            elif isinstance(ev, ToolCallFinished):
                pass
            elif isinstance(ev, StepFinished):
                steps = ev.step + 1
                yield "status", {"stage": "thinking",
                                 "label": "Putting it together…"}
            elif isinstance(ev, Final):
                result = ev.result
    finally:
        cancel.cancel()
        stop_flag.set()   # unblock the pump thread if the client disconnected

    latency_ms = int((time.monotonic() - t0) * 1000)

    if result is None or error is not None:
        detail = f"{type(error).__name__}: {error}" if error else "no result"
        yield "error", {"code": "escalation_failed",
                        "message": "The deeper investigation didn't finish — "
                                   "try again, or rephrase the question.",
                        "retryable": True}
        deps.recorder.emit(m.Escalation(
            id=run_id, message_id=source_message_id, trigger=trigger,
            model=esc.model or deps.settings.gateway.model, steps=steps,
            tools_used=tools_used, stopped="error", latency_ms=latency_ms,
            outcome="error", trace_file=trace_path))
        deps.recorder.emit(m.ErrorEvent(
            scope="gateway_chat", error_type="escalation", detail=detail[:500],
            user_id=user_row_id, conversation_id=conversation_id))
        return

    final_text, removed = lint_links(result.text or "", deps.resolver)

    # tool Sources → citations + resources (same contract as the default path)
    citations, resources, seen_urls = [], [], set()
    n = 0
    for src in result.sources or []:
        url = getattr(src, "url", None)
        title = getattr(src, "title", None) or "Course material"
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        n += 1
        citations.append({"n": n, "source": "webbook", "title": str(title),
                          "snippet": (getattr(src, "snippet", "") or "")[:240],
                          "similarity": 0.5, "url": url})
        if url and deps.resolver.is_allowed_url(url):
            kind = "video" if "video_viewer" in url else (
                "worksheet" if "worksheet" in url else
                "simulation" if "ShinyApps" in url else
                "syllabus" if url.endswith(".pdf") else "lecture")
            resources.append({"kind": kind, "title": str(title), "url": url,
                              "meta": None})
    if citations:
        yield "citations", {"citations": citations[:12]}
    if resources:
        yield "resources", {"resources": resources[:8]}

    # stream the final text in chunks through the normal token path
    CHUNK = 400
    for i in range(0, len(final_text), CHUNK):
        yield "token", {"text": final_text[i:i + CHUNK]}
    yield "done", {"messageId": result_msg_id, "finishReason": "stop",
                   "finalText": final_text,
                   "flags": {"linted": bool(removed)}}

    usage = getattr(result, "usage", None)
    deps.recorder.emit(m.Message(
        id=result_msg_id, conversation_id=conversation_id, seq=seq,
        role="assistant", content=final_text,
        model=esc.model or deps.settings.gateway.model,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        latency_ms=latency_ms, finish_reason="stop",
        answer_kind="escalation", intent="dig_deeper"))
    deps.recorder.emit(m.Escalation(
        id=run_id, message_id=source_message_id, trigger=trigger,
        model=esc.model or deps.settings.gateway.model, steps=steps,
        tools_used=tools_used, stopped=getattr(result, "stopped", "final"),
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        latency_ms=latency_ms, outcome="answered", trace_file=trace_path))
