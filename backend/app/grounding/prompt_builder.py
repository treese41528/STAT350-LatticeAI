"""Assemble the messages array for the single grounded chat call."""

from __future__ import annotations

from .retrieve import Passage

CAVEAT_INSTRUCTION = (
    "\n\nNOTE: The retrieved passages are only loosely related to this "
    "question. Answer only what they support, say clearly which parts of the "
    "question the course materials don't cover, and suggest the student "
    "rephrase or ask about a related course topic."
)


def _passage_block(passages: list[Passage]) -> str:
    lines = ["", "CONTEXT PASSAGES (cite as [n]; the app renders all links):"]
    for p in passages:
        label = p.resolved.title if p.resolved and p.resolved.title else p.collection
        lines.append(f"[{p.n}] ({p.collection} | {label})\n{p.text.strip()}")
    return "\n\n".join(lines)


def build_messages(tutor_core: str, passages: list[Passage],
                   history: list[dict], user_message: str, *,
                   modality: str | None = None, caveat: bool = False,
                   history_window: int = 10) -> list[dict]:
    system = tutor_core
    if modality:
        system += f"\n\nSTUDENT CONTEXT: enrolled section modality = {modality}."
    if passages:
        system += "\n\n" + _passage_block(passages)
    if caveat:
        system += CAVEAT_INSTRUCTION

    messages: list[dict] = [{"role": "system", "content": system}]
    for turn in history[-history_window:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})
    return messages
