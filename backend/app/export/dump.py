"""Anonymized, R-friendly data export.

    python -m app.export --from 2026-08-01 --to 2026-12-20 --out exports/fall26
    python -m app.export --out exports/all --include-content   # with warning

Pseudonymization: anon_user = HMAC-SHA256(EXPORT_SALT, users.id)[:12] — stable
across exports (longitudinal analysis works) but not reversible without the
server-held salt. Timestamps truncated to the hour. Message content and
feedback free-text excluded unless explicitly flagged in.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..config import load_settings
from ..db import models as m
from ..db.engine import make_engine, make_session_factory

README = """# STAT 350 Tutor data export

Generated: {now}   Range: {frm} .. {to}

- `anon_user` = HMAC(salt, user_id)[:12] — stable pseudonym; not reversible.
- `date_hour` = event time truncated to the hour (UTC).
- One observation per row, snake_case headers.

Files: questions.csv, retrieval_results.csv (long format), feedback.csv,
ui_events.csv, daily_stats.csv, eval_runs.csv{extra}

Starter R:
```r
library(tidyverse)
q <- read_csv("questions.csv")
q |> count(weak, refused) |> mutate(share = n / sum(n))
rr <- read_csv("retrieval_results.csv")
rr |> ggplot(aes(score, fill = collection)) + geom_histogram(bins = 40)
```
"""


def _anon(salt: str, user_id: str | None) -> str:
    if not user_id:
        return ""
    return hmac.new(salt.encode(), user_id.encode(), hashlib.sha256) \
        .hexdigest()[:12]


def _hour(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%dT%H:00Z")


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not rows:
            fh.write("")
            return
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name}: {len(rows)} rows")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.export")
    parser.add_argument("--from", dest="frm", default=None)
    parser.add_argument("--to", dest="to", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--include-freetext", action="store_true")
    args = parser.parse_args(argv)

    settings = load_settings()
    out = settings.resolve_path(args.out)
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    salt = settings.export_salt

    frm = datetime.fromisoformat(args.frm).replace(tzinfo=timezone.utc) \
        if args.frm else datetime(2000, 1, 1, tzinfo=timezone.utc)
    to = datetime.fromisoformat(args.to).replace(tzinfo=timezone.utc) \
        if args.to else datetime.now(timezone.utc)

    if args.include_content or args.include_freetext:
        print("WARNING: including raw content — treat the export as "
              "student-record data (FERPA); do not share outside the course "
              "staff.")

    with sf() as session:
        users = {u.id: u for u in session.scalars(select(m.User)).all()}
        convo_user = {c.id: c.user_id for c in
                      session.scalars(select(m.Conversation)).all()}

        # questions.csv — one row per user question + its answer facts
        questions = []
        msgs = session.scalars(
            select(m.Message).where(m.Message.role == "assistant",
                                    m.Message.created_at >= frm,
                                    m.Message.created_at <= to)).all()
        rev_by_req = {r.request_id: r for r in session.scalars(
            select(m.RetrievalEvent)
            .where(m.RetrievalEvent.created_at >= frm,
                   m.RetrievalEvent.created_at <= to)).all()}
        fb_by_msg = {f.message_id: f for f in
                     session.scalars(select(m.Feedback)).all()}
        esc_msgs = {e.message_id for e in
                    session.scalars(select(m.Escalation)).all()}
        for msg in msgs:
            rev = rev_by_req.get(msg.request_id)
            fb = fb_by_msg.get(msg.id)
            row = {
                "question_id": msg.request_id or msg.id,
                "anon_user": _anon(salt, convo_user.get(msg.conversation_id)),
                "date_hour": _hour(msg.created_at),
                "intent": msg.intent, "answer_kind": msg.answer_kind,
                "tier": rev.tier if rev else "",
                "top_score": rev.top_score if rev else "",
                "weak": bool(rev.weak) if rev else "",
                "refused": msg.answer_kind == "refusal",
                "escalated": msg.id in esc_msgs,
                "rating": fb.rating if fb else "",
                "tags": ";".join(fb.reason_tags or []) if fb else "",
                "latency_ms": msg.latency_ms, "ttft_ms": msg.ttft_ms,
                "answer_tokens": msg.completion_tokens,
                "model": msg.model,
            }
            if args.include_content:
                row["content"] = msg.content
            questions.append(row)
        _write(out / "questions.csv", questions)

        # retrieval_results.csv — long format
        rr_rows = []
        for rev in rev_by_req.values():
            for res in rev.results or []:
                rr_rows.append({
                    "question_id": rev.request_id,
                    "date_hour": _hour(rev.created_at),
                    "rank": res.get("rank"),
                    "collection": res.get("collection"),
                    "source_file": res.get("source_file"),
                    "score": res.get("score"),
                    "tier": rev.tier,
                })
        _write(out / "retrieval_results.csv", rr_rows)

        # feedback.csv
        fb_rows = []
        for fb in fb_by_msg.values():
            if not (frm <= fb.created_at.replace(tzinfo=timezone.utc) <= to):
                continue
            row = {
                "message_id": fb.message_id,
                "anon_user": _anon(salt, fb.user_id),
                "date_hour": _hour(fb.created_at),
                "rating": fb.rating,
                "tags": ";".join(fb.reason_tags or []),
                "resolution_category": fb.resolution_category or "",
            }
            if args.include_freetext:
                row["free_text"] = fb.free_text or ""
            fb_rows.append(row)
        _write(out / "feedback.csv", fb_rows)

        # ui_events.csv
        ui_rows = [{
            "anon_user": _anon(salt, e.user_id),
            "date_hour": _hour(e.created_at),
            "event_type": e.event_type,
            "payload": json.dumps(e.payload or {}),
        } for e in session.scalars(
            select(m.UiEvent).where(m.UiEvent.created_at >= frm,
                                    m.UiEvent.created_at <= to)).all()]
        _write(out / "ui_events.csv", ui_rows)

        # daily_stats.csv + eval_runs.csv
        _write(out / "daily_stats.csv", [
            {c.name: getattr(r, c.name) for c in m.DailyStat.__table__.columns}
            for r in session.scalars(select(m.DailyStat)
                                     .order_by(m.DailyStat.date)).all()])
        _write(out / "eval_runs.csv", [
            {c.name: (json.dumps(getattr(r, c.name))
                      if c.name == "per_chapter" else getattr(r, c.name))
             for c in m.EvalRun.__table__.columns}
            for r in session.scalars(select(m.EvalRun)).all()])

    extra = ""
    if args.include_content:
        extra = ", plus content columns (HANDLE AS STUDENT RECORDS)"
    (out / "README.md").write_text(README.format(
        now=datetime.now(timezone.utc).isoformat(), frm=frm.date(),
        to=to.date(), extra=extra), encoding="utf-8")
    print(f"Export complete → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
