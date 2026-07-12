"""Bring-your-own-key: format guard, redaction, per-key gateways, and the
turn-level behavior (own budget, no shared queue, key never persisted)."""

from __future__ import annotations

import pytest

from app.byok import GatewayPool, key_hash, redact, valid_key_format
from app.config import load_settings

from .conftest import BACKEND, FakeGateway, webbook_payload

SECRET = "sk-abc123DEF456ghi789JKL012mno345"   # a plausible-format fake key


def test_key_format_and_redaction():
    assert valid_key_format(SECRET)
    assert not valid_key_format("")
    assert not valid_key_format("short")
    assert not valid_key_format("has spaces in it aaaaaaaaaaaaaaaaaaaa")
    assert not valid_key_format("bad\nnewline" + "a" * 20)
    # redaction removes the secret from anything log-bound
    assert SECRET not in redact(f"error using {SECRET} failed", SECRET)
    # the cache key is a hash, not the secret
    assert SECRET not in key_hash(SECRET) and len(key_hash(SECRET)) == 16


def test_validate_endpoint_rejects_malformed_key(client, device_id):
    """The /api/key/validate response must always carry the full contract
    ({authOk, retrievalOk, usable, message}) — the frontend types require it.
    A malformed key is rejected BEFORE the gateway is ever contacted."""
    client.get("/api/profile", headers={"X-Device-Id": device_id})  # bind cookie
    # reach the format-guard branch (gateway ready, byok on by config default)
    client.app.state.deps.gateway_ready = True
    r = client.post("/api/key/validate",
                    headers={"X-Device-Id": device_id, "X-GenAI-Key": "short"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"authOk", "retrievalOk", "usable", "message"}
    assert body["authOk"] is False and body["usable"] is False
    # the (rejected) key is never echoed back in the message
    assert "short" not in body["message"]


def test_validate_endpoint_503_when_gateway_down(client, device_id):
    client.get("/api/profile", headers={"X-Device-Id": device_id})
    client.app.state.deps.gateway_ready = False
    r = client.post("/api/key/validate",
                    headers={"X-Device-Id": device_id, "X-GenAI-Key": SECRET})
    assert r.status_code == 503


def test_pool_caches_per_key(settings):
    shared = FakeGateway()
    pool = GatewayPool(settings, shared, max_size=2)
    from unittest.mock import patch
    # for_key builds a real Gateway (lazy studio, never contacted here)
    with patch("app.byok.Gateway.for_key", side_effect=lambda s, k, ids: ("gw", k)):
        a1 = pool.for_key("keyAAAAAAAAAAAAAAAAAAAAAA")
        a2 = pool.for_key("keyAAAAAAAAAAAAAAAAAAAAAA")
        assert a1 is a2                       # same key -> cached instance
        b = pool.for_key("keyBBBBBBBBBBBBBBBBBBBBBB")
        assert b is not a1


# ---- turn-level behavior (async, mirrors the pipeline test harness) ----

from app.api.deps import AppDeps  # noqa: E402
from app.byok import GatewayPool as _Pool  # noqa: E402
from app.db import models as m  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.engine import make_engine, make_session_factory  # noqa: E402
from app.grounding.pipeline import TurnContext, run_turn  # noqa: E402
from app.identity import DeviceCookieIdentity  # noqa: E402
from app.overload import Overload  # noqa: E402
from app.queueing import LlmQueue  # noqa: E402
from app.ratelimit import UserLimiter  # noqa: E402
from app.telemetry.recorder import Recorder  # noqa: E402
from sqlalchemy import select  # noqa: E402


@pytest.fixture()
async def deps(settings, resolver, tmp_path):
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    recorder = Recorder(sf, traces_dir=tmp_path / "traces")
    await recorder.start()
    shared = FakeGateway()
    d = AppDeps(
        settings=settings, resolver=resolver, gateway=shared,
        gateway_pool=_Pool(settings, shared), recorder=recorder,
        session_factory=sf, llm_queue=LlmQueue(1),
        user_limiter=UserLimiter(settings.limits, settings.escalation),
        overload=Overload(settings.degradation),
        identity_provider=DeviceCookieIdentity("test"),
        tutor_core=(BACKEND / "prompts" / "tutor_core.md").read_text(encoding="utf-8"),
        escalation_prompt="test", traces_dir=tmp_path / "traces",
        gateway_ready=True)
    with sf() as session:
        session.add(m.User(id="u1", device_id="device:t"))
        session.flush()
        session.add(m.Conversation(id="c1", user_id="u1", title="t"))
        session.commit()
    yield d
    await recorder.stop()


async def test_byok_turn_uses_own_gateway_and_skips_queue(deps):
    # a full LlmQueue would block a shared-key turn; a BYO turn must ignore it
    own_gw = FakeGateway(
        retrieval_payloads={"kb-web": webbook_payload(
            ("7-3-clt.rst", "The CLT text.", 0.86))},
        stream_chunks=["The CLT says the mean is approx normal [1]."])
    async with deps.llm_queue.slot():  # occupy the single shared slot
        ctx = TurnContext(deps, user_row_id="u1", conversation_id="c1",
                          history=[], message="explain the CLT", modality=None,
                          shrink=True, escalation_enabled=True,
                          gateway=own_gw, retrieval_gateway=own_gw,
                          uses_own_key=True)
        ctx.reject = True   # overload: a shared turn would be shed; BYO ignores it
        events = [ev async for ev in run_turn(ctx, seq=0)]
    names = [e for e, _ in events]
    assert names[-1] == "done" and "citations" in names   # answered, not shed
    assert own_gw.chat_calls and not deps.gateway.chat_calls  # ran on the OWN key
    await deps.recorder.stop()
    with deps.session_factory() as session:
        msg = session.scalar(select(m.Message).where(m.Message.role == "assistant"))
        assert msg.used_own_key is True
        # the key is never stored anywhere on the row
        assert "sk-" not in (msg.content or "")
    await deps.recorder.start()
