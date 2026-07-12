"""SSE plumbing: event formatting and a keep-alive wrapper.

Contract with the SPA (frontend/src/api/types.ts):
  event order  meta → queue* → status* → citations → resources → token* →
               (refusal) → done | error
  keep-alive   ": ping" comment every 15s
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi.responses import StreamingResponse

PING_INTERVAL_S = 15

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _with_pings(source: AsyncIterator[tuple[str, dict]]) -> AsyncIterator[str]:
    it = source.__aiter__()
    next_item: asyncio.Task | None = None
    try:
        while True:
            if next_item is None:
                next_item = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({next_item}, timeout=PING_INTERVAL_S)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                event, data = next_item.result()
            except StopAsyncIteration:
                return
            next_item = None
            yield format_sse(event, data)
    finally:
        if next_item is not None and not next_item.done():
            next_item.cancel()
            # let the cancellation settle before closing the source generator,
            # so aclose() doesn't race an in-flight __anext__
            try:
                await next_item
            except (asyncio.CancelledError, StopAsyncIteration, Exception):
                pass
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass


def sse_response(source: AsyncIterator[tuple[str, dict]]) -> StreamingResponse:
    return StreamingResponse(_with_pings(source), media_type="text/event-stream",
                             headers=SSE_HEADERS)
