# Running & testing the STAT 350 Tutor

## Start it (dev or prod-like)

```bash
./run.sh dev      # hot reload: uvicorn :8100 + Vite :5173 (proxies /api). Browse :5173.
./run.sh serve    # build SPA + one uvicorn worker serving app+API at :8100. (default)
# GENAI_STUDIO_API_KEY for real answers; without it, degraded (deterministic) mode.
```

## Rolling over to a new semester (syllabus grounding)

Syllabus answers are grounded in **`config.course.term`** + the student's section.
How the pieces fit:

- **Which syllabus to QUOTE** — `app/syllabus.py` filters retrieved passages by
  *filename*: it keeps a passage only if its source filename contains the term's
  season + year AND a token for the student's modality (`flipped`, `in-person`,
  `online`, `winter`, `summer`). This is **substring/token matching, not fuzzy
  edit-distance**, so it's robust to naming variants (`Syllabus_SPRING_2026_Flipped.md`,
  `SyllabusSPRING_2026_In-Person.md`, `STAT_350_SUMMER_2026_Syllabus.md` all work).
  If no current-term/section passage is found, the tutor **links the official PDF
  instead of quoting a wrong term** — it never guesses.
- **Which PDF/schedule to LINK** — from `config.course.syllabi` (per modality),
  NOT baked into the code. Config wins; a modality omitted there falls back to
  `course_map.json`.

**To add a new term (e.g. FALL 2026):**
1. Upload the new syllabi to the knowledge collection, named with the season,
   year, and modality (e.g. `Syllabus_FALL_2026_Flipped.md`).
2. In `backend/config.yaml`: set `course.term: "FALL 2026"` and update the
   `course.syllabi.<modality>.syllabus_pdf` / `schedule_url` links to the new
   term's files.
3. `python backend/scripts/probe_gateway.py` — probe #10 reports whether the
   **current term's** syllabus is retrievable for each modality (confirms the KB
   upload + filename are recognized).

A new *modality* (e.g. an evening section) also needs a one-line entry added to
`MODALITY_TOKENS` in `app/syllabus.py`. A startup warning fires if `course.term`
looks stale for today's date.

# Testing the full build

The test pyramid, from "no key needed" to "full stack against the real gateway".
All commands assume the project venv at `~/venvs/stat350-tutor` (the `scripts/*.py`
helpers auto-select it; `-m` and `pytest` need it active or use the full path).

## 0. One-time setup

```bash
python3 -m venv ~/venvs/stat350-tutor
~/venvs/stat350-tutor/bin/pip install fastapi 'uvicorn[standard]' 'sqlalchemy>=2' \
    alembic pydantic-settings itsdangerous pyyaml pytest pytest-asyncio httpx
~/venvs/stat350-tutor/bin/pip install -e ../genai-studio-sdk   # or the pinned git tag
cd frontend && npm ci && cd ..
```

## 1. Unit tests — NO key, fast (run on every change)

```bash
# backend: 66 tests (mocked gateway) — router, retrieval tiering, term/modality
# syllabus grounding, citations/link-lint, SSE contract, identity, telemetry…
cd backend && ~/venvs/stat350-tutor/bin/python -m pytest tests/ -q

# frontend: 61 tests (jsdom) — SSE reducer, streaming-safe markdown, KaTeX
# rendering (inline+display), citation/resource hrefs, security invariants
cd frontend && npx vitest run
```

## 2. Frontend visual/interaction — NO key (real browser, mock backend)

```bash
cd frontend
npx playwright install chromium      # one-time (~130 MB, into ~/.cache)
node e2e-smoke.mjs                    # drives the built app in mock mode
# 10/10 checks: formulas render, citation popover + link, resource cards, R
# code, dark mode, no JS errors. Screenshots in the scratchpad dir.
```

## 3. Degraded backend — NO key (deterministic paths only)

```bash
cd backend && ~/venvs/stat350-tutor/bin/uvicorn app.main:app --port 8100
# In another shell — these work WITHOUT the gateway:
curl -s localhost:8100/api/config
curl -sN -X POST localhost:8100/api/chat -H 'X-Device-Id: 00000000-0000-0000-0000-000000000001' \
     -H 'Content-Type: application/json' -d '{"message":"link to worksheet 5"}'
# Concept/syllabus-content questions return a friendly "gateway unavailable".
```

## 4. Gateway probes — KEY REQUIRED (run once before trusting config)

```bash
export GENAI_STUDIO_API_KEY=...      # GenAI Studio → Settings → Account → API Keys
python backend/scripts/probe_gateway.py
# Confirms: collection IDs, chunk-filename → URL join, SIMILARITY direction,
# distance scale, syllabus indexing + modality naming (probe #10), model TTFB,
# native tool-calling, SSE-buffering reminder. Prints suggested config changes.
```

## 5. Retrieval quality — KEY REQUIRED (paced ~3s/question)

```bash
python backend/scripts/eval.py run                                  # 345 webbook Qs (~15 min)
python backend/scripts/eval.py run --golden data/golden_syllabus.yaml   # 27 syllabus Qs
# Reports hit@k, per-chapter, by-difficulty, out-of-scope refusal-accuracy, and
# a threshold suggestion. Stores an eval_runs row (trend baseline).
python backend/scripts/eval.py replay --since 2026-08-01            # regression gate after re-index
```

## 6. Full backend end-to-end — KEY REQUIRED

```bash
export GENAI_STUDIO_API_KEY=...
python backend/scripts/smoke_live.py
# Runs the REAL pipeline through the app: concept question (citations + [n] +
# course URLs, no linted URLs), syllabus question (term+modality grounded quote
# + PDF link), out-of-scope (BEYOND/refusal), and dig-deeper escalation.
```

## 7. Full STACK — KEY REQUIRED (browser → backend → gateway)

```bash
# build the SPA into the backend's static dir, run one uvicorn worker, open it
cd frontend && npm run build && cd ..
cd backend && ~/venvs/stat350-tutor/bin/uvicorn app.main:app --port 8100
# browse http://localhost:8100 and ask:
#   - a concept question  → streamed answer, [n] chips, resource cards, KaTeX
#   - "how much is homework worth?" → set your section, get the quoted % + link
#   - an out-of-scope question → BEYOND banner / redirect
#   - "Dig deeper" on an answer → staged progress, then a sourced answer
# For an automated full-stack browser pass, run `npm run dev:backend` (proxies
# /api → :8100) and point e2e-smoke.mjs's URL at that dev server.
```

### Deploy gate before a student pilot
- probe (§4) fully green; eval (§5) hit@k ≥ ~0.85 and syllabus quotes are
  term/modality-correct; smoke (§6) all checks; a full-stack manual pass (§7).
- Confirm SSE isn't proxy-buffered: `curl -N` a chat request through the real
  reverse proxy and verify tokens arrive incrementally.
- Set `course.term` in `config.yaml` for the CURRENT semester (a startup warning
  fires if it looks stale) so syllabus answers ground in the right point spread.
