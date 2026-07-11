"""Instructor endpoints. Bearer ADMIN_TOKEN now; CAS role later (only
`require_admin` changes). Every GET takes ?format=csv — the professor lives
in R, and `read_csv()` against these URLs is a feature.
"""

from __future__ import annotations

import csv
import io
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select

from ..concurrency import run_sync
from ..db import models as m
from .deps import AppDeps, get_deps

router = APIRouter(prefix="/admin/api")


def require_admin(request: Request) -> AppDeps:
    deps = get_deps(request)
    token = deps.settings.admin_token
    if not deps.settings.admin.enabled or not token:
        raise HTTPException(status_code=404)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or \
            not secrets.compare_digest(auth[7:], token):
        raise HTTPException(status_code=401, detail={
            "error": {"code": "admin_auth", "message": "Bad admin token.",
                      "retryable": False}})
    return deps


def _maybe_csv(rows: list[dict], fmt: str | None):
    if fmt != "csv":
        return rows
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v) if isinstance(v, (dict, list))
                                 else v) for k, v in row.items()})
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/overview")
async def overview(request: Request, days: int = Query(30, le=400),
                   format: str | None = None,
                   deps: AppDeps = Depends(require_admin)):
    def work():
        with deps.session_factory() as session:
            rows = session.scalars(
                select(m.DailyStat).where(m.DailyStat.date >=
                                          _since(days).strftime("%Y-%m-%d"))
                .order_by(m.DailyStat.date)).all()
            out = [{c.name: getattr(r, c.name) for c in m.DailyStat.__table__.columns}
                   for r in rows]
            # live today row (daily_stats is nightly)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            live_q = session.scalar(
                select(func.count(m.Message.id)).where(
                    m.Message.role == "user",
                    m.Message.created_at >= _since(1)))
            out.append({"date": today, "questions_live_24h": int(live_q or 0)})
            return out
    return _maybe_csv(await run_sync(work), format)


@router.get("/topics")
async def topics(request: Request, days: int = Query(30, le=400),
                 format: str | None = None,
                 deps: AppDeps = Depends(require_admin)):
    """Retrieval hits mapped to chapters via the course map — what students
    actually ask about, and where retrieval struggles."""
    def work():
        counts: dict[str, dict] = {}
        unmapped: dict[str, int] = {}
        with deps.session_factory() as session:
            events = session.scalars(
                select(m.RetrievalEvent)
                .where(m.RetrievalEvent.created_at >= _since(days))).all()
            for ev in events:
                seen_chapters: set[str] = set()
                for res in ev.results or []:
                    src = deps.resolver.resolve_webbook(
                        {"name": res.get("source_file")}) \
                        if res.get("collection") == "webbook" else \
                        deps.resolver.resolve_transcript(
                            {"name": res.get("source_file")})
                    if src.section is not None:
                        ch = src.section.number.split(".")[0]
                        seen_chapters.add(ch)
                    elif res.get("source_file"):
                        unmapped[res["source_file"]] = \
                            unmapped.get(res["source_file"], 0) + 1
                for ch in seen_chapters:
                    entry = counts.setdefault(ch, {"chapter": int(ch),
                                                   "questions": 0, "weak": 0})
                    entry["questions"] += 1
                    if ev.weak:
                        entry["weak"] += 1
        rows = sorted(counts.values(), key=lambda r: -r["questions"])
        for r in rows:
            ch = deps.resolver.lookup_chapter(r["chapter"])
            r["title"] = ch.title if ch else "?"
        if unmapped:
            rows.append({"chapter": -1, "title": "UNMAPPED FILES (fix course map)",
                         "questions": sum(unmapped.values()), "weak": 0,
                         "files": dict(sorted(unmapped.items(),
                                              key=lambda kv: -kv[1])[:20])})
        return rows
    return _maybe_csv(await run_sync(work), format)


@router.get("/weak-retrievals")
async def weak_retrievals(request: Request, days: int = Query(30, le=400),
                          limit: int = Query(100, le=1000),
                          format: str | None = None,
                          deps: AppDeps = Depends(require_admin)):
    """THE content-gap report: questions the knowledge base couldn't answer."""
    def work():
        with deps.session_factory() as session:
            rows = session.scalars(
                select(m.RetrievalEvent)
                .where(m.RetrievalEvent.weak,
                       m.RetrievalEvent.created_at >= _since(days))
                .order_by(m.RetrievalEvent.created_at.desc()).limit(limit)).all()
            return [{
                "created_at": r.created_at.isoformat(),
                "question": r.raw_query,
                "rewritten": r.rewritten_query,
                "tier": r.tier, "top_score": r.top_score,
                "weak_reason": r.weak_reason,
                "top_files": [x.get("source_file") for x in (r.results or [])[:3]],
                "request_id": r.request_id,
            } for r in rows]
    return _maybe_csv(await run_sync(work), format)


@router.get("/refusals")
async def refusals(request: Request, days: int = Query(30, le=400),
                   limit: int = Query(100, le=1000), format: str | None = None,
                   deps: AppDeps = Depends(require_admin)):
    def work():
        with deps.session_factory() as session:
            rows = session.execute(
                select(m.Message, m.RetrievalEvent)
                .join(m.RetrievalEvent,
                      m.RetrievalEvent.request_id == m.Message.request_id,
                      isouter=True)
                .where(m.Message.answer_kind == "refusal",
                       m.Message.created_at >= _since(days))
                .order_by(m.Message.created_at.desc()).limit(limit)).all()
            return [{
                "created_at": msg.created_at.isoformat(),
                "conversation_id": msg.conversation_id,
                "question": rev.raw_query if rev else None,
                "top_score": rev.top_score if rev else None,
                "request_id": msg.request_id,
            } for msg, rev in rows]
    return _maybe_csv(await run_sync(work), format)


@router.get("/feedback")
async def feedback_list(request: Request, status: str = "open",
                        rating: int | None = None, days: int = Query(90, le=400),
                        format: str | None = None,
                        deps: AppDeps = Depends(require_admin)):
    def work():
        with deps.session_factory() as session:
            q = (select(m.Feedback, m.Message)
                 .join(m.Message, m.Feedback.message_id == m.Message.id)
                 .where(m.Feedback.created_at >= _since(days)))
            if status == "open":
                q = q.where(m.Feedback.resolved_at.is_(None))
            if rating is not None:
                q = q.where(m.Feedback.rating == rating)
            rows = session.execute(
                q.order_by(m.Feedback.created_at.desc()).limit(500)).all()
            return [{
                "id": fb.id, "created_at": fb.created_at.isoformat(),
                "rating": fb.rating, "tags": fb.reason_tags,
                "comment": fb.free_text,
                "message_id": fb.message_id,
                "answer_kind": msg.answer_kind, "intent": msg.intent,
                "answer_preview": (msg.content or "")[:200],
                "request_id": msg.request_id,
                "resolved_at": fb.resolved_at.isoformat() if fb.resolved_at else None,
                "resolution_category": fb.resolution_category,
            } for fb, msg in rows]
    return _maybe_csv(await run_sync(work), format)


RESOLUTION_CATEGORIES = {"kb_gap", "chunking", "prompt", "course_map",
                         "policy", "ops", "not_actionable"}


@router.post("/feedback/{feedback_id}/resolve")
async def resolve_feedback(feedback_id: int, body: dict, request: Request,
                           deps: AppDeps = Depends(require_admin)):
    category = (body or {}).get("category")
    if category not in RESOLUTION_CATEGORIES:
        raise HTTPException(status_code=422, detail={
            "error": {"code": "bad_category",
                      "message": f"category must be one of "
                                 f"{sorted(RESOLUTION_CATEGORIES)}",
                      "retryable": False}})

    def work():
        with deps.session_factory() as session:
            fb = session.get(m.Feedback, feedback_id)
            if fb is None:
                raise HTTPException(status_code=404)
            fb.resolved_at = datetime.now(timezone.utc)
            fb.resolution_category = category
            fb.resolution_note = (body or {}).get("note")
            session.commit()
            return {"ok": True}
    return await run_sync(work)


@router.get("/messages/{message_id}/replay")
async def replay(message_id: str, request: Request,
                 deps: AppDeps = Depends(require_admin)):
    """Full-context replay: conversation up to the message + retrieval +
    citations + feedback + a pointer into the JSONL chat trace."""
    def work():
        with deps.session_factory() as session:
            msg = session.get(m.Message, message_id)
            if msg is None:
                raise HTTPException(status_code=404)
            convo_msgs = session.scalars(
                select(m.Message)
                .where(m.Message.conversation_id == msg.conversation_id,
                       m.Message.seq <= msg.seq)
                .order_by(m.Message.seq)).all()
            rev = session.scalar(
                select(m.RetrievalEvent)
                .where(m.RetrievalEvent.request_id == msg.request_id))
            cits = session.scalars(
                select(m.Citation)
                .where(m.Citation.message_id == message_id)).all()
            fb = session.scalar(
                select(m.Feedback).where(m.Feedback.message_id == message_id))
            return {
                "conversation": [{"role": x.role, "content": x.content,
                                  "seq": x.seq, "kind": x.answer_kind}
                                 for x in convo_msgs],
                "retrieval": None if rev is None else {
                    "raw_query": rev.raw_query,
                    "rewritten_query": rev.rewritten_query,
                    "tier": rev.tier, "top_score": rev.top_score,
                    "results": rev.results,
                },
                "citations": [{"marker": c.marker, "resolved": c.resolved,
                               "source_file": c.source_file} for c in cits],
                "feedback": None if fb is None else {
                    "rating": fb.rating, "tags": fb.reason_tags,
                    "comment": fb.free_text},
                "trace_hint": f"grep {msg.request_id} traces/chat-*.jsonl",
                "latency_ms": msg.latency_ms, "ttft_ms": msg.ttft_ms,
                "model": msg.model,
            }
    return await run_sync(work)
