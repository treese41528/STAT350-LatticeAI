"""Exam-week degradation ladder, driven by queue depth.

Levels (cumulative):
  0 normal
  1 disable "dig deeper" escalation           (depth >= disable_escalation_at)
  2 shrink retrieval k and answer max_tokens  (depth >= shrink_retrieval_at)
  3 reject new messages with a friendly page  (depth >= reject_at)

Transitions are logged so the professor has evidence for an RCAC quota ask.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import DegradationCfg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OverloadState:
    level: int
    escalation_enabled: bool
    shrink: bool          # halve retrieval k, cap max_tokens
    reject: bool


class Overload:
    def __init__(self, cfg: DegradationCfg):
        self._cfg = cfg
        self._last_level = 0

    def state(self, queue_depth: int) -> OverloadState:
        cfg = self._cfg
        if queue_depth >= cfg.reject_at:
            level = 3
        elif queue_depth >= cfg.shrink_retrieval_at:
            level = 2
        elif queue_depth >= cfg.disable_escalation_at:
            level = 1
        else:
            level = 0
        if level != self._last_level:
            logger.warning("Overload ladder %d -> %d (queue depth %d)",
                           self._last_level, level, queue_depth)
            self._last_level = level
        return OverloadState(
            level=level,
            escalation_enabled=level < 1,
            shrink=level >= 2,
            reject=level >= 3,
        )
