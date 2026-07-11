# STAT 350 Tutor — Backend

Grounded course tutor over Purdue GenAI Studio. One streamed LLM call per
concept question, app-side retrieval over the existing knowledge collections
("STAT 350 Knowledge Base (SPRING 2026)" + "STAT 350 Transcripts"), real
citations, deterministic links from `data/course_map.json` (the model never
types URLs), honest refusals on weak retrieval, and a "dig deeper" agent
escalation. Full telemetry for improving the tool.

## Dev setup

```bash
python3 -m venv ~/venvs/stat350-tutor
~/venvs/stat350-tutor/bin/pip install fastapi 'uvicorn[standard]' 'sqlalchemy>=2' \
    alembic pydantic-settings itsdangerous pyyaml pytest pytest-asyncio httpx
~/venvs/stat350-tutor/bin/pip install -e ../../genai-studio-sdk   # local SDK checkout
# (production installs pin the SDK from git — see pyproject.toml)

cd backend
~/venvs/stat350-tutor/bin/python -m pytest tests/ -q     # 47 offline tests, no key needed
~/venvs/stat350-tutor/bin/uvicorn app.main:app --port 8100   # degraded without a key
```

Without `GENAI_STUDIO_API_KEY` the app runs **degraded**: deterministic
answers (worksheet/exam/syllabus lookups) work, concept questions return an
honest "gateway unavailable" with course links. The SPA is served from
`app_static/` (built by `cd ../frontend && npm run build`).

## Before first real deploy — Phase 0 probes

```bash
export GENAI_STUDIO_API_KEY=...   # GenAI Studio → Settings → Account → API Keys
~/venvs/stat350-tutor/bin/python scripts/probe_gateway.py
```

The probe report answers the nine unknowns the design flagged (retrieval
metadata shape, collection-ID resolution, single-call row order, distance
scale, query-rewriter availability, model TTFB + native tool calling, SSE
buffering, transcript naming, worksheets 14-22) and prints config changes.
Then calibrate retrieval thresholds properly:

```bash
~/venvs/stat350-tutor/bin/python -m app.eval run       # golden set → thresholds
```

## Operations

- `config.yaml` — all tunables. Secrets via env: `GENAI_STUDIO_API_KEY`,
  `STAT350_SECRET_KEY`, `ADMIN_TOKEN`, `EXPORT_SALT`.
- **Run exactly ONE uvicorn worker** (`ops/stat350-tutor.service`) — the SDK
  rate limiter is in-process and the gateway silently drops bursts.
- Nightly: `python -m app.jobs rollup && python -m app.jobs purge`
  (`ops/stat350-tutor-nightly.timer`); backups via `ops/backup.sh` (rehearse
  one restore!).
- Admin API under `/admin/api/*` (Bearer `ADMIN_TOKEN`); every GET takes
  `?format=csv` for direct `readr::read_csv()` use. Key views:
  `/admin/api/weak-retrievals` (= webbook content-gap backlog),
  `/admin/api/topics`, `/admin/api/feedback?status=open`,
  `/admin/api/messages/{id}/replay`.
- Semester export: `python -m app.export --from ... --to ... --out exports/x`
  (anonymized, R-friendly CSVs + README).
- Legacy `conversations.db`: scrub IPs before archiving —
  `python scripts/scrub_legacy_db.py path/to/conversations.db`.

## Architecture invariants (do not break)

1. The model **never** writes URLs; the app attaches links from
   `course_map.json` and `lint_links()` strips anything off-allowlist.
2. The student chat path **never awaits a DB write** — telemetry rides
   `Recorder.emit()` (single writer, strict FIFO; emission order must respect
   FK dependencies: user msg → retrieval → assistant msg → citations).
3. Everything outbound is paced by the **one** shared `RateLimiter`
   (`gateway.py`) — chat, retrieval, escalation. Never create a second client.
4. `citations`/`resources` SSE events are sent **before** `token`s;
   `done.finalText` (post-lint) is canonical and the SPA swaps it in.
5. Contract lives in `frontend/src/api/types.ts` — change it and the API
   schemas together.
