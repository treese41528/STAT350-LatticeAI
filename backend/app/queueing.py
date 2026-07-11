"""FIFO admission queue in front of the gateway.

The RateLimiter paces request *starts*; this bounds *concurrent* streams and
gives waiting students an honest queue position for the SSE `queue` event.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Awaitable, Callable


class QueueFullError(Exception):
    pass


class LlmQueue:
    def __init__(self, max_concurrent: int, max_waiting: int = 100):
        self._max = max_concurrent
        self._max_waiting = max_waiting
        self._active = 0
        self._waiters: list[asyncio.Event] = []  # FIFO; index = position
        self._lock = asyncio.Lock()

    @property
    def depth(self) -> int:
        """Waiting + active beyond capacity — the degradation-ladder signal."""
        return len(self._waiters) + max(0, self._active - self._max)

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    async def _positions_changed(self) -> None:
        # Wake every waiter so it can re-check its position and report it.
        for ev in self._waiters:
            ev.set()

    @asynccontextmanager
    async def slot(self, on_position: Callable[[int], Awaitable[None]] | None = None):
        """Wait for a slot, reporting queue position changes via on_position.

        Raises QueueFullError immediately when the waiting line is full.
        """
        my_event = asyncio.Event()
        async with self._lock:
            if self._active < self._max and not self._waiters:
                self._active += 1
                acquired = True
            else:
                if len(self._waiters) >= self._max_waiting:
                    raise QueueFullError()
                self._waiters.append(my_event)
                acquired = False

        last_reported = None
        try:
            while not acquired:
                async with self._lock:
                    try:
                        pos = self._waiters.index(my_event)
                    except ValueError:
                        pos = 0
                    if pos == 0 and self._active < self._max:
                        self._waiters.remove(my_event)
                        self._active += 1
                        acquired = True
                        await self._positions_changed()
                if not acquired:
                    if on_position and pos != last_reported:
                        # position is 1-based for humans
                        await on_position(pos + 1)
                        last_reported = pos
                    my_event.clear()
                    await my_event.wait()
            yield
        finally:
            async with self._lock:
                if acquired:
                    self._active -= 1
                elif my_event in self._waiters:  # cancelled while waiting
                    self._waiters.remove(my_event)
                await self._positions_changed()
