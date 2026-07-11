"""Message feedback + batched UI events."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..concurrency import run_sync
from ..db import models as m
from ..identity import Identity
from .chat import _get_or_create_user
from .deps import get_deps, require_identity

router = APIRouter()

ALLOWED_TAGS = {
    "wrong-math", "notation", "bad-sources", "broken-link", "too-much-help",
    "too-little-help", "off-scope", "missed-question",
    "clear", "good-sources", "right-level",
}

ALLOWED_UI_EVENTS = {
    "resource_card_click", "citation_click", "dig_deeper_click", "copy_answer",
    "suggested_question_click", "conversation_new", "conversation_delete",
    "overload_shown", "queue_wait_shown", "client_error",
}


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    tags: list[str] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(default=None, max_length=2000)


class UiEventIn(BaseModel):
    type: str
    payload: dict = Field(default_factory=dict)
    conversationId: str | None = None
    messageId: str | None = None


class UiEventBatch(BaseModel):
    events: list[UiEventIn] = Field(max_length=50)


@router.post("/api/messages/{message_id}/feedback", status_code=204)
async def submit_feedback(message_id: str, body: FeedbackRequest,
                          request: Request,
                          identity: Identity = Depends(require_identity)):
    deps = get_deps(request)
    tags = [t for t in body.tags if t in ALLOWED_TAGS]
    if body.rating == "down" and not tags and not (body.comment or "").strip():
        raise HTTPException(status_code=422, detail={
            "error": {"code": "feedback_needs_reason",
                      "message": "Pick at least one reason or add a comment.",
                      "retryable": False}})

    def work():
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
            existing = session.scalar(select(m.Feedback)
                                      .where(m.Feedback.message_id == message_id))
            if existing:
                existing.rating = 1 if body.rating == "up" else -1
                existing.reason_tags = tags
                existing.free_text = (body.comment or "").strip() or None
            else:
                session.add(m.Feedback(
                    message_id=message_id, user_id=user.id,
                    rating=1 if body.rating == "up" else -1,
                    reason_tags=tags,
                    free_text=(body.comment or "").strip() or None))
            session.commit()

    await run_sync(work)


@router.post("/api/events", status_code=204)
async def ui_events(body: UiEventBatch, request: Request,
                    identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    def user_row_id():
        with deps.session_factory() as session:
            user = _get_or_create_user(session, identity)
            session.commit()
            return user.id

    uid = await run_sync(user_row_id)
    for ev in body.events:
        if ev.type not in ALLOWED_UI_EVENTS:
            continue
        # enumerated types only; payload is small structured fields
        deps.recorder.emit(m.UiEvent(
            user_id=uid, conversation_id=ev.conversationId,
            message_id=ev.messageId, event_type=ev.type,
            payload={k: v for k, v in list(ev.payload.items())[:8]
                     if isinstance(v, (str, int, float, bool))}))
