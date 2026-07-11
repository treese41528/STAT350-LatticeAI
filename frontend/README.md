# STAT 350 Tutor — Frontend

React SPA for the STAT 350 Socratic tutor. Vite 7 + React 19 + TypeScript,
zustand for state, CSS Modules with Purdue design tokens, react-markdown +
KaTeX for math-heavy answers, hand-rolled SSE-over-POST streaming client.

## Development

```bash
npm install --no-audit --no-fund

# Standalone demo mode (DEFAULT) — no backend required.
# A Vite dev plugin (mock/plugin.ts) fakes the whole /api surface and streams
# a canned SSE answer (citations, resources, KaTeX t-test walkthrough, an R
# code block, [1][2] markers, queue + status events, a refusal path if you
# ask for an "answer key", and the Dig Deeper flow).
npm run dev

# Against the real backend (proxies /api -> http://localhost:8100):
npm run dev:backend
```

Mock mode is enabled by `--mode mock` (what `npm run dev` uses) or by setting
`VITE_MOCK=1`.

## Checks

```bash
npm run typecheck   # tsc --noEmit
npm test            # vitest run
```

## Build

```bash
npm run build
```

The build typechecks, then emits into **`../backend/app_static/`**
(`emptyOutDir: true` — the directory is wiped and rewritten). The FastAPI
backend serves that directory as the SPA. Workflow: build here, then commit
the regenerated `backend/app_static` together with any frontend source
changes so the served bundle never drifts from the source.

KaTeX CSS/fonts and Shiki grammars are self-hosted via npm packages — no CDN
at runtime. Shiki loads lazily on the first R code fence only.

## API contract

`src/api/types.ts` is the **single source of truth** shared with the backend;
the backend's Pydantic schemas are generated/written against it. If you touch
it, the backend schemas must change in the same commit (and vice versa). The
SSE event order per answer is:

```
meta -> queue* -> status* -> citations -> resources -> token* -> (refusal) -> done | error
```

`done.finalText`, when present, is canonical (post link-lint) and replaces
the streamed text in the store.

## Identity

An anonymous device id (`localStorage["stat350.device"]`) is attached to every
request as `X-Device-Id` by `src/api/http.ts#apiFetch` (plus cookies via
`credentials: "include"`). Components never touch identity — when Purdue CAS
arrives, `src/lib/identity.ts` + `apiFetch` are the only swap points.

## Invariants worth knowing

- **No `rehype-raw`.** Raw HTML in model/retrieval output stays dropped
  (react-markdown default). KaTeX runs with `trust: false`,
  `throwOnError: false`, `strict: "ignore"`. See
  `src/components/markdown/MessageMarkdown.tsx`.
- Streaming markdown is split by `src/lib/streamingMarkdown.ts#splitStable`
  so KaTeX/fences never see partial constructs; the in-flight tail renders as
  dimmed plain text.
- Token deltas buffer outside React and flush at most every ~50ms (rAF), so
  only the streaming bubble re-renders.
- Feedback tag ids (`src/components/feedback/tags.ts`) are part of the API
  contract.
