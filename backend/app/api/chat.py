"""POST /api/chat — the streamed default path."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..concurrency import run_sync
from ..db import models as m
from ..grounding.pipeline import TurnContext, run_turn
from ..identity import Identity
from .deps import AppDeps, get_deps, require_identity
from .sse import sse_response

router = APIRouter()

MODALITIES = {"flipped", "traditional", "indy", "online", "winter"}


class ClientState(BaseModel):
    modality: str | None = None


class ChatRequest(BaseModel):
    conversationId: str | None = None
    message: str = Field(min_length=1)
    clientState: ClientState | None = None


class TurnSetup(BaseModel):
    user_row_id: str
    conversation_id: str
    history: list[dict]
    next_seq: int
    modality: str | None


def _get_or_create_user(session, identity: Identity) -> m.User:
    user = session.scalar(select(m.User).where(m.User.device_id == identity.user_id))
    if user is None:
        user = m.User(id=str(uuid.uuid4()), device_id=identity.user_id)
        session.add(user)
        session.flush()
    else:
        # cheap write-avoidance: bump last_seen at most every 10 minutes
        now = datetime.now(timezone.utc)
        last = user.last_seen_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or (now - last).total_seconds() > 600:
            user.last_seen_at = now
    return user


def setup_turn(deps: AppDeps, identity: Identity, req: ChatRequest) -> TurnSetup:
    """All hot-path DB reads for one turn, in one short session."""
    with deps.session_factory() as session:
        user = _get_or_create_user(session, identity)

        if req.clientState and req.clientState.modality in MODALITIES \
                and user.modality != req.clientState.modality:
            user.modality = req.clientState.modality

        if req.conversationId:
            convo = session.get(m.Conversation, req.conversationId)
            if convo is None or convo.user_id != user.id:
                raise HTTPException(status_code=404, detail={
                    "error": {"code": "conversation_not_found",
                              "message": "Conversation not found.",
                              "retryable": False}})
            convo.updated_at = datetime.now(timezone.utc)
        else:
            convo = m.Conversation(
                id=str(uuid.uuid4()), user_id=user.id,
                title=req.message.strip()[:80] or "New conversation")
            session.add(convo)

        history_rows = session.execute(
            select(m.Message.role, m.Message.content)
            .where(m.Message.conversation_id == convo.id)
            .order_by(m.Message.seq)
        ).all()
        next_seq = session.scalar(
            select(func.coalesce(func.max(m.Message.seq), -1) + 1)
            .where(m.Message.conversation_id == convo.id)) or 0

        setup = TurnSetup(
            user_row_id=user.id, conversation_id=convo.id,
            history=[{"role": r, "content": c} for r, c in history_rows],
            next_seq=int(next_seq), modality=user.modality)
        session.commit()
        return setup


@router.post("/api/chat")
async def chat(request: Request, response: Response, body: ChatRequest,
               identity: Identity = Depends(require_identity)):
    deps: AppDeps = get_deps(request)

    if len(body.message) > deps.settings.course.max_message_chars:
        raise HTTPException(status_code=413, detail={
            "error": {"code": "message_too_long",
                      "message": f"Messages are capped at "
                                 f"{deps.settings.course.max_message_chars} characters.",
                      "retryable": False}})

    verdict = deps.user_limiter.check_message(identity.user_id)
    if not verdict.allowed:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(verdict.retry_after_s or 60)},
            detail={"error": {"code": f"rate_limited_{verdict.reason}",
                              "message": "You're sending messages quickly — "
                                         "give it a moment and try again.",
                              "retryable": True}})

    setup = await run_sync(setup_turn, deps, identity, body)

    state = deps.overload.state(deps.llm_queue.depth)
    ctx = TurnContext(
        deps,
        user_row_id=setup.user_row_id,
        conversation_id=setup.conversation_id,
        history=setup.history,
        message=body.message,
        modality=setup.modality,
        shrink=state.shrink,
        escalation_enabled=state.escalation_enabled and deps.settings.escalation.enabled,
    )
    ctx.reject = state.reject

    # copy the identity cookie (set by require_identity) onto the SSE response
    stream = sse_response(run_turn(ctx, setup.next_seq))
    for header, value in response.headers.items():
        if header.lower() == "set-cookie":
            stream.headers.append("set-cookie", value)
    return stream
