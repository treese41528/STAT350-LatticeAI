"""Application-wide dependency container, built once in the lifespan and
stashed on app.state. Routers pull it via `get_deps(request)`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..course_map.resolver import CourseMapResolver
from ..gateway import Gateway
from ..identity import Identity, IdentityProvider
from ..overload import Overload
from ..queueing import LlmQueue
from ..ratelimit import UserLimiter
from ..telemetry.recorder import Recorder


@dataclass
class AppDeps:
    settings: Settings
    resolver: CourseMapResolver
    gateway: Gateway
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
