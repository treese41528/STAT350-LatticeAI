"""SyllabusStore: manifest+fetch sync, (term, modality) lookup, path-safety,
cache-keeps-on-failure, and local fallback. httpx is mocked — no network."""

from __future__ import annotations

import json
import urllib.parse

import app.syllabi_store as ss_mod
from app.syllabi_store import SyllabusStore

MANIFEST = {"files": ["Syllabus_SUMMER_2026.md", "Syllabus_SPRING_2026_Flipped.md",
                      "Syllabus_SPRING_2026_Online.md"]}
FILES = {
    "index.json": json.dumps(MANIFEST),
    "Syllabus_SUMMER_2026.md": "## Grading Policy\n| Homework | 26% |",
    "Syllabus_SPRING_2026_Flipped.md": "Homework is 24% (Flipped).",
    "Syllabus_SPRING_2026_Online.md": "Homework is 24% (Online).",
}


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class _Client:
    """Stand-in for httpx.Client; serves canned objects keyed by the URL tail."""
    def __init__(self, files):
        self.files = files

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        return _Resp(200, self.files[name]) if name in self.files else _Resp(404, "")


def _serve(monkeypatch, files):
    """Point the store's httpx.Client at canned files (auto-restored)."""
    monkeypatch.setattr(ss_mod.httpx, "Client", lambda *a, **k: _Client(files))


def _store(settings, tmp_path):
    settings.syllabi_store.enabled = True
    settings.syllabi_store.supabase_url = "https://x.supabase.co"
    settings.syllabi_store.cache_dir = str(tmp_path / "cache")
    return SyllabusStore(settings)


def test_refresh_and_term_modality_lookup(settings, tmp_path, monkeypatch):
    _serve(monkeypatch, FILES)
    store = _store(settings, tmp_path)
    assert store.refresh() == 3
    # the (term, modality) filter picks exactly the right file
    assert store.get("SUMMER 2026", "summer")[0] == "Syllabus_SUMMER_2026.md"
    assert store.get("SPRING 2026", "flipped")[0] == "Syllabus_SPRING_2026_Flipped.md"
    assert store.get("SPRING 2026", "online")[0] == "Syllabus_SPRING_2026_Online.md"
    # content is the FULL file (grading table present)
    assert "26%" in store.get("SUMMER 2026", "summer")[1]
    # no match -> None
    assert store.get("FALL 2025", "flipped") is None


def test_disabled_store_is_a_noop(settings, tmp_path, monkeypatch):
    _serve(monkeypatch, FILES)
    store = _store(settings, tmp_path)
    store.enabled = False
    assert store.refresh() == 0 and store.get("SUMMER 2026", "summer") is None


def test_refresh_keeps_cache_on_failure(settings, tmp_path, monkeypatch):
    _serve(monkeypatch, FILES)
    store = _store(settings, tmp_path)
    assert store.refresh() == 3
    # Supabase "goes down" (manifest 404) -> keep the good cache, don't wipe it
    _serve(monkeypatch, {})
    assert store.refresh() == 3
    assert store.get("SUMMER 2026", "summer") is not None


def test_manifest_rejects_paths_and_non_md(settings, tmp_path, monkeypatch):
    bad = dict(FILES)
    bad["index.json"] = json.dumps({"files": [
        "Syllabus_SUMMER_2026.md", "../../etc/passwd", "sub/dir.md", "notes.txt"]})
    _serve(monkeypatch, bad)
    store = _store(settings, tmp_path)
    store.refresh()
    assert store.count() == 1   # only the clean .md survived the filter


def test_local_fallback(settings, tmp_path, monkeypatch):
    _serve(monkeypatch, FILES)
    store = _store(settings, tmp_path)
    store.refresh()                       # also writes the local cache
    # a fresh store with Supabase unreachable loads from the local copy
    _serve(monkeypatch, {})
    fresh = _store(settings, tmp_path)
    assert fresh.load_local() == 3
    assert fresh.get("SUMMER 2026", "summer")[0] == "Syllabus_SUMMER_2026.md"
