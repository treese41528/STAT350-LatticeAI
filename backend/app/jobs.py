"""Nightly maintenance, run as short-lived processes via systemd timers
(WAL + busy_timeout make brief cross-process writes safe):

    python backend/scripts/maintenance.py rollup    # yesterday's daily_stats row
    python backend/scripts/maintenance.py purge     # retention: delete old rows, null old free-text
"""

from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update

from .config import load_settings
from .db import models as m
from .db.base import Base
from .db.engine import make_engine, make_session_factory


def _day_bounds(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def cmd_rollup(args) -> int:
    settings = load_settings()
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    day = (datetime.now(timezone.utc) - timedelta(days=1)) \
        if not args.date else \
        datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
    start, end = _day_bounds(day)
    key = start.strftime("%Y-%m-%d")

    with sf() as session:
        q_msgs = session.scalars(select(m.Message).where(
            m.Message.role == "assistant",
            m.Message.created_at >= start, m.Message.created_at < end)).all()
        latencies = [x.latency_ms for x in q_msgs if x.latency_ms]
        ttfts = [x.ttft_ms for x in q_msgs if x.ttft_ms]
        stat = session.get(m.DailyStat, key) or m.DailyStat(date=key)
        stat.questions = len(q_msgs)
        stat.refusals = sum(1 for x in q_msgs if x.answer_kind == "refusal")
        stat.total_tokens = sum(x.total_tokens or 0 for x in q_msgs)
        stat.p50_latency_ms = int(statistics.median(latencies)) if latencies else None
        stat.p50_ttft_ms = int(statistics.median(ttfts)) if ttfts else None
        stat.active_users = session.scalar(
            select(func.count(func.distinct(m.Conversation.user_id)))
            .join(m.Message, m.Message.conversation_id == m.Conversation.id)
            .where(m.Message.created_at >= start,
                   m.Message.created_at < end)) or 0
        stat.weak_retrievals = session.scalar(
            select(func.count(m.RetrievalEvent.id))
            .where(m.RetrievalEvent.weak,
                   m.RetrievalEvent.created_at >= start,
                   m.RetrievalEvent.created_at < end)) or 0
        stat.escalations = session.scalar(
            select(func.count(m.Escalation.id))
            .where(m.Escalation.created_at >= start,
                   m.Escalation.created_at < end)) or 0
        stat.thumbs_up = session.scalar(
            select(func.count(m.Feedback.id))
            .where(m.Feedback.rating == 1,
                   m.Feedback.created_at >= start,
                   m.Feedback.created_at < end)) or 0
        stat.thumbs_down = session.scalar(
            select(func.count(m.Feedback.id))
            .where(m.Feedback.rating == -1,
                   m.Feedback.created_at >= start,
                   m.Feedback.created_at < end)) or 0
        stat.overload_events = session.scalar(
            select(func.count(m.ErrorEvent.id))
            .where(m.ErrorEvent.scope == "overload_shed",
                   m.ErrorEvent.created_at >= start,
                   m.ErrorEvent.created_at < end)) or 0
        session.merge(stat)
        session.commit()
    print(f"daily_stats[{key}]: questions={stat.questions} "
          f"refusals={stat.refusals} weak={stat.weak_retrievals} "
          f"users={stat.active_users}")
    return 0


def cmd_purge(args) -> int:
    settings = load_settings()
    engine = make_engine(settings)
    sf = make_session_factory(engine)
    now = datetime.now(timezone.utc)
    cut_main = now - timedelta(days=settings.db.retention_days)
    cut_ui = now - timedelta(days=180)
    cut_err = now - timedelta(days=90)

    with sf() as session:
        # citations/retrieval/escalations hang off messages; delete leaf-first
        old_msg_ids = select(m.Message.id).where(m.Message.created_at < cut_main)
        n_cit = session.execute(delete(m.Citation)
                                .where(m.Citation.message_id.in_(old_msg_ids))
                                ).rowcount
        n_esc = session.execute(delete(m.Escalation)
                                .where(m.Escalation.created_at < cut_main)).rowcount
        n_rev = session.execute(delete(m.RetrievalEvent)
                                .where(m.RetrievalEvent.created_at < cut_main)
                                ).rowcount
        n_msg = session.execute(delete(m.Message)
                                .where(m.Message.created_at < cut_main)).rowcount
        # conversations with no messages left
        empty = select(m.Conversation.id).where(~select(m.Message.id).where(
            m.Message.conversation_id == m.Conversation.id).exists())
        n_convo = session.execute(delete(m.Conversation)
                                  .where(m.Conversation.id.in_(empty))).rowcount
        # feedback rows are kept (triage record) but free-text is nulled
        n_ft = session.execute(update(m.Feedback)
                               .where(m.Feedback.created_at < cut_main,
                                      m.Feedback.free_text.is_not(None))
                               .values(free_text=None)).rowcount
        n_ui = session.execute(delete(m.UiEvent)
                               .where(m.UiEvent.created_at < cut_ui)).rowcount
        n_err = session.execute(delete(m.ErrorEvent)
                                .where(m.ErrorEvent.created_at < cut_err)).rowcount
        session.commit()
    print(f"purged: {n_msg} messages, {n_rev} retrievals, {n_cit} citations, "
          f"{n_esc} escalations, {n_convo} empty conversations, "
          f"{n_ui} ui_events, {n_err} errors; nulled {n_ft} feedback texts "
          f"(cutoff {cut_main.date()})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="maintenance.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_roll = sub.add_parser("rollup")
    p_roll.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday)")
    p_roll.set_defaults(fn=cmd_rollup)
    p_purge = sub.add_parser("purge")
    p_purge.set_defaults(fn=cmd_purge)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
