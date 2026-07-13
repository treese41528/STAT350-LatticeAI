# Deploying the STAT 350 Tutor

The whole app is **one process**: a single Uvicorn worker that serves the built
SPA *and* the API from one origin (default `http://127.0.0.1:8100`). You expose
that one port to students — the simplest way is a **Cloudflare Tunnel** from the
machine that runs it (a lab box, or your own machine in `tmux`). No separate
frontend host, no database server.

> **Never commit secrets.** Put every key in a `.env` file (already gitignored,
> alongside `config.yaml`). The commands below use placeholders like
> `sk-xxxxxxxx` — replace them with your real values, and keep those values out
> of tracked files, chat, and screenshots.

---

## 1. Prerequisites (one time)

```bash
# Python venv + backend deps + the SDK (see README for dev-vs-pinned install)
python3 -m venv ~/venvs/stat350-tutor
~/venvs/stat350-tutor/bin/pip install fastapi 'uvicorn[standard]' 'sqlalchemy>=2' \
    pydantic-settings itsdangerous pyyaml httpx
~/venvs/stat350-tutor/bin/pip install -e ../genai-studio-sdk   # or the pinned git SDK

# Node is needed only to BUILD the SPA (run.sh serve does this for you)
cd frontend && npm ci && cd ..

# cloudflared, if you don't have it (https://developers.cloudflare.com/cloudflare-one/)
```

## 2. Secrets — put them in `.env` (gitignored)

Create `./.env` (repo root) — it is already in `.gitignore`, so it is never
committed:

```bash
# .env  — real values here, NEVER in a tracked file
GENAI_STUDIO_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx   # GenAI Studio → Settings → Account → API Keys
STAT350_SECRET_KEY=<random-64-hex>                 # signs the device cookie — see below
ADMIN_TOKEN=<random>                               # only if you use the /admin dashboard
EXPORT_SALT=<random>                               # only needed before exporting data
```

- **`GENAI_STUDIO_API_KEY`** — required for real answers. Without it the app runs
  in *degraded mode* (deterministic lookups work; concept/syllabus questions
  return "gateway unavailable"). This is the class key that all students share
  (~20 requests/min) unless BYOK is enabled.
- **`STAT350_SECRET_KEY`** — **set this in production.** It signs the anonymous
  device-identity cookie; the built-in default is a *known* value, so leaving it
  unset lets identities be forged. Generate one:
  ```bash
  echo "STAT350_SECRET_KEY=$(openssl rand -hex 32)" >> .env
  ```
- **`ADMIN_TOKEN`** — Bearer token for `/admin/api/*` (the weak-retrieval backlog,
  feedback triage, CSV exports). Omit to leave the dashboard disabled.
- **`EXPORT_SALT`** — pseudonymizes semester exports; only matters when you run
  `scripts/export.py`.

Load it before starting (or let your process manager load it):

```bash
set -a; source .env; set +a
```

## 3. Start the server

```bash
./run.sh serve            # build the SPA + ONE uvicorn worker on :8100 (default)
./run.sh serve 9000       # ...on port 9000 (positional)
./run.sh serve --port 9000
PORT=9000 ./run.sh serve  # or via env; an argument overrides it
```

`run.sh serve` rebuilds the frontend each time, so it always serves the current
SPA. It binds to `127.0.0.1` — fine when `cloudflared` runs on the same machine
(and it keeps the app off the open internet). If your tunnel/proxy is on a
*different* host, run behind that host's private network, not `0.0.0.0`.

> **THE ONE HARD RULE — exactly one worker.** `run.sh` already passes
> `--workers 1`. Do **not** add workers or run a second copy: the ~18 req/min
> rate limiter is in-process, so multiple workers would each pace independently
> and the gateway would silently drop the excess.

## 4. Expose it with a Cloudflare Tunnel

Point `cloudflared` at the port from step 3 — the same way the old app was
exposed, just the new target:

```bash
# quick tunnel (ephemeral *.trycloudflare.com URL — good for a pilot)
cloudflared tunnel --url http://localhost:8100

# or a named tunnel with a stable hostname (free Cloudflare account + your domain)
cloudflared tunnel run stat350-tutor        # after `cloudflared tunnel create` + DNS route
```

Give students the resulting `https://…` URL. That's it — the SPA and API are the
same origin, so there's nothing else to host.

*(Alternative without Cloudflare: any reverse proxy — Nginx/Caddy — terminating
TLS and proxying to `127.0.0.1:8100`. **Disable response buffering for
`/api/chat`** so SSE streams; the app already sends `X-Accel-Buffering: no`.)*

## 5. Verify streaming works through the tunnel (do this once)

Answers stream token-by-token over Server-Sent Events — new behavior vs. the old
app, so confirm the tunnel doesn't buffer or time it out:

```bash
curl -N -H "Content-Type: application/json" \
  -H "X-Device-Id: 11111111-1111-1111-1111-111111111111" \
  -d '{"conversationId":null,"message":"Explain the Central Limit Theorem"}' \
  https://YOUR-TUNNEL-URL/api/chat
```

You should see `event: token` lines appear **progressively**, not all at once
(all-at-once = buffering). The app sends a `: ping` heartbeat every 15s, which
keeps Cloudflare's ~100s connection limit from cutting a stream; a "Dig deeper"
run can take ~120s, so confirm that finishes too. Then open the site in a browser
and ask a real question end-to-end.

## 6. Keep it running

- **Simple:** run `./run.sh serve` inside `tmux` or `screen` (and `cloudflared`
  in another) so it survives your SSH session. The SQLite DB lives on local disk;
  the tunnel is up only while both processes are.
- **Headless / survives reboots:** `backend/ops/stat350-tutor.service` (systemd)
  plus the nightly rollup/purge and backup timers. Point the unit's
  `EnvironmentFile` at your `.env`.

## 7. Backups & maintenance

```bash
backend/ops/backup.sh                         # snapshot the SQLite DB (rehearse a RESTORE once!)
python backend/scripts/maintenance.py rollup  # nightly anonymous daily_stats
python backend/scripts/maintenance.py purge   # drop rows past the retention window
```

The `ops/` timers automate the nightly jobs. **Rehearse restoring a backup**
before you rely on it.

## 8. Redeploying a new version

```bash
git pull
cd frontend && npm ci && cd ..     # only if frontend deps changed
./run.sh serve                     # rebuilds the SPA; restart the service if using systemd
```

The database **self-heals on startup**: any new (nullable) telemetry column the
models gained is added automatically — no manual migration for additive changes.

## 9. Rollback

The old single-file Flask app (`genaiStudio_app_database.py` + `deploy_database.sh`)
is kept as a one-command rollback until cutover — start it and re-point the
tunnel at its port if you ever need to revert.

---

### Pre-flight checklist

- [ ] `.env` created with a **real** `GENAI_STUDIO_API_KEY` and a **random**
      `STAT350_SECRET_KEY` (and it's gitignored — `git status` shows nothing).
- [ ] `backend/config.yaml`: `course.term` and `collections.webbook` are current.
- [ ] `python backend/scripts/smoke_live.py` passes (health, a grounded answer,
      citations, no leaked URLs).
- [ ] Streaming verified through the public tunnel URL (§5).
- [ ] Exactly **one** worker; the machine + `cloudflared` stay up.
