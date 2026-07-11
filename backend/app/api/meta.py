"""Config, health, and profile endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..concurrency import run_sync
from ..identity import Identity
from .chat import _get_or_create_user
from .deps import get_deps, require_identity

router = APIRouter()


class ProfilePatch(BaseModel):
    modality: Literal["flipped", "traditional", "indy", "online", "winter"] | None


@router.get("/api/config")
async def config(request: Request):
    deps = get_deps(request)
    state = deps.overload.state(deps.llm_queue.depth)
    course = deps.settings.course
    return {
        "courseName": course.name,
        "term": course.term,
        "welcome": course.welcome.strip(),
        "starterQuestions": course.starter_questions,
        "modalities": ["flipped", "traditional", "indy", "online", "winter"],
        "features": {
            "digDeeper": (deps.settings.escalation.enabled
                          and state.escalation_enabled and deps.gateway_ready),
        },
        "maxMessageChars": course.max_message_chars,
    }


@router.get("/api/health")
async def health(request: Request):
    deps = get_deps(request)
    status = "ok"
    if not deps.gateway_ready:
        status = "degraded"
    elif deps.overload.state(deps.llm_queue.depth).level > 0:
        status = "degraded"
    return {
        "status": status,
        "queueDepth": deps.llm_queue.depth,
        "telemetryQueue": deps.recorder.depth,
        "telemetryDropped": deps.recorder.dropped,
        "gatewayReady": deps.gateway_ready,
    }


@router.get("/api/profile")
async def get_profile(request: Request,
                      identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    def work():
        with deps.session_factory() as session:
            user = _get_or_create_user(session, identity)
            out = {"modality": user.modality}
            session.commit()
            return out

    return await run_sync(work)


@router.patch("/api/profile")
async def patch_profile(body: ProfilePatch, request: Request,
                        identity: Identity = Depends(require_identity)):
    deps = get_deps(request)

    def work():
        with deps.session_factory() as session:
            user = _get_or_create_user(session, identity)
            user.modality = body.modality
            out = {"modality": user.modality}
            session.commit()
            return out

    return await run_sync(work)
