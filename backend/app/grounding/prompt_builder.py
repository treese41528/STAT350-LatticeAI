"""Assemble the messages array for the single grounded chat call."""

from __future__ import annotations

from .retrieve import Passage

CAVEAT_INSTRUCTION = (
    "\n\nNOTE: The retrieved passages are only loosely related to this "
    "question. Answer only what they support, say clearly which parts of the "
    "question the course materials don't cover, and suggest the student "
    "rephrase or ask about a related course topic."
)

SYLLABUS_INSTRUCTION = (
    "\n\nSYLLABUS MODE: The student is asking about course policy or logistics. "
    "Quote the specific figure or rule from the passages (e.g. a grade weight, "
    "a make-up rule, a deadline) and cite it [n]. Policies can differ by "
    "section, so always tell the student to confirm against their section's "
    "official syllabus and schedule — their links are shown as resources — and "
    "for exact dates defer to that syllabus. Do not state a policy the passages "
    "don't support."
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
                   syllabus: bool = False,
                   history_window: int = 10) -> list[dict]:
    system = tutor_core
    if modality:
        system += f"\n\nSTUDENT CONTEXT: enrolled section modality = {modality}."
    if passages:
        system += "\n\n" + _passage_block(passages)
    if caveat:
        system += CAVEAT_INSTRUCTION
    if syllabus:
        system += SYLLABUS_INSTRUCTION

    messages: list[dict] = [{"role": "system", "content": system}]
    for turn in history[-history_window:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})
    return messages
