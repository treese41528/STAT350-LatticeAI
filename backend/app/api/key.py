"""Validate a student's own GenAI Studio key. The key rides the X-GenAI-Key
header, is checked against the gateway (auth + real retrieval), and is NEVER
stored, logged, or echoed back."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..concurrency import run_sync
from ..db import models as m
from .deps import BYOK_HEADER, get_deps

router = APIRouter()


@router.post("/api/key/validate")
async def validate_key(request: Request):
    deps = get_deps(request)
    if not deps.settings.byok.enabled:
        raise HTTPException(status_code=404)
    if not deps.gateway_ready:
        raise HTTPException(status_code=503, detail={
            "error": {"code": "gateway_unavailable",
                      "message": "The tutor can't reach the gateway right now.",
                      "retryable": True}})
    from ..byok import valid_key_format
    key = (request.headers.get(BYOK_HEADER) or "").strip()
    if not valid_key_format(key):
        return {"authOk": False, "retrievalOk": False, "usable": False,
                "message": "That doesn't look like a valid API key."}

    verdict = await run_sync(deps.gateway_pool.validate, key)
    # usable = the key will actually work for this deployment's retrieval mode
    # ("shared" mode doesn't need the student's key to read the collection)
    usable = verdict.auth_ok and (
        verdict.retrieval_ok or deps.settings.byok.retrieval == "shared")
    # telemetry: whether validation succeeded — NEVER the key
    deps.recorder.emit(m.UiEvent(
        event_type="own_key_validated",
        payload={"auth": verdict.auth_ok, "retrieval": verdict.retrieval_ok,
                 "usable": usable}))
    return {"authOk": verdict.auth_ok, "retrievalOk": verdict.retrieval_ok,
            "usable": usable, "message": verdict.message}
