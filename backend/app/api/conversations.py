"""Conversation CRUD (ownership always checked against the caller's identity)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..concurrency import run_sync
from ..db import models as m
from ..identity import Identity
from .chat import _get_or_create_user
from .deps import AppDeps, get_deps, require_identity

router = APIRouter()


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def _own_conversation(session, deps: AppDeps, identity: Identity, cid: str):
    user = _get_or_create_user(session, identity)
    convo = session.get(m.Conversation, cid)
    if convo is None or convo.user_id != user.id:
        raise HTTPException(status_code=404, detail={
            "error": {"code": "conversation_not_found",
                      "message": "Conversation not found.", "retryable": False}})
    return user, convo


def _summary(session, convo: m.Conversation) -> dict:
    count = session.scalar(select(func.count(m.Message.id))
                           .where(m.Message.conversation_id == convo.id)) or 0
    return {"id": convo.id, "title": convo.title or "New conversation",
            "updatedAt": convo.updated_at.isoformat() + "Z",
            "messageCount": int(count)}


def _message_dict(session, msg: m.Message) -> dict:
    citations = []
    if msg.role == "assistant":
        rows = session.execute(
            select(m.Citation, m.RetrievalEvent)
            .join(m.RetrievalEvent,
                  m.Citation.retrieval_event_id == m.RetrievalEvent.id,
                  isouter=True)
            .where(m.Citation.message_id == msg.id, m.Citation.resolved)
        ).all()
        for cit, rev in rows:
            entry = {"n": cit.marker, "source": cit.collection or "webbook",
                     "title": cit.source_file or "Course material",
                     "snippet": "", "similarity": 0.5, "url": None}
            if rev is not None:
                for res in rev.results:
                    if res.get("rank") == cit.marker:
                        entry["similarity"] = max(
                            0.0, min(1.0, 1.0 - (res.get("score") or 0.5)))
                        break
            citations.append(entry)
    return {
        "id": msg.id, "role": msg.role, "content": msg.content,
        "citations": citations, "resources": [],
        "status": "refused" if msg.answer_kind == "refusal" else "complete",
        "createdAt": msg.created_at.isoformat() + "Z",
    }


@router.get("/api/conversations")
async def list_conversations(request: Request,
                             identity: Identity = Depends(require_identity),
                             limit: int = 50, offset: int = 0):
    deps = get_deps(request)

    def work():
        with deps.session_factory() as session:
            user = _get_or_create_user(session, identity)
            convos = session.scalars(
                select(m.Conversation)
                .where(m.Conversation.user_id == user.id)
                .order_by(m.Conversation.updated_at.desc())
                .limit(min(limit, 100)).offset(offset)).all()
            out = [_summary(session, c) for c in convos]
            session.commit()
            return out

    return await run_sync(work)


@router.get("/api/conversations/{cid}")
async def get_conversation(cid: str, request: Request,
                           identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    def work():
        with deps.session_factory() as session:
            _, convo = _own_conversation(session, deps, identity, cid)
            data = _summary(session, convo)
            data["messages"] = [_message_dict(session, msg)
                                for msg in convo.messages]
            session.commit()
            return data

    return await run_sync(work)


@router.patch("/api/conversations/{cid}")
async def rename_conversation(cid: str, body: RenameRequest, request: Request,
                              identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    def work():
        with deps.session_factory() as session:
            _, convo = _own_conversation(session, deps, identity, cid)
            convo.title = body.title.strip()
            data = _summary(session, convo)
            session.commit()
            return data

    return await run_sync(work)


@router.delete("/api/conversations/{cid}", status_code=204)
async def delete_conversation(cid: str, request: Request,
                              identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    def work():
        with deps.session_factory() as session:
            _, convo = _own_conversation(session, deps, identity, cid)
            session.delete(convo)
            session.commit()

    await run_sync(work)
    deps.recorder.emit(m.UiEvent(event_type="conversation_delete",
                                 conversation_id=cid))
