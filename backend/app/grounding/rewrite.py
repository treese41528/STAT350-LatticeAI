"""Retrieval-query construction from conversation history.

Heuristic only (no extra LLM call — every gateway request spends one of ~18
RPM slots shared by the whole class): short or anaphoric follow-ups get the
previous user question (and the gist of the last answer) prepended so vector
search has something to bite on. `retrieval.rewriter: task_endpoint` exists in
config for a Phase-0-verified upgrade to the gateway's server-side rewriter.
"""

from __future__ import annotations

import re

_ANAPHORA_RE = re.compile(
    r"^\s*(and|but|so|also|what about|how about|why|why not|then|ok(ay)?|"
    r"wait|huh|again|it|that|this|those|these|the (first|second|third|last) one)\b|"
    r"\b(it|that|this|they|them|those|these)\b\s*\??\s*$", re.I)

_FLUFF_RE = re.compile(
    r"^\s*(hi|hello|hey|please|can you|could you|would you|help me( with)?|"
    r"i (was|am|'m) (wondering|confused about)|quick question[:,]?)\s+", re.I)


def _strip_fluff(text: str) -> str:
    prev = None
    out = text.strip()
    while prev != out:
        prev = out
        out = _FLUFF_RE.sub("", out).strip()
    return out or text.strip()


def _first_sentence(text: str, max_chars: int = 160) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?])\s", text + " ")
    out = m.group(1) if m else text
    return out[:max_chars]


def build_retrieval_query(history: list[dict], message: str,
                          short_token_limit: int = 8) -> str:
    """`history` is prior turns as [{"role": ..., "content": ...}] oldest-first."""
    msg = _strip_fluff(message)
    tokens = msg.split()
    anaphoric = bool(_ANAPHORA_RE.search(msg))
    if len(tokens) >= short_token_limit and not anaphoric:
        return msg

    prev_user = next((h["content"] for h in reversed(history)
                      if h["role"] == "user"), "")
    prev_assistant = next((h["content"] for h in reversed(history)
                           if h["role"] == "assistant"), "")
    parts = []
    if prev_user:
        parts.append(_first_sentence(_strip_fluff(prev_user)))
    if prev_assistant and len(tokens) < 4:
        parts.append(_first_sentence(prev_assistant))
    parts.append(msg)
    return " — ".join(p for p in parts if p)[:500]
