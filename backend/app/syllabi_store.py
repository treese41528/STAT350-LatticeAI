"""Syllabus content store.

Serves the tutor the FULL (term, modality) syllabus text so policy questions
(the grading TABLE, deadlines, etc.) always answer — instead of relying on KB
retrieval, where a weakly-embedded markdown table ranks ~30th and misses.

Source of truth is Supabase Storage (a PUBLIC bucket): a manifest
`<prefix>index.json` = {"files": [...]} plus the .md files. Every read is a
plain public GET — no key, no RLS, no Data API; the app only READS. It syncs
into an in-memory cache + a local fallback copy, refreshed on a timer and on
demand, so the professor edits syllabi in Supabase and they go live WITHOUT
redeploying (and a Supabase outage never breaks answers — the last good copy
keeps serving).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional
from urllib.parse import quote

import httpx

from .config import Settings
from .syllabus import syllabus_matches

log = logging.getLogger("stat350")


class SyllabusStore:
    def __init__(self, settings: Settings) -> None:
        cfg = settings.syllabi_store
        self.enabled: bool = bool(cfg.enabled and cfg.supabase_url)
        self.refresh_seconds: int = max(60, cfg.refresh_seconds)
        self._base = cfg.supabase_url.rstrip("/")
        self._bucket = cfg.bucket
        self._prefix = cfg.prefix if cfg.prefix.endswith("/") else cfg.prefix + "/"
        self._timeout = cfg.timeout_s
        self._max_files = cfg.max_files
        self._max_bytes = cfg.max_bytes
        self._cache_dir = settings.resolve_path(cfg.cache_dir)
        self._by_name: dict[str, str] = {}
        self._loaded_at: float = 0.0

    # -- public GETs (no auth; public bucket) ---------------------------------
    def _url(self, name: str) -> str:
        return f"{self._base}/storage/v1/object/public/{self._bucket}/{self._prefix}{quote(name)}"

    def _get(self, client: httpx.Client, name: str) -> Optional[str]:
        try:
            r = client.get(self._url(name))
        except Exception as exc:                                   # noqa: BLE001
            log.warning("syllabi: GET %s failed (%s)", name, type(exc).__name__)
            return None
        if r.status_code != 200:
            log.warning("syllabi: GET %s -> HTTP %s", name, r.status_code)
            return None
        return r.text

    def _manifest(self, client: httpx.Client) -> list[str]:
        raw = self._get(client, "index.json")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:                                          # noqa: BLE001
            log.warning("syllabi: index.json is not valid JSON")
            return []
        files = data.get("files") if isinstance(data, dict) else data
        out: list[str] = []
        for f in files or []:
            f = str(f)
            # only same-folder .md names — never a path or traversal
            if f.endswith(".md") and "/" not in f and ".." not in f and f not in out:
                out.append(f)
        return out[: self._max_files]

    # -- sync -----------------------------------------------------------------
    def refresh(self) -> int:
        """Re-sync from Supabase into cache + local fallback. NEVER raises; on
        any failure keeps the current cache. Returns the live file count."""
        if not self.enabled:
            return 0
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                names = self._manifest(client)
                if not names:
                    log.warning("syllabi: empty manifest — keeping %d cached",
                                len(self._by_name))
                    return len(self._by_name)
                fetched: dict[str, str] = {}
                for name in names:
                    text = self._get(client, name)
                    if text is None:
                        continue
                    if len(text.encode("utf-8", "ignore")) > self._max_bytes:
                        log.warning("syllabi: %s exceeds %d bytes — skipped",
                                    name, self._max_bytes)
                        continue
                    fetched[name] = text
            if fetched:
                self._by_name = fetched
                self._loaded_at = time.time()
                self._write_local(fetched)
                log.info("syllabi: synced %d files from Supabase", len(fetched))
        except Exception:                                          # noqa: BLE001
            log.exception("syllabi: refresh failed — keeping cache")
        return len(self._by_name)

    def maybe_refresh(self) -> None:
        if self.enabled and (time.time() - self._loaded_at) > self.refresh_seconds:
            self.refresh()

    # -- local fallback copy --------------------------------------------------
    def _write_local(self, files: dict[str, str]) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            for name, text in files.items():
                (self._cache_dir / name).write_text(text, encoding="utf-8")
        except Exception:                                          # noqa: BLE001
            log.warning("syllabi: could not write local cache")

    def load_local(self) -> int:
        """Populate from the local fallback copy (used at startup when Supabase
        is unreachable, so answers work immediately from last-known-good)."""
        try:
            if self._cache_dir.is_dir():
                for p in sorted(self._cache_dir.glob("*.md")):
                    self._by_name.setdefault(p.name, p.read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            log.warning("syllabi: could not read local cache")
        return len(self._by_name)

    # -- lookup ---------------------------------------------------------------
    def get(self, term: str, modality: str) -> Optional[tuple[str, str]]:
        """(filename, full markdown) for the current (term, modality), or None."""
        for name, text in self._by_name.items():
            if syllabus_matches(name, term, modality):
                return name, text
        return None

    def count(self) -> int:
        return len(self._by_name)
