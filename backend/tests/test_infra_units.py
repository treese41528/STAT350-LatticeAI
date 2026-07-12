"""Queue, overload ladder, per-user limits, SSE framing, recorder."""

from __future__ import annotations

import asyncio

import pytest

from app.config import DegradationCfg, EscalationCfg, LimitsCfg
from app.overload import Overload
from app.queueing import LlmQueue, QueueFullError
from app.ratelimit import UserLimiter
from app.api.sse import format_sse


def test_overload_ladder_levels():
    ov = Overload(DegradationCfg(disable_escalation_at=5,
                                 shrink_retrieval_at=12, reject_at=25))
    assert ov.state(0).level == 0 and ov.state(0).escalation_enabled
    s5 = ov.state(5)
    assert s5.level == 1 and not s5.escalation_enabled and not s5.shrink
    s12 = ov.state(12)
    assert s12.level == 2 and s12.shrink and not s12.reject
    assert ov.state(30).reject


def test_user_limiter_windows():
    lim = UserLimiter(LimitsCfg(user_per_min=2, user_per_day=5, burst_per_10min=3),
                      EscalationCfg(per_user_per_hour=1))
    t = 1000.0
    assert lim.check_message("u", now=t).allowed
    assert lim.check_message("u", now=t + 1).allowed
    v = lim.check_message("u", now=t + 2)
    assert not v.allowed and v.reason == "per_min"
    # window slides
    assert lim.check_message("u", now=t + 61).allowed
    v = lim.check_message("u", now=t + 62)          # 3 in 10min → burst cap
    assert not v.allowed and v.reason == "burst"
    # escalation counter is separate
    assert lim.check_escalation("u", now=t).allowed
    assert not lim.check_escalation("u", now=t + 10).allowed
    assert lim.check_escalation("u", now=t + 3601).allowed


async def test_llm_queue_positions_and_fifo():
    q = LlmQueue(max_concurrent=1, max_waiting=2)
    order: list[str] = []
    positions: dict[str, list[int]] = {"b": [], "c": []}
    started = asyncio.Event()
    release = asyncio.Event()

    async def holder():
        async with q.slot():
            started.set()
            await release.wait()
            order.append("a")

    async def waiter(name: str):
        async def on_pos(p: int):
            positions[name].append(p)
        async with q.slot(on_pos):
            order.append(name)

    t1 = asyncio.create_task(holder())
    await started.wait()
    t2 = asyncio.create_task(waiter("b"))
    await asyncio.sleep(0.05)
    t3 = asyncio.create_task(waiter("c"))
    await asyncio.sleep(0.05)
    assert q.depth == 2
    # third waiter overflows
    with pytest.raises(QueueFullError):
        async with q.slot():
            pass
    release.set()
    await asyncio.gather(t1, t2, t3)
    assert order == ["a", "b", "c"]                 # FIFO
    assert positions["b"] and positions["b"][0] == 1
    assert positions["c"] and positions["c"][0] == 2
    assert q.depth == 0


async def test_llm_queue_cancelled_waiter_leaves_line():
    q = LlmQueue(max_concurrent=1)
    release = asyncio.Event()
    started = asyncio.Event()

    async def holder():
        async with q.slot():
            started.set()
            await release.wait()

    t1 = asyncio.create_task(holder())
    await started.wait()

    async def waiter():
        async with q.slot():
            pass

    t2 = asyncio.create_task(waiter())
    await asyncio.sleep(0.05)
    t2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t2
    assert q.waiting == 0
    release.set()
    await t1


def test_sse_framing():
    out = format_sse("token", {"text": "hi"})
    assert out == 'event: token\ndata: {"text": "hi"}\n\n'


async def test_recorder_batches_and_drains(settings, tmp_path):
    from sqlalchemy import select

    from app.db import models as m
    from app.db.base import Base
    from app.db.engine import make_engine, make_session_factory
    from app.telemetry.recorder import Recorder

    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    rec = Recorder(sf, traces_dir=tmp_path / "traces")
    await rec.start()
    rec.emit(m.User(id="u1", device_id="device:x"))
    rec.emit(m.ErrorEvent(scope="app", error_type="test"))
    rec.emit_chat_trace({"request_id": "r1", "answer": "hello"})
    await rec.stop()

    with sf() as session:
        assert session.get(m.User, "u1") is not None
        assert session.scalar(select(m.ErrorEvent)).error_type == "test"
    trace_files = list((tmp_path / "traces").glob("chat-*.jsonl"))
    assert trace_files and "r1" in trace_files[0].read_text()
