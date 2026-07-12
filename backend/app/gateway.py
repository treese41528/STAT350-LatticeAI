"""The single seam to Purdue GenAI Studio.

ONE `GenAIStudio` client and ONE `RateLimiter` for the entire process — the
gateway (~20 RPM) silently drops bursts instead of returning 429s, so every
outbound call (chat, retrieval, escalation agents) must be paced by the same
limiter. This is also why the app runs with exactly one uvicorn worker.

All methods here are synchronous (the SDK is sync); callers bridge with
`app.concurrency.run_sync` / `aiter_sync`.
"""

from __future__ import annotations

import logging
from typing import Iterator

from genai_studio import GenAIStudio
from genai_studio.agents.client import RateLimiter

from .config import Settings

logger = logging.getLogger(__name__)

RETRIEVAL_ENDPOINT = "/api/v1/retrieval/query/collection"


class GatewayError(RuntimeError):
    pass


class Gateway:
    def __init__(self, settings: Settings, *, api_key: str | None = None,
                 kb_ids: dict[str, str] | None = None, label: str = "shared"):
        self.settings = settings
        # per-instance limiter: each API key is its own ~20 RPM bucket, so a
        # student's own key gets an independent budget from the shared one.
        self.limiter = RateLimiter(rpm=settings.gateway.rpm)
        self._studio: GenAIStudio | None = None
        # `api_key` overrides settings.api_key (bring-your-own-key gateways).
        self._api_key = api_key
        self.label = label  # "shared" | "byok" — never the key itself
        # display name -> knowledge-base id, filled by resolve_collections()
        # (per-key gateways reuse the shared IDs — collections are the owner's).
        self.kb_ids: dict[str, str] = dict(kb_ids) if kb_ids else {}

    @classmethod
    def for_key(cls, settings: Settings, api_key: str,
                kb_ids: dict[str, str]) -> "Gateway":
        return cls(settings, api_key=api_key, kb_ids=kb_ids, label="byok")

    @property
    def studio(self) -> GenAIStudio:
        """Lazy so the app can boot (degraded) without an API key in dev."""
        if self._studio is None:
            key = self._api_key or self.settings.api_key
            if not key:
                raise GatewayError(
                    "GENAI_STUDIO_API_KEY is not set — gateway unavailable.")
            self._studio = GenAIStudio(
                api_key=key,
                base_url=self.settings.gateway.base_url,
                timeout=self.settings.gateway.timeout_s,
                connect_timeout=self.settings.gateway.connect_timeout_s,
                validate_model=False,  # don't block startup on a models fetch
            )
        return self._studio

    # ---- startup -----------------------------------------------------------

    def resolve_collections(self) -> dict[str, str]:
        """Resolve configured collection display names to knowledge-base IDs.

        The retrieval endpoint takes IDs (UUIDs), not display names.
        """
        wanted = {
            "webbook": self.settings.collections.webbook,
            "transcripts": self.settings.collections.transcripts,
        }
        by_name = {kb.name: kb.id for kb in self.studio.list_knowledge_bases()}
        resolved: dict[str, str] = {}
        for key, name in wanted.items():
            if name not in by_name:
                raise GatewayError(
                    f"Knowledge collection {name!r} not found on the gateway. "
                    f"Available: {sorted(by_name)}"
                )
            resolved[key] = by_name[name]
        self.kb_ids = resolved
        logger.info("Resolved knowledge collections: %s", resolved)
        return resolved

    # ---- retrieval (no LLM call) --------------------------------------------

    def retrieval_query(self, query: str, collection_ids: list[str], k: int,
                        hybrid: bool = False) -> dict:
        """POST the gateway's vector-search endpoint; returns the raw payload.

        Called once per collection so passages stay labeled by origin (the
        SDK's kb_search tool flattens rows and loses that)."""
        self.limiter.acquire()
        body = {"collection_names": collection_ids, "query": query,
                "k": k, "hybrid": hybrid}
        resp = self.studio._http_post(RETRIEVAL_ENDPOINT, json=body)
        return resp.json()

    # ---- chat ---------------------------------------------------------------

    def stream_chat(self, messages: list[dict], *, temperature: float | None = None,
                    max_tokens: int | None = None) -> Iterator[str]:
        """Stream token deltas for a fully-assembled messages array."""
        gen = self.settings.generation
        self.limiter.acquire()
        return self.studio.chat_messages(
            messages,
            model=self.settings.gateway.model,
            stream=True,
            temperature=gen.temperature if temperature is None else temperature,
            max_tokens=gen.max_tokens if max_tokens is None else max_tokens,
        )

    # ---- health --------------------------------------------------------------

    def health(self) -> dict:
        try:
            return self.studio.health_check()
        except Exception as exc:  # health must never raise
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
