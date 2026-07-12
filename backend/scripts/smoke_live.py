#!/usr/bin/env python3
"""Full-backend live smoke test against the REAL GenAI Studio gateway.

Drives the actual app (lifespan resolves the collections; /api/chat runs the
real retrieval + streamed grounded answer) and checks the end-to-end contract
for a concept question, a syllabus question, an out-of-scope question, and a
dig-deeper escalation.

    cd backend
    export GENAI_STUDIO_API_KEY=...
    python backend/scripts/smoke_live.py        # (venv auto-selected)
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.main import create_app  # noqa: E402

OK, BAD = "✅", "❌"
results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    results.append((ok, msg))
    print(f"  {OK if ok else BAD} {msg}")


def parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for m in re.finditer(r"event: (\w+)\ndata: (.*)", text):
        try:
            out.append((m.group(1), json.loads(m.group(2))))
        except json.JSONDecodeError:
            pass
    return out


def answer_text(events) -> str:
    done = next((d for e, d in events if e == "done"), None)
    if done and done.get("finalText"):
        return done["finalText"]
    return "".join(d.get("text", "") for e, d in events if e == "token")


def main() -> int:
    settings = load_settings()
    if not settings.api_key:
        print("GENAI_STUDIO_API_KEY not set — cannot run the live smoke.")
        return 2
    settings.db.url = "sqlite:///data/smoke.db"

    app = create_app(settings)
    with TestClient(app) as client:
        did = str(uuid.uuid4())
        H = {"X-Device-Id": did}

        health = client.get("/api/health").json()
        print(f"health: {health}")
        check(health.get("gatewayReady") is True,
              "gateway ready (collections resolved)")

        # --- concept question: grounded answer with citations + links --------
        print("\n[1] concept question")
        r = client.post("/api/chat", headers=H, json={
            "conversationId": None,
            "message": "Can you explain the Central Limit Theorem and its conditions?"})
        ev = parse_sse(r.text)
        names = [e for e, _ in ev]
        cits = next((d["citations"] for e, d in ev if e == "citations"), [])
        text = answer_text(ev)
        check("citations" in names and len(cits) > 0, f"returned {len(cits)} citations")
        check(names and names[-1] == "done", "stream ended with done")
        check(bool(re.search(r"\[\d+\]", text)), "answer cites [n] markers")
        check("[link removed" not in text, "no linted (hallucinated) URLs")
        check(any(c.get("url") for c in cits), "citations carry course URLs")

        # --- syllabus question: term+modality grounded quote -----------------
        print("\n[2] syllabus question (Flipped section)")
        client.patch("/api/profile", headers=H, json={"modality": "flipped"})
        r = client.post("/api/chat", headers=H, json={
            "conversationId": None, "message": "how much is the homework worth?"})
        ev = parse_sse(r.text)
        res = next((d["resources"] for e, d in ev if e == "resources"), [])
        text = answer_text(ev)
        check(any(x["kind"] == "syllabus" for x in res), "syllabus link attached")
        check(bool(re.search(r"\d+\s?%|\bpercent", text)) or "refus" in text.lower(),
              f"quoted a figure or safely declined: {text[:70]!r}")

        # --- out-of-scope: should refuse or BEYOND-banner --------------------
        print("\n[3] out-of-scope question")
        r = client.post("/api/chat", headers=H, json={
            "conversationId": None,
            "message": "How do I run a logistic regression with an interaction term?"})
        ev = parse_sse(r.text)
        text = answer_text(ev)
        beyond = "BEYOND STAT 350" in text
        refused = any(e == "refusal" for e, _ in ev)
        check(beyond or refused or "not" in text.lower()[:200],
              f"flagged out-of-scope (beyond={beyond}, refused={refused})")

        # --- dig deeper (escalation agent) -----------------------------------
        print("\n[4] dig deeper (escalation)")
        r = client.post("/api/chat", headers=H, json={
            "conversationId": None, "message": "When do I pool variances vs use Welch?"})
        ev = parse_sse(r.text)
        mid = next((d["messageId"] for e, d in ev if e == "meta"), None)
        if mid:
            rd = client.post(f"/api/messages/{mid}/deeper", headers=H)
            evd = parse_sse(rd.text)
            statuses = [d.get("label") for e, d in evd if e == "status"]
            dtext = answer_text(evd)
            check(any(e == "done" for e, _ in evd) or rd.status_code in (429, 503),
                  f"escalation completed or was gated ({len(dtext)} chars, "
                  f"{len(statuses)} status events)")
        else:
            check(False, "no messageId to escalate")

    n_ok = sum(1 for ok, _ in results if ok)
    print(f"\n{n_ok}/{len(results)} checks passed")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
