"""Engine + session factory. SQLite runs in WAL mode so the admin dashboard
and nightly jobs can read while the recorder task writes."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from .base import Base

log = logging.getLogger("stat350")


def make_engine(settings: Settings) -> Engine:
    url = settings.db.url
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        # resolve relative sqlite paths against the backend dir
        rel = url.removeprefix("sqlite:///")
        path = settings.resolve_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"

    engine = create_engine(url, future=True)

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_schema(engine: Engine) -> None:
    """Create missing tables, THEN add any columns the models gained since the
    database was first created.

    We deliberately don't run Alembic (single-maintainer, SQLite). But
    `create_all` only ever creates *missing tables* — it never adds a column to
    a table that already exists. So an additive model change (a new nullable
    telemetry column like `messages.used_own_key`) silently breaks every write
    against a pre-existing DB. This reconciles the two: for each existing table,
    ADD COLUMN for any model column the DB lacks.

    Additive + nullable only (which is all our telemetry ever is). A new NOT
    NULL column without a default can't be added to a populated table in SQLite,
    so we skip it with a loud warning rather than crash — that case needs a
    hand-written migration."""
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    tables_on_disk = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables_on_disk:
                continue  # just created by create_all — already at current schema
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable and col.default is None and col.server_default is None:
                    log.warning("schema: %s.%s is missing and NOT NULL without a "
                                "default — needs a manual migration; skipping",
                                table.name, col.name)
                    continue
                coltype = col.type.compile(engine.dialect)
                conn.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))
                log.info("schema: added missing column %s.%s (%s)",
                         table.name, col.name, coltype)
