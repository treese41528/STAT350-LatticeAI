"""Configuration: config.yaml (non-secrets) + environment (secrets).

Everything the app reads at runtime hangs off one `Settings` object built by
`load_settings()`. The YAML file is the single source for tunables; env vars
carry only secrets and deploy-time overrides (STAT350_CONFIG, STAT350_DB_URL).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

BACKEND_DIR = Path(__file__).resolve().parent.parent


class SyllabusLinkCfg(BaseModel):
    label: str = ""
    syllabus_pdf: str = ""
    schedule_url: str = ""


class CourseCfg(BaseModel):
    name: str = "STAT 350"
    term: str = ""
    # When true, the current term is derived from today's date (no per-semester
    # edit). `term` above is then only a fallback/label. Leave false to pin the
    # term explicitly (a startup warning fires if it looks stale).
    auto_term: bool = False
    welcome: str = ""
    starter_questions: list[str] = Field(default_factory=list)
    max_message_chars: int = 4000
    # Per-term syllabus + schedule links, keyed by modality. Update these + the
    # `term` field each semester — nothing else changes. A modality absent here
    # falls back to course_map.json.
    syllabi: dict[str, SyllabusLinkCfg] = Field(default_factory=dict)


class GatewayCfg(BaseModel):
    base_url: str = "https://genai.rcac.purdue.edu"
    model: str = "gpt-oss:120b"
    rpm: int = 18
    timeout_s: int = 120
    connect_timeout_s: int = 30
    max_concurrent_llm: int = 4


class CollectionsCfg(BaseModel):
    webbook: str
    transcripts: str


class ThresholdsCfg(BaseModel):
    # Interpreted per RetrievalCfg.higher_is_better. With higher_is_better
    # (this gateway): best score >= strong -> answer; best < weak -> refuse.
    strong: float = 0.75
    weak: float = 0.66


class RetrievalCfg(BaseModel):
    k_webbook: int = 6
    k_transcripts: int = 4
    max_passages: int = 8
    min_transcript_slots: int = 2
    rewriter: str = "heuristic"
    single_call: bool = False
    # Phase 0 probe #4: this gateway's retrieval "distances" are actually
    # similarity scores (higher = more relevant). Flip if a re-index switches
    # to a true-distance metric.
    higher_is_better: bool = True
    thresholds: ThresholdsCfg = ThresholdsCfg()


class GenerationCfg(BaseModel):
    temperature: float = 0.2
    max_tokens: int = 1600
    history_window: int = 10


class EscalationCfg(BaseModel):
    enabled: bool = True
    model: str = ""
    temperature: float = 0.0
    max_steps: int = 6
    max_tool_calls: int = 8
    max_tokens: int = 24000
    timeout_s: int = 120
    per_user_per_hour: int = 3


class LimitsCfg(BaseModel):
    user_per_min: int = 6
    user_per_day: int = 60
    burst_per_10min: int = 10


class DegradationCfg(BaseModel):
    disable_escalation_at: int = 5
    shrink_retrieval_at: int = 12
    reject_at: int = 25


class DbCfg(BaseModel):
    url: str = "sqlite:///data/tutor.db"
    retention_days: int = 400


class LoggingCfg(BaseModel):
    dir: str = "logs"
    chat_traces: bool = True
    agent_traces: bool = True


class AdminCfg(BaseModel):
    enabled: bool = True


class ByokCfg(BaseModel):
    # Let students supply their own GenAI Studio key for their own RPM budget.
    enabled: bool = True
    # "own": the student key does retrieval + chat + escalation (needs the
    # collection shared to students). "shared": retrieval stays on the class
    # key, only the chat/escalation LLM call uses the student key (works even
    # if the collection is private, but retrieval still spends the shared RPM).
    retrieval: str = "own"


class SyllabiStoreCfg(BaseModel):
    # Serve full (term, modality) syllabus text from Supabase Storage so policy
    # questions always answer, and so syllabi can be edited each term WITHOUT
    # redeploying. All reads are public GETs (no key needed).
    enabled: bool = False
    supabase_url: str = ""             # https://<ref>.supabase.co  (non-secret)
    bucket: str = "stat-350-assets"
    prefix: str = "syllabi/"
    refresh_seconds: int = 900         # background re-sync cadence
    timeout_s: int = 15
    max_files: int = 50
    max_bytes: int = 512_000           # skip absurdly large files (~500 KB)
    cache_dir: str = "data/syllabi_cache"


class Settings(BaseModel):
    course: CourseCfg = CourseCfg()
    gateway: GatewayCfg = GatewayCfg()
    collections: CollectionsCfg
    retrieval: RetrievalCfg = RetrievalCfg()
    generation: GenerationCfg = GenerationCfg()
    escalation: EscalationCfg = EscalationCfg()
    limits: LimitsCfg = LimitsCfg()
    degradation: DegradationCfg = DegradationCfg()
    db: DbCfg = DbCfg()
    logging: LoggingCfg = LoggingCfg()
    admin: AdminCfg = AdminCfg()
    byok: ByokCfg = ByokCfg()
    syllabi_store: SyllabiStoreCfg = SyllabiStoreCfg()

    # --- secrets / env-only ---
    api_key: str | None = None          # GENAI_STUDIO_API_KEY
    secret_key: str = "dev-secret-change-me"   # STAT350_SECRET_KEY
    admin_token: str | None = None      # ADMIN_TOKEN
    export_salt: str = "dev-salt"       # EXPORT_SALT

    @property
    def backend_dir(self) -> Path:
        return BACKEND_DIR

    def resolve_path(self, rel: str) -> Path:
        """Resolve a config-relative path against the backend directory."""
        p = Path(rel)
        return p if p.is_absolute() else BACKEND_DIR / p


def load_settings(config_file: str | os.PathLike | None = None) -> Settings:
    path = Path(config_file or os.environ.get("STAT350_CONFIG", BACKEND_DIR / "config.yaml"))
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = Settings(**raw)

    settings.api_key = os.environ.get("GENAI_STUDIO_API_KEY") or None
    settings.secret_key = os.environ.get("STAT350_SECRET_KEY", settings.secret_key)
    settings.admin_token = os.environ.get("ADMIN_TOKEN") or None
    settings.export_salt = os.environ.get("EXPORT_SALT", settings.export_salt)
    if os.environ.get("STAT350_DB_URL"):
        settings.db.url = os.environ["STAT350_DB_URL"]
    return settings
