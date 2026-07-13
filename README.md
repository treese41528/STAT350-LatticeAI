# STAT 350 Tutor

A grounded AI tutor for **STAT 35000 – Introduction to Statistics** at Purdue.
It answers from the course's own materials — the webbook, lecture transcripts,
and syllabi that live in a Purdue GenAI Studio knowledge collection — and shows
its sources, so students get help that matches the course's notation, methods,
and policies instead of generic (and often wrong) statistics.

- **Backend:** FastAPI over the [`genai-studio-sdk`](https://github.com/treese41528/genai-studio-sdk),
  streaming SSE, SQLite/Postgres.
- **Frontend:** React + Vite single-page app (built to static files the backend serves).

> Replaces the earlier single-file Flask proxy (`genaiStudio_app_database.py`),
> which sent no system prompt, hid retrieval, and hallucinated. That app is kept
> only as an instant rollback until cutover.

## Why it's grounded (and doesn't hallucinate)

The old app forwarded chat to a GenAI Studio custom model and hoped for the
best. This one keeps grounding **in the app**, where it's observable and fixable:

```
student question
  → intent router (deterministic, no LLM)
      • worksheet / exam / syllabus-link lookups → answered from the course map, no LLM
      • concept question ↓
  → retrieve from the knowledge collections (webbook + transcripts) — a vector
    search, NOT an LLM call — returning ranked passages with similarity scores
  → weak retrieval? → honest refusal (skip the LLM entirely)
  → ONE streamed LLM call with a slim behavioral prompt + numbered passages;
    the model cites [n] and NEVER writes URLs
  → the APP attaches every link from course_map.json; any URL the model emits
    anyway is stripped
  → "Dig deeper" (optional) runs an SDK agent loop that can search, compute,
    and fetch course pages, then verifies before answering
```

The model cannot cite a source it wasn't given, and cannot invent a link.
Retrieval quality, refusals, and citations are all logged so the tool improves.

## Quick start

```bash
# 1. venv + deps. In DEV, install the backend's deps and the LOCAL SDK (editable)
#    — not `pip install -e backend`, which would pull the git-pinned SDK.
python3 -m venv ~/venvs/stat350-tutor
~/venvs/stat350-tutor/bin/pip install fastapi 'uvicorn[standard]' 'sqlalchemy>=2' \
    pydantic-settings itsdangerous pyyaml httpx pytest pytest-asyncio
~/venvs/stat350-tutor/bin/pip install -e ../genai-studio-sdk    # dev: local SDK checkout
cd frontend && npm ci && cd ..
# (Production/CI: `pip install -e backend` uses the pinned git SDK from pyproject.)

# 2. secrets — put them in a gitignored .env (see DEPLOY.md); real answers need
#    a gateway key, without it the app runs in degraded mode
export GENAI_STUDIO_API_KEY=sk-...        # GenAI Studio → Settings → Account → API Keys

# 3. run it
./run.sh dev            # hot reload: uvicorn :8100 + Vite :5173 (browse :5173)
./run.sh serve          # build the SPA + one uvicorn worker at :8100  (default)
./run.sh serve 9000     # ...on a port you choose  (also: --port 9000, or PORT=9000)
```

To ship it to students, see **[`DEPLOY.md`](./DEPLOY.md)** (Cloudflare Tunnel /
reverse proxy). Before trusting a fresh deployment, run the gateway probes and
evals — see [`TESTING.md`](./TESTING.md).

## Layout

```
STAT350-LatticeAI/
├── run.sh                     # start backend + frontend (dev | serve [PORT])
├── DEPLOY.md                  # production deploy (Cloudflare Tunnel / reverse proxy)
├── TESTING.md                 # the full test pyramid + semester-rollover guide
├── backend/                   # FastAPI app
│   ├── config.yaml            # all tunables (term, syllabus links, thresholds, limits)
│   ├── prompts/               # tutor_core.md (slim behavioral prompt) + escalation_agent.md
│   ├── data/                  # course_map.json, golden_*.yaml eval sets
│   ├── app/
│   │   ├── gateway.py         # ONE GenAIStudio client + ONE RateLimiter (whole process)
│   │   ├── grounding/         # router, retrieve, prompt_builder, citations, pipeline
│   │   ├── syllabus.py        # (term, modality) filename filter + per-term links
│   │   ├── escalation/        # the "dig deeper" SDK agent + course tools
│   │   ├── db/ · telemetry/    # schema + non-blocking recorder
│   │   └── api/               # chat (SSE), conversations, feedback, admin, meta
│   ├── scripts/               # probe_gateway, eval, export, maintenance, smoke_live
│   └── ops/                   # systemd units, timers, logrotate, backup.sh
├── frontend/                  # Vite + React + TS; builds into backend/app_static
└── genaiStudio_app_database.py, templates/, static/, deploy_database.sh
                               # the old Flask app — frozen, rollback only until
                               # cutover (then move under legacy/)
```

## Configuration

`backend/config.yaml` holds every non-secret tunable; secrets come from the
environment (`GENAI_STUDIO_API_KEY`, `STAT350_SECRET_KEY`, `ADMIN_TOKEN`,
`EXPORT_SALT`) — keep them in a gitignored `.env` (see [`DEPLOY.md`](./DEPLOY.md)),
never in a tracked file. Highlights:

- **`course.term`** — the current semester. Grounds syllabus answers; a startup
  warning fires if it looks stale. **Update it each semester.**
- **`course.syllabi`** — per-modality syllabus/schedule links for the current
  term. See [`TESTING.md` → semester rollover](./TESTING.md) for the 3-step
  process to add a new term.
- **`retrieval.thresholds`** — `strong` / `weak` similarity cutoffs, calibrated
  by `scripts/eval.py run` (this gateway returns *similarity* scores, higher =
  better).

## The SDK dependency

The backend rides the `genai-studio-sdk` (chat, streaming, retrieval, the agent
framework, and the shared rate limiter). Two install modes:

- **Development:** `pip install -e ../genai-studio-sdk` — an *editable* install of
  the sibling checkout, so `import genai_studio` resolves to your local SDK and
  picks up your edits live.
- **Production (pinned):** `backend/pyproject.toml` declares
  `genai-studio-sdk @ git+https://github.com/treese41528/genai-studio-sdk@v2.0.1`
  — the `v2.0.1` tag must exist on the remote.

Both are **v2.0.1**; keep them in sync (bump the pin and tag together). `/api/health`
reports the running app + SDK versions.

## Deployment

See **[`DEPLOY.md`](./DEPLOY.md)** for the step-by-step guide (Cloudflare Tunnel,
`.env` secrets, the streaming check, keeping it running). The essentials:

Run **exactly one uvicorn worker** — the SDK's rate limiter is in-process state
and the gateway silently drops bursts, so multiple workers would each pace
independently and lose requests (`run.sh serve` already enforces `--workers 1`).
`backend/ops/` has the systemd unit, nightly rollup/purge + backup timers, and
logrotate config. Terminate TLS and serve behind a tunnel or reverse proxy;
**disable response buffering for `/api/chat`** so SSE actually streams (verify
with `curl -N`). The database **self-heals additive schema on startup** — a new
nullable telemetry column is added automatically, no manual migration.

## Data collection & privacy

Every question logs its retrieval (query, chunks, scores), the citations the
answer used, feedback, and usage — the dataset for improving the tool
(`/admin/api/weak-retrievals` is the webbook content-gap backlog). The student
chat path **never awaits a DB write** (a background recorder handles it). **No IP
addresses** are stored; students are anonymous device IDs now, with a
Purdue-CAS seam for later. Exports are pseudonymized and content-free by default.

## Versions

| Component | Version |
|---|---|
| Backend app (`app.__version__`, `pyproject`) | 0.1.0 |
| Frontend (`package.json`) | 0.1.0 |
| `genai-studio-sdk` (pinned + installed) | 2.0.1 |

## Testing

See [`TESTING.md`](./TESTING.md) — unit (backend 87, frontend 65), a real-browser
frontend smoke, gateway probes, retrieval evals **plus an LLM-judge answer eval**
(`scripts/eval.py judge` grades generated answers on a six-dimension rubric), and
a full-backend live smoke.
