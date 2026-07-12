"""Application-wide dependency container, built once in the lifespan and
stashed on app.state. Routers pull it via `get_deps(request)`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from ..byok import GatewayPool
from ..config import Settings
from ..course_map.resolver import CourseMapResolver
from ..gateway import Gateway
from ..identity import Identity, IdentityProvider
from ..overload import Overload
from ..queueing import LlmQueue
from ..ratelimit import UserLimiter
from ..syllabi_store import SyllabusStore
from ..telemetry.recorder import Recorder

BYOK_HEADER = "X-GenAI-Key"


@dataclass
class AppDeps:
    settings: Settings
    resolver: CourseMapResolver
    gateway: Gateway
    gateway_pool: GatewayPool
    recorder: Recorder
    session_factory: sessionmaker[Session]
    llm_queue: LlmQueue
    user_limiter: UserLimiter
    overload: Overload
    identity_provider: IdentityProvider
    tutor_core: str
    escalation_prompt: str
    traces_dir: Path
    gateway_ready: bool = False   # collections resolved (needs API key)
    syllabus_store: SyllabusStore | None = None


def get_byok_key(request: Request) -> str | None:
    """The caller's own API key from the header, if BYO is enabled and the value
    is well-formed. Never logged."""
    deps: AppDeps = request.app.state.deps
    if not deps.settings.byok.enabled:
        return None
    from ..byok import valid_key_format
    raw = (request.headers.get(BYOK_HEADER) or "").strip()
    return raw if valid_key_format(raw) else None


def get_deps(request: Request) -> AppDeps:
    return request.app.state.deps


def require_identity(request: Request, response: Response) -> Identity:
    deps: AppDeps = request.app.state.deps
    ident = deps.identity_provider.resolve(request, response)
    if ident is None:
        raise HTTPException(status_code=401, detail={
            "error": {"code": "no_identity",
                      "message": "Missing or invalid device identity.",
                      "retryable": False}})
    return ident
