"""Per-identity inbound limits (sliding windows, in-memory).

Single-process deployment makes exact in-memory counting correct. Windows:
per-minute, per-10-minute burst, per-day, plus a separate hourly escalation
counter. All limits come from config.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from .config import EscalationCfg, LimitsCfg

MIN = 60
TEN_MIN = 600
DAY = 86400
HOUR = 3600


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None = None       # "per_min" | "burst" | "per_day" | "escalation"
    retry_after_s: int | None = None


class UserLimiter:
    def __init__(self, limits: LimitsCfg, escalation: EscalationCfg):
        self._limits = limits
        self._escalation = escalation
        self._events: dict[str, deque[float]] = defaultdict(deque)       # question timestamps
        self._esc_events: dict[str, deque[float]] = defaultdict(deque)   # escalation timestamps

    @staticmethod
    def _prune(dq: deque[float], horizon: float, now: float) -> None:
        while dq and dq[0] < now - horizon:
            dq.popleft()

    def check_message(self, user_id: str, *, now: float | None = None) -> Verdict:
        now = time.time() if now is None else now
        dq = self._events[user_id]
        self._prune(dq, DAY, now)

        in_min = sum(1 for t in dq if t >= now - MIN)
        if in_min >= self._limits.user_per_min:
            return Verdict(False, "per_min", MIN)
        in_burst = sum(1 for t in dq if t >= now - TEN_MIN)
        if in_burst >= self._limits.burst_per_10min:
            return Verdict(False, "burst", TEN_MIN // 2)
        if len(dq) >= self._limits.user_per_day:
            return Verdict(False, "per_day", DAY // 4)
        dq.append(now)
        return Verdict(True)

    def check_escalation(self, user_id: str, *, now: float | None = None) -> Verdict:
        now = time.time() if now is None else now
        dq = self._esc_events[user_id]
        self._prune(dq, HOUR, now)
        if len(dq) >= self._escalation.per_user_per_hour:
            return Verdict(False, "escalation", HOUR // 2)
        dq.append(now)
        return Verdict(True)

    def remaining_today(self, user_id: str, *, now: float | None = None) -> int:
        now = time.time() if now is None else now
        dq = self._events[user_id]
        self._prune(dq, DAY, now)
        return max(0, self._limits.user_per_day - len(dq))
