"""Non-blocking telemetry writes.

THE RULE: the student chat path never awaits a DB commit. Handlers mint UUIDs
up front and `emit()` ORM rows (or callables) into an asyncio.Queue; a single
consumer task batches them into transactions (every 250 ms or 50 items —
ideal for SQLite's single-writer model). On overflow we drop (counting drops)
rather than block chat.

`emit_chat_trace()` appends full-fidelity JSONL lines (system prompt, chunk
texts, final output) to traces/chat-YYYYMMDD.jsonl — the DB stays lean and
queryable; the JSONL is for replay/debugging.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

FLUSH_INTERVAL_S = 0.25
FLUSH_BATCH = 50


class Recorder:
    def __init__(self, session_factory: sessionmaker[Session],
                 traces_dir: Path | None = None, maxsize: int = 10_000):
        self._session_factory = session_factory
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task | None = None
        self._traces_dir = traces_dir
        self.dropped = 0

    # ---- producer side (never blocks) ---------------------------------------

    def emit(self, item: Any) -> None:
        """Enqueue an ORM row, or a callable(session) for updates."""
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped % 100 == 1:
                logger.error("Telemetry queue full — dropped %d items", self.dropped)

    def emit_chat_trace(self, payload: dict) -> None:
        if self._traces_dir is None:
            return
        payload = {"v": 1, "ts": datetime.now(timezone.utc).isoformat(), **payload}
        self.emit(_TraceLine(self._traces_dir, payload))

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    # ---- consumer side -------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="telemetry-recorder")

    async def stop(self) -> None:
        if self._task is None:
            return
        # Drain what's queued, then cancel.
        await self._flush_pending()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            batch = [await self._queue.get()]
            deadline = asyncio.get_running_loop().time() + FLUSH_INTERVAL_S
            while len(batch) < FLUSH_BATCH:
                timeout = deadline - asyncio.get_running_loop().time()
                if timeout <= 0:
                    break
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), timeout))
                except asyncio.TimeoutError:
                    break
            await asyncio.get_running_loop().run_in_executor(None, self._write_batch, batch)

    async def _flush_pending(self) -> None:
        batch = []
        while not self._queue.empty():
            batch.append(self._queue.get_nowait())
        if batch:
            await asyncio.get_running_loop().run_in_executor(None, self._write_batch, batch)

    def _write_batch(self, batch: list) -> None:
        rows = [b for b in batch if not isinstance(b, (_TraceLine,)) and not callable(b)]
        calls: list[Callable] = [b for b in batch if callable(b) and not isinstance(b, _TraceLine)]
        traces = [b for b in batch if isinstance(b, _TraceLine)]
        if rows or calls:
            try:
                with self._session_factory() as session:
                    for row in rows:
                        session.merge(row)
                    for call in calls:
                        call(session)
                    session.commit()
            except Exception:
                logger.exception("Telemetry batch write failed (%d rows)", len(rows))
        for line in traces:
            try:
                line.write()
            except Exception:
                logger.exception("Chat trace write failed")


class _TraceLine:
    def __init__(self, traces_dir: Path, payload: dict):
        self.traces_dir = traces_dir
        self.payload = payload

    def write(self) -> None:
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self.traces_dir / f"chat-{day}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(self.payload, ensure_ascii=False, default=str) + "\n")
