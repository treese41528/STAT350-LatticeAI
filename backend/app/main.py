"""App factory. Run with exactly ONE worker:

    uvicorn app.main:app --host 127.0.0.1 --port 8100 --workers 1

One process ⇒ one GenAIStudio client ⇒ one RateLimiter — required because the
gateway silently drops bursts and the SDK limiter is in-process state.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin as admin_api
from .api import chat, conversations, deeper, feedback, meta
from .api.deps import AppDeps
from .config import Settings, load_settings
from .course_map.resolver import CourseMapResolver
from .db.base import Base
from .db.engine import make_engine, make_session_factory
from .gateway import Gateway
from .identity import DeviceCookieIdentity
from .overload import Overload
from .queueing import LlmQueue
from .ratelimit import UserLimiter
from .telemetry.recorder import Recorder

logger = logging.getLogger("stat350")


def build_deps(settings: Settings) -> AppDeps:
    backend = settings.backend_dir
    resolver = CourseMapResolver.from_file(backend / "data" / "course_map.json")
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    traces_dir = settings.resolve_path(settings.logging.dir) / ".." / "traces"
    traces_dir = traces_dir.resolve()
    return AppDeps(
        settings=settings,
        resolver=resolver,
        gateway=Gateway(settings),
        recorder=Recorder(session_factory,
                          traces_dir if settings.logging.chat_traces else None),
        session_factory=session_factory,
        llm_queue=LlmQueue(settings.gateway.max_concurrent_llm),
        user_limiter=UserLimiter(settings.limits, settings.escalation),
        overload=Overload(settings.degradation),
        identity_provider=DeviceCookieIdentity(settings.secret_key),
        tutor_core=(backend / "prompts" / "tutor_core.md").read_text(encoding="utf-8"),
        escalation_prompt=(backend / "prompts" / "escalation_agent.md")
        .read_text(encoding="utf-8"),
        traces_dir=traces_dir,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        deps = build_deps(settings)
        app.state.deps = deps
        await deps.recorder.start()
        # warn if the configured term looks stale for today's date (a syllabus
        # is quoted for course.term; a forgotten rollover would ground answers
        # in the wrong semester)
        from datetime import datetime, timezone

        from .syllabus import term_for_date
        derived = term_for_date(datetime.now(timezone.utc).date())
        if settings.course.term and settings.course.term.lower() != derived.lower():
            logger.warning(
                "config course.term=%r but today's date suggests %r — confirm "
                "the term is correct so syllabus answers ground in the right "
                "semester.", settings.course.term, derived)
        if settings.api_key:
            try:
                import anyio
                await anyio.to_thread.run_sync(deps.gateway.resolve_collections)
                deps.gateway_ready = True
            except Exception:
                logger.exception(
                    "Could not resolve knowledge collections — running degraded "
                    "(deterministic answers only) until the gateway is reachable.")
        else:
            logger.warning(
                "GENAI_STUDIO_API_KEY is not set — running degraded "
                "(deterministic answers only).")
        yield
        await deps.recorder.stop()

    from . import __version__
    app = FastAPI(title="STAT 350 Tutor", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_req: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "error": {"code": "http_error", "message": str(exc.detail),
                      "retryable": exc.status_code >= 500}}
        return JSONResponse(status_code=exc.status_code, content=detail,
                            headers=getattr(exc, "headers", None))

    app.include_router(chat.router)
    app.include_router(deeper.router)
    app.include_router(conversations.router)
    app.include_router(feedback.router)
    app.include_router(meta.router)
    app.include_router(admin_api.router)

    # ---- SPA static serving (frontend build output) --------------------------
    static_dir = Path(__file__).resolve().parent.parent / "app_static"
    if static_dir.exists() and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"),
                  name="assets")

        static_root = static_dir.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith(("api/", "admin/api")):
                raise HTTPException(status_code=404)
            # Confine to static_root: reject percent-encoded/absolute traversal
            # (`..%2f`, `%2e%2e/...`) — the ASGI stack doesn't normalize those,
            # so `static_dir / full_path` could escape the directory.
            if full_path:
                candidate = (static_dir / full_path).resolve()
                if (candidate == static_root or static_root in candidate.parents) \
                        and candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(static_root / "index.html")

    return app


app = create_app()
