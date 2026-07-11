"""Sync→async bridges for the (synchronous) genai-studio SDK.

The SDK blocks; FastAPI is asyncio. Two seams:

- `run_sync(fn, *args)` — run a blocking call on the default threadpool.
- `aiter_sync(gen_factory)` — pump a sync generator (e.g. a token stream) from
  a worker thread into an async iterator, with cancellation: closing the async
  side sets a threading.Event the pump checks between yields, so a client
  disconnect stops the underlying gateway stream instead of leaking it.
"""

from __future__ import annotations

import asyncio
import threading
from typing import AsyncIterator, Callable, Iterator, TypeVar

from starlette.concurrency import run_in_threadpool

T = TypeVar("T")

_SENTINEL = object()


async def run_sync(fn: Callable[..., T], /, *args, **kwargs) -> T:
    return await run_in_threadpool(fn, *args, **kwargs)


async def aiter_sync(gen_factory: Callable[[], Iterator[T]]) -> AsyncIterator[T]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    stop = threading.Event()

    def _put(item) -> None:
        # Called from the worker thread; drop silently if the loop is closing.
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:
            pass

    def _pump() -> None:
        try:
            for item in gen_factory():
                if stop.is_set():
                    break
                _put(item)
        except Exception as exc:  # surface gateway errors on the async side
            _put(exc)
        finally:
            _put(_SENTINEL)

    thread = threading.Thread(target=_pump, daemon=True, name="sse-pump")
    thread.start()
    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stop.set()
