"""The grounded LLM path end-to-end with a fake gateway: event ordering,
citations-before-tokens, link linting into done.finalText, weak-retrieval
refusal, and telemetry persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.deps import AppDeps
from app.db import models as m
from app.db.base import Base
from app.db.engine import make_engine, make_session_factory
from app.grounding.pipeline import TurnContext, run_turn
from app.identity import DeviceCookieIdentity
from app.overload import Overload
from app.queueing import LlmQueue
from app.ratelimit import UserLimiter
from app.telemetry.recorder import Recorder

from .conftest import BACKEND, FakeGateway, webbook_payload


@pytest.fixture()
async def deps(settings, resolver, tmp_path):
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    recorder = Recorder(sf, traces_dir=tmp_path / "traces")
    await recorder.start()
    d = AppDeps(
        settings=settings, resolver=resolver,
        gateway=FakeGateway(), recorder=recorder, session_factory=sf,
        llm_queue=LlmQueue(settings.gateway.max_concurrent_llm),
        user_limiter=UserLimiter(settings.limits, settings.escalation),
        overload=Overload(settings.degradation),
        identity_provider=DeviceCookieIdentity("test"),
        tutor_core=(BACKEND / "prompts" / "tutor_core.md").read_text(encoding="utf-8"),
        escalation_prompt="test", traces_dir=tmp_path / "traces",
        gateway_ready=True,
    )
    # seed user + conversation rows the pipeline references (flush between:
    # no relationship() between the mappers, so insert order isn't sorted)
    with sf() as session:
        session.add(m.User(id="u1", device_id="device:t"))
        session.flush()
        session.add(m.Conversation(id="c1", user_id="u1", title="t"))
        session.commit()
    yield d
    await recorder.stop()


def _ctx(deps, message: str) -> TurnContext:
    return TurnContext(deps, user_row_id="u1", conversation_id="c1",
                       history=[], message=message, modality=None,
                       shrink=False, escalation_enabled=True)


async def _collect(gen) -> list[tuple[str, dict]]:
    return [ev async for ev in gen]


GOOD_URL = "https://treese41528.github.io/STAT350/Website/chapter7/lectures/7-3-clt.html"


async def test_grounded_happy_path(deps):
    deps.gateway = FakeGateway(
        retrieval_payloads={
            "kb-web": webbook_payload(
                ("7-3-clt.rst", "The CLT: for large n the sample mean is "
                                "approximately normal.", 0.86)),
            "kb-tr": {"documents": [["In lecture: n at least 30 rule of thumb."]],
                      "distances": [[0.82]],
                      "metadatas": [[{"name": "lecture_7-3_transcript.vtt"}]]},
        },
        stream_chunks=["The CLT says the sampling distribution of the mean "
                       "is approximately normal [1]",
                       ", typically once n ≥ 30 [2]. ",
                       "Bad link: https://evil.example.com/clt and a bogus "
                       "cite [9]."])
    ctx = _ctx(deps, "Can you explain the central limit theorem?")
    events = await _collect(run_turn(ctx, seq=0))
    names = [e for e, _ in events]

    # contract ordering: citations & resources BEFORE any token
    assert names[0] == "meta"
    assert names.index("citations") < names.index("token")
    assert names.index("resources") < names.index("token")
    assert names[-1] == "done"

    cit = dict(events)["citations"]["citations"]
    assert [c["n"] for c in cit] == [1, 2]
    assert cit[0]["source"] == "webbook" and cit[1]["source"] == "transcript"
    assert cit[0]["url"] == GOOD_URL

    done = dict(events)["done"]
    assert done["flags"]["linted"] is True
    assert "evil.example.com" not in done["finalText"]
    assert "[link removed — see Sources]" in done["finalText"]

    resources = dict(events)["resources"]["resources"]
    kinds = {r["kind"] for r in resources}
    assert "lecture" in kinds and "simulation" in kinds  # ch 7 → CLT sim card
    assert all(deps.resolver.is_allowed_url(r["url"]) for r in resources)

    # telemetry persisted after recorder drain
    await deps.recorder.stop()
    with deps.session_factory() as session:
        msgs = session.scalars(select(m.Message).order_by(m.Message.seq)).all()
        assert [x.role for x in msgs] == ["user", "assistant"]
        assert msgs[1].answer_kind == "rag_answer"
        assert msgs[1].content == done["finalText"]
        rev = session.scalar(select(m.RetrievalEvent))
        assert rev.tier == "strong" and len(rev.results) == 2
        cits = session.scalars(select(m.Citation).order_by(m.Citation.marker)).all()
        assert [(c.marker, c.resolved) for c in cits] == \
            [(1, True), (2, True), (9, False)]   # [9] = unresolved tripwire
        lint_err = session.scalar(select(m.ErrorEvent)
                                  .where(m.ErrorEvent.error_type == "linted_url"))
        assert lint_err is not None
    await deps.recorder.start()


async def test_weak_retrieval_refuses_without_llm_call(deps):
    deps.gateway = FakeGateway(retrieval_payloads={
        "kb-web": webbook_payload(("7-3-clt.rst", "irrelevant", 0.58))})
    ctx = _ctx(deps, "what is the best crypto exchange?")
    events = await _collect(run_turn(ctx, seq=0))
    names = [e for e, _ in events]
    assert "refusal" in names
    assert dict(events)["refusal"]["reason"] == "weak_retrieval"
    assert deps.gateway.chat_calls == []          # LLM call skipped
    await deps.recorder.stop()
    with deps.session_factory() as session:
        assistant = session.scalar(select(m.Message)
                                   .where(m.Message.role == "assistant"))
        assert assistant.answer_kind == "refusal"
        rev = session.scalar(select(m.RetrievalEvent))
        assert rev.weak and rev.tier == "no_evidence"
    await deps.recorder.start()


async def test_gateway_stream_error_yields_retryable_error(deps):
    deps.gateway = FakeGateway(
        retrieval_payloads={"kb-web": webbook_payload(
            ("7-3-clt.rst", "The CLT text.", 0.85))},
        stream_error=ConnectionError("boom"))
    events = await _collect(run_turn(_ctx(deps, "explain the CLT please"), seq=0))
    err = dict(events).get("error")
    assert err and err["retryable"]


async def test_caveat_tier_flags_done(deps):
    deps.gateway = FakeGateway(
        retrieval_payloads={"kb-web": webbook_payload(
            ("7-3-clt.rst", "loosely related", 0.70))},
        stream_chunks=["Partially covered [1]."])
    events = await _collect(run_turn(_ctx(deps, "explain something adjacent"),
                                     seq=0))
    assert dict(events)["done"]["flags"].get("caveat") is True


async def test_syllabus_content_grounds_in_correct_term_and_modality(deps):
    # retrieval returns Flipped (right), Online (wrong modality), and a FALL
    # syllabus (wrong term). Only the SPRING-2026 Flipped passage must survive.
    deps.gateway = FakeGateway(
        retrieval_payloads={
            "kb-web": {
                "documents": [["Homework is 24% of the grade. (SPRING 2026 Flipped)",
                               "Homework is 24% of the grade. (SPRING 2026 Online)",
                               "Homework is 30% of the grade. (FALL 2025 Flipped)"]],
                "distances": [[0.83, 0.85, 0.86]],
                "metadatas": [[{"name": "Syllabus_SPRING_2026_Flipped.md"},
                               {"name": "Syllabus_SPRING_2026_Online.md"},
                               {"name": "Syllabus_FALL_2025_Flipped.md"}]],
            },
        },
        stream_chunks=["Homework is **24%** of your grade [1]."])
    ctx = TurnContext(deps, user_row_id="u1", conversation_id="c1", history=[],
                      message="how much is the homework worth?", modality="flipped",
                      shrink=False, escalation_enabled=True)
    events = await _collect(run_turn(ctx, seq=0))
    names = [e for e, _ in events]
    assert "citations" in names and names[-1] == "done"
    # exactly one citation survived the term+modality filter
    cits = dict(events)["citations"]["citations"]
    assert len(cits) == 1
    # the query was biased with BOTH term and modality
    call_q = deps.gateway.retrieval_calls[0][0].lower()
    assert "spring 2026" in call_q and "flipped" in call_q
    # authoritative SPRING 2026 Flipped syllabus + schedule cards attached
    resources = dict(events)["resources"]["resources"]
    assert {"syllabus", "schedule"} <= {r["kind"] for r in resources}
    assert any("SPRING" in r["url"] and "Flipped" in r["url"]
               for r in resources if r["kind"] == "syllabus")
    await deps.recorder.stop()
    with deps.session_factory() as session:
        msg = session.scalar(select(m.Message).where(m.Message.role == "assistant"))
        assert msg.intent == "syllabus_content"
    await deps.recorder.start()


async def test_syllabus_falls_back_to_link_when_term_absent(deps):
    # only a FALL syllabus is retrievable; a SPRING student must NOT be quoted
    # a wrong-term figure — instead we link the official PDF.
    deps.gateway = FakeGateway(
        retrieval_payloads={
            "kb-web": webbook_payload(
                ("Syllabus_FALL_2025_Flipped.md", "Homework is 30% (FALL).", 0.86)),
        },
        stream_chunks=["should not be reached"])
    ctx = TurnContext(deps, user_row_id="u1", conversation_id="c1", history=[],
                      message="how much is the homework worth?", modality="flipped",
                      shrink=False, escalation_enabled=True)
    events = await _collect(run_turn(ctx, seq=0))
    names = [e for e, _ in events]
    assert "refusal" in names             # no current-term match -> fallback
    assert deps.gateway.chat_calls == []  # never quoted the wrong term
    resources = dict(events)["resources"]["resources"]
    assert any(r["kind"] == "syllabus" for r in resources)  # links the real PDF


async def test_syllabus_content_asks_modality_when_unknown(deps):
    deps.gateway = FakeGateway()
    ctx = TurnContext(deps, user_row_id="u1", conversation_id="c1", history=[],
                      message="what's the late homework policy?", modality=None,
                      shrink=False, escalation_enabled=True)
    events = await _collect(run_turn(ctx, seq=0))
    text = "".join(d.get("text", "") for e, d in events if e == "token")
    assert "Which section" in text            # asks modality first
    assert deps.gateway.retrieval_calls == []  # no retrieval until modality known


async def test_overload_reject_path(deps):
    deps.gateway = FakeGateway()
    ctx = _ctx(deps, "explain the CLT")
    ctx.reject = True
    events = await _collect(run_turn(ctx, seq=0))
    names = [e for e, _ in events]
    assert "refusal" in names and "citations" not in names
    assert deps.gateway.retrieval_calls == []     # nothing spent
