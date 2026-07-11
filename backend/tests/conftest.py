from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import load_settings  # noqa: E402
from app.course_map.resolver import CourseMapResolver  # noqa: E402


@pytest.fixture(scope="session")
def resolver() -> CourseMapResolver:
    return CourseMapResolver.from_file(BACKEND / "data" / "course_map.json")


@pytest.fixture()
def settings(tmp_path):
    s = load_settings(BACKEND / "config.yaml")
    s.db.url = f"sqlite:///{tmp_path}/test.db"
    s.secret_key = "test-secret"
    s.admin_token = "test-admin-token"
    return s


@pytest.fixture()
def device_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def client(settings):
    """TestClient with lifespan (recorder etc.). Degraded gateway (no key)."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    app = create_app(settings)
    with TestClient(app) as c:
        c.app = app
        yield c


class FakeGateway:
    """Stands in for app.gateway.Gateway in grounded-pipeline tests."""

    def __init__(self, retrieval_payloads: dict | None = None,
                 stream_chunks: list[str] | None = None,
                 stream_error: Exception | None = None):
        self.kb_ids = {"webbook": "kb-web", "transcripts": "kb-tr"}
        self.retrieval_payloads = retrieval_payloads or {}
        self.stream_chunks = stream_chunks or []
        self.stream_error = stream_error
        self.retrieval_calls: list = []
        self.chat_calls: list = []

    def retrieval_query(self, query, collection_ids, k, hybrid=False):
        self.retrieval_calls.append((query, tuple(collection_ids), k))
        key = collection_ids[0] if len(collection_ids) == 1 else "both"
        return self.retrieval_payloads.get(key, {"documents": [],
                                                 "distances": [],
                                                 "metadatas": []})

    def stream_chat(self, messages, temperature=None, max_tokens=None):
        self.chat_calls.append(messages)
        if self.stream_error is not None:
            raise self.stream_error

        def gen():
            yield from self.stream_chunks
        return gen()


def webbook_payload(*chunks: tuple[str, str, float]) -> dict:
    """chunks: (rst_name, text, score) — score is a SIMILARITY (higher=better)
    to match this gateway (Phase 0 probe #4)."""
    return {
        "documents": [[t for _, t, _ in chunks]],
        "distances": [[d for _, _, d in chunks]],
        "metadatas": [[{"name": n, "file_id": f"f-{i}"}
                       for i, (n, _, _) in enumerate(chunks)]],
    }
