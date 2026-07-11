"""POST /api/messages/{id}/deeper — escalate an answered question to the
agent loop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from ..concurrency import run_sync
from ..db import models as m
from ..escalation.agent_runner import run_escalation
from ..identity import Identity
from .chat import _get_or_create_user
from .deps import get_deps, require_identity
from .sse import sse_response

router = APIRouter()


@router.post("/api/messages/{message_id}/deeper")
async def dig_deeper(message_id: str, request: Request,
                     identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    state = deps.overload.state(deps.llm_queue.depth)
    if not (deps.settings.escalation.enabled and state.escalation_enabled
            and deps.gateway_ready):
        raise HTTPException(status_code=503, detail={
            "error": {"code": "escalation_disabled",
                      "message": "Dig deeper is paused right now (high demand). "
                                 "Try again in a few minutes.",
                      "retryable": True}})

    verdict = deps.user_limiter.check_escalation(identity.user_id)
    if not verdict.allowed:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(verdict.retry_after_s or 600)},
            detail={"error": {"code": "escalation_limit",
                              "message": "You've used your deeper investigations "
                                         "for this hour — the regular tutor is "
                                         "still available.",
                              "retryable": True}})

    def load():
        with deps.session_factory() as session:
            user = _get_or_create_user(session, identity)
            msg = session.get(m.Message, message_id)
            if msg is None:
                raise HTTPException(status_code=404, detail={
                    "error": {"code": "message_not_found",
                              "message": "Message not found.", "retryable": False}})
            convo = session.get(m.Conversation, msg.conversation_id)
            if convo is None or convo.user_id != user.id:
                raise HTTPException(status_code=404, detail={
                    "error": {"code": "message_not_found",
                              "message": "Message not found.", "retryable": False}})
            # the question = nearest user message at or before this one
            question_row = session.scalar(
                select(m.Message).where(
                    m.Message.conversation_id == convo.id,
                    m.Message.role == "user",
                    m.Message.seq <= msg.seq)
                .order_by(m.Message.seq.desc()).limit(1))
            next_seq = session.scalar(
                select(func.coalesce(func.max(m.Message.seq), -1) + 1)
                .where(m.Message.conversation_id == convo.id)) or 0
            hint = msg.content if msg.role == "assistant" else ""
            out = {
                "user_row_id": user.id,
                "conversation_id": convo.id,
                "question": question_row.content if question_row else msg.content,
                "hint": hint if msg.answer_kind != "refusal" else "",
                "seq": int(next_seq),
            }
            session.commit()
            return out

    info = await run_sync(load)
    trigger = "refusal_dig_deeper" if not info["hint"] else "user_dig_deeper"

    return sse_response(run_escalation(
        deps,
        question=info["question"],
        context_hint=info["hint"],
        user_row_id=info["user_row_id"],
        conversation_id=info["conversation_id"],
        source_message_id=message_id,
        seq=info["seq"],
        trigger=trigger,
    ))
