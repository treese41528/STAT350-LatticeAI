"""Config, health, and profile endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from ..concurrency import run_sync
from ..identity import DEVICE_COOKIE, Identity
from .chat import _get_or_create_user
from .deps import get_deps, require_identity

router = APIRouter()


class ProfilePatch(BaseModel):
    modality: Literal["flipped", "traditional", "indy", "online", "winter",
                      "summer"] | None


@router.get("/api/config")
async def config(request: Request):
    from ..syllabus import resolve_current_term
    deps = get_deps(request)
    state = deps.overload.state(deps.llm_queue.depth)
    course = deps.settings.course
    return {
        "courseName": course.name,
        "term": resolve_current_term(deps.settings),
        "welcome": course.welcome.strip(),
        "starterQuestions": course.starter_questions,
        "modalities": ["flipped", "traditional", "indy", "online", "winter",
                       "summer"],
        "features": {
            "digDeeper": (deps.settings.escalation.enabled
                          and state.escalation_enabled and deps.gateway_ready),
            "byok": deps.settings.byok.enabled and deps.gateway_ready,
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
    from .. import __version__
    from ..syllabus import resolve_current_term
    try:
        import genai_studio
        sdk_version = genai_studio.__version__
    except Exception:
        sdk_version = None
    return {
        "status": status,
        "version": __version__,
        "sdkVersion": sdk_version,
        "term": resolve_current_term(deps.settings),
        "autoTerm": deps.settings.course.auto_term,
        "queueDepth": deps.llm_queue.depth,
        "telemetryQueue": deps.recorder.depth,
        "telemetryDropped": deps.recorder.dropped,
        "gatewayReady": deps.gateway_ready,
    }


@router.post("/api/identity/reset", status_code=204)
async def reset_identity(response: Response):
    """Clear the signed device cookie so 'Clear my data' can mint a fresh
    identity. Without this, the HttpOnly cookie (which JS can't remove) would
    keep mismatching the new localStorage id and 401 every request."""
    response.delete_cookie(DEVICE_COOKIE, samesite="lax")


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
