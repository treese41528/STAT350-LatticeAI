"""ensure_schema() must add columns the models gained to a DB created before
them — the failure that broke telemetry after BYOK added messages.used_own_key
(create_all never alters an existing table)."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.db import models as m  # noqa: F401  (registers tables on Base.metadata)
from app.db.engine import ensure_schema


def _cols(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_ensure_schema_adds_missing_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db", future=True)
    # simulate an OLD messages table — before intent/answer_kind/used_own_key/ttft_ms
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE messages (id VARCHAR PRIMARY KEY, conversation_id VARCHAR, "
            "seq INTEGER, role VARCHAR, content VARCHAR, created_at DATETIME)"))
    before = _cols(engine, "messages")
    assert "used_own_key" not in before and "intent" not in before

    ensure_schema(engine)   # create_all + reconcile columns

    after = _cols(engine, "messages")
    for col in ("used_own_key", "intent", "answer_kind", "ttft_ms", "model"):
        assert col in after, f"{col} not added"
    # and the new column is actually usable
    with engine.begin() as c:
        c.execute(text("INSERT INTO messages (id, role, content, used_own_key) "
                       "VALUES ('m1', 'assistant', 'hi', 1)"))
        val = c.execute(text("SELECT used_own_key FROM messages WHERE id='m1'")).scalar()
    assert val == 1


def test_ensure_schema_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/fresh.db", future=True)
    ensure_schema(engine)          # first run creates everything
    cols = _cols(engine, "messages")
    ensure_schema(engine)          # second run must be a no-op, not error
    assert _cols(engine, "messages") == cols
