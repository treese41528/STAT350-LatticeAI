"""Schema. Design rules:

- Hot-path PKs are app-generated UUID strings so the chat handler never waits
  on a DB round-trip to learn an id.
- JSON payloads carry {"v": 1} for schema versioning independent of Alembic.
- Values worth filtering on (top_score, weak, source_file) are denormalized
  into real columns — SQLite can't index into JSON.
- No IP addresses anywhere, ever.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # "device:<uuid>" now; a CAS login links purdue_id onto the same row later.
    device_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    purdue_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), default="student")
    modality: Mapped[str | None] = mapped_column(String(16))   # flipped|traditional|indy|online|winter
    consent_research: Mapped[bool | None] = mapped_column(Boolean)  # future IRB opt-in
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(200))
    client_app_version: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow,
                                                 onupdate=utcnow, index=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.seq")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_seq", "conversation_id", "seq"),
        Index("ix_messages_kind_created", "answer_kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))          # user | assistant
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)   # time to first token
    finish_reason: Mapped[str | None] = mapped_column(String(24))
    # rag_answer | refusal | resource_lookup | smalltalk | escalation
    answer_kind: Mapped[str | None] = mapped_column(String(24))
    intent: Mapped[str | None] = mapped_column(String(32))  # router output
    # whether the student used their OWN key (a bool ONLY — never the key)
    used_own_key: Mapped[bool | None] = mapped_column(Boolean)
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class RetrievalEvent(Base):
    __tablename__ = "retrieval_events"
    __table_args__ = (Index("ix_retrieval_weak_created", "weak", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    question_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id"), index=True)
    raw_query: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str | None] = mapped_column(Text)
    k_requested: Mapped[int] = mapped_column(Integer)
    collections_queried: Mapped[dict] = mapped_column(JSON)
    # [{collection, source_file, chunk_id, score, rank}] — no chunk text (JSONL has it)
    results: Mapped[list] = mapped_column(JSON)
    top_score: Mapped[float | None] = mapped_column(Float, index=True)
    mean_score: Mapped[float | None] = mapped_column(Float)
    retrieval_latency_ms: Mapped[int | None] = mapped_column(Integer)
    tier: Mapped[str | None] = mapped_column(String(16))   # strong | caveat | no_evidence
    weak: Mapped[bool] = mapped_column(Boolean, default=False)
    weak_reason: Mapped[str | None] = mapped_column(String(32))
    embedding_index_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"), index=True)
    marker: Mapped[int] = mapped_column(Integer)            # the [n]
    retrieval_event_id: Mapped[str | None] = mapped_column(ForeignKey("retrieval_events.id"))
    rank_in_results: Mapped[int | None] = mapped_column(Integer)
    source_file: Mapped[str | None] = mapped_column(String(255))
    collection: Mapped[str | None] = mapped_column(String(64))
    # False = the model cited a passage that doesn't exist → prompt-quality tripwire
    resolved: Mapped[bool] = mapped_column(Boolean, default=True)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("message_id"),
        Index("ix_feedback_rating_created", "rating", "created_at"),
        Index("ix_feedback_open", "resolved_at", sqlite_where=None),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[int] = mapped_column(Integer)            # +1 / -1
    reason_tags: Mapped[list] = mapped_column(JSON, default=list)
    free_text: Mapped[str | None] = mapped_column(Text)     # capped app-side; nulled at retention
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # triage workflow
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    # kb_gap | chunking | prompt | course_map | policy | ops | not_actionable
    resolution_category: Mapped[str | None] = mapped_column(String(24))


class UiEvent(Base):
    __tablename__ = "ui_events"
    __table_args__ = (Index("ix_ui_events_type_created", "event_type", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    message_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)   # = agent run id
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id"), index=True)
    retrieval_event_id: Mapped[str | None] = mapped_column(ForeignKey("retrieval_events.id"))
    trigger: Mapped[str] = mapped_column(String(32))        # user_dig_deeper | refusal_dig_deeper
    model: Mapped[str | None] = mapped_column(String(100))
    steps: Mapped[int | None] = mapped_column(Integer)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    stopped: Mapped[str | None] = mapped_column(String(24))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str | None] = mapped_column(String(16))  # answered | refused | error | timeout
    trace_file: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ErrorEvent(Base):
    __tablename__ = "error_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32))  # gateway_chat|gateway_retrieval|app|frontend|overload_shed
    error_type: Mapped[str | None] = mapped_column(String(64))
    http_status: Mapped[int | None] = mapped_column(Integer)
    user_id: Mapped[str | None] = mapped_column(String(36))
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    message_id: Mapped[str | None] = mapped_column(String(36))
    request_id: Mapped[str | None] = mapped_column(String(36), index=True)
    detail: Mapped[str | None] = mapped_column(Text)        # truncated app-side
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class KbSnapshot(Base):
    __tablename__ = "kb_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_version: Mapped[str] = mapped_column(String(32), unique=True)
    kb_ids: Mapped[dict] = mapped_column(JSON)
    chunking_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    golden_set_version: Mapped[str | None] = mapped_column(String(64))
    index_version: Mapped[str | None] = mapped_column(String(32))
    k: Mapped[int | None] = mapped_column(Integer)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    mrr: Mapped[float | None] = mapped_column(Float)
    weak_rate: Mapped[float | None] = mapped_column(Float)
    per_chapter: Mapped[dict] = mapped_column(JSON, default=dict)
    harness_version: Mapped[str | None] = mapped_column(String(16))


class DailyStat(Base):
    __tablename__ = "daily_stats"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    active_users: Mapped[int] = mapped_column(Integer, default=0)
    questions: Mapped[int] = mapped_column(Integer, default=0)
    refusals: Mapped[int] = mapped_column(Integer, default=0)
    weak_retrievals: Mapped[int] = mapped_column(Integer, default=0)
    escalations: Mapped[int] = mapped_column(Integer, default=0)
    thumbs_up: Mapped[int] = mapped_column(Integer, default=0)
    thumbs_down: Mapped[int] = mapped_column(Integer, default=0)
    p50_latency_ms: Mapped[int | None] = mapped_column(Integer)
    p50_ttft_ms: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    overload_events: Mapped[int] = mapped_column(Integer, default=0)
    telemetry_dropped: Mapped[int] = mapped_column(Integer, default=0)
