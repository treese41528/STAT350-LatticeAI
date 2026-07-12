"""Bring-your-own-key: let a student use their OWN GenAI Studio API key so they
get their own ~20 RPM budget instead of competing for the shared class key.

SECURITY CONTRACT — the student's key is a credential to their Purdue account:
- It lives only in the browser and TRANSIENTLY in server RAM (inside a per-key
  Gateway's studio client). It is NEVER written to the database, telemetry,
  logs, traces, or error details.
- The pool caches per-key Gateways by a SHA-256 hash of the key (so the cache
  key isn't the secret), bounded by an LRU cap.
- `redact()` scrubs a key out of any string before it could be logged.

Collection access: a student's key can query the professor's knowledge
collection only if that collection is shared to them in Open WebUI. `validate()`
checks this explicitly (auth AND a real retrieval), so the UI can refuse to
enable BYO when it wouldn't actually work.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

from .config import Settings
from .gateway import Gateway

# Open WebUI keys look like "sk-..."; be lenient but reject obvious junk /
# anything with whitespace or control chars (which can't be a real bearer token).
_KEY_RE = re.compile(r"^[A-Za-z0-9._\-]{20,400}$")


def valid_key_format(key: str | None) -> bool:
    return bool(key) and bool(_KEY_RE.match(key.strip()))


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def redact(text: str, key: str | None) -> str:
    """Remove a key (and its hash) from a string before logging."""
    if not text:
        return text
    if key and key in text:
        text = text.replace(key, "«redacted-key»")
    return text


@dataclass(frozen=True)
class KeyVerdict:
    auth_ok: bool
    retrieval_ok: bool
    message: str


class GatewayPool:
    """LRU cache of per-key Gateways (each with its own rate limiter)."""

    def __init__(self, settings: Settings, shared: Gateway, max_size: int = 300):
        self._settings = settings
        self._shared = shared
        self._max = max_size
        self._cache: "OrderedDict[str, Gateway]" = OrderedDict()
        self._lock = threading.Lock()

    def for_key(self, key: str) -> Gateway:
        """A Gateway bound to `key`, reusing the shared collection IDs."""
        h = key_hash(key)
        with self._lock:
            gw = self._cache.get(h)
            if gw is None:
                gw = Gateway.for_key(self._settings, key, self._shared.kb_ids)
                self._cache[h] = gw
            self._cache.move_to_end(h)
            while len(self._cache) > self._max:
                self._cache.popitem(last=False)
            return gw

    def validate(self, key: str) -> KeyVerdict:
        """Check that a key (a) authenticates and (b) can actually retrieve from
        the shared collection. Never stores or logs the key."""
        if not valid_key_format(key):
            return KeyVerdict(False, False,
                              "That doesn't look like a valid API key.")
        gw = self.for_key(key)
        # (a) auth — a cheap call that fails on a bad key
        try:
            gw.studio.health_check()
        except Exception as exc:
            return KeyVerdict(False, False,
                              f"Key rejected by the gateway ({type(exc).__name__}).")
        # (b) retrieval — can THIS key see the course collection?
        web = self._shared.kb_ids.get("webbook")
        if not web:
            return KeyVerdict(True, False,
                              "Key works, but the course collection isn't "
                              "resolved on the server yet — try again shortly.")
        try:
            payload = gw.retrieval_query("central limit theorem", [web], k=1)
            docs = payload.get("documents") or []
            flat = docs[0] if docs and isinstance(docs[0], list) else docs
            if flat:
                return KeyVerdict(True, True,
                                  "Your key is active — you now have your own "
                                  "request budget.")
            return KeyVerdict(True, False,
                              "Your key works, but it can't read the STAT 350 "
                              "course materials (the collection isn't shared with "
                              "your account). Using the shared class key instead.")
        except Exception:
            return KeyVerdict(True, False,
                              "Your key works, but couldn't query the course "
                              "materials. Using the shared class key instead.")
