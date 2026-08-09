# CapCode — PRD

## What it is
CapCode is a recursive bot-builder. Human types the app they want; the system runs **Teacher → Artist → Product → Rater**, delivering a runnable downloadable code folder. Dark 1980s neo-noir BBS aesthetic. Not a Cursor/v0 competitor — CapCode strictly generates a fresh runnable project, not IDE assistance.

## Strict topology (do not deviate)
1. Human types the app they want built.
2. **TEACHER** bot (rigid, strict) reads the target + top-verified prior chains and writes a brief for the Artist. Default: OpenRouter `deepseek/deepseek-v4-flash`.
3. **ARTIST** bot (creative, novel) — **writes the actual source files** as a `files: [{path, content}]` array. Default: OpenRouter `anthropic/claude-sonnet-5`. Auto-retries once with terser directive if the first response is truncated/unparseable.
4. **Product** is materialized to `/workspaces/<chain>/<name>/`.
5. **Executor** runs `bash run.sh` in an isolated process group (soon: Vercel Sandbox API).
6. If the app fails to start, **one** correction pass runs.
7. **RATER** scores. Composite score = weighted sum.
8. Human clicks **✓ Works — Verify** on a completed chain → +0.5 composite boost + fed into the Teacher exemplar pool.

## Tech stack (2026-08-09 — after migration)
- **Frontend**: React (CRA), Tailwind, Shadcn UI, better-auth React SDK
- **Backend**: FastAPI, asyncpg, PyJWT (EdDSA)
- **Database**: **Neon Postgres** (via a home-grown `docdb.py` adapter that mimics a small Mongo subset over JSONB)
- **Auth**: **Neon Managed Better Auth** (Google OAuth via Neon "Shared keys" + email/password), JWT verified against `${NEON_AUTH_URL}/.well-known/jwks.json`
- **LLMs**: OpenRouter (default), NVIDIA NIM, Venice — all BYOK
- **Deploy target**: Vercel (upcoming — needs Vercel Sandbox executor rewrite + `vercel.json`)

## Architecture files
- `/app/backend/server.py` — FastAPI routes (owner-filtered) + Neon JWT verification.
- `/app/backend/docdb.py` — Postgres/JSONB Mongo-compat adapter (find/insert/update_one/update_many/count_documents/$set/$push/upserts).
- `/app/backend/chain_generator.py` — Teacher / Artist / Corrector / Rater LLM orchestration + SSE streaming.
- `/app/backend/executor.py` — subprocess spawn with `os.setsid()` + env whitelist scrub (SEC-001).
- `/app/backend/seed_template.py` — fills gaps in Artist's file set (run.sh, package.json, etc.).
- `/app/backend/providers.py` — OpenRouter / NVIDIA / Venice OpenAI-compatible clients.
- `/app/frontend/src/App.js` — main orchestration, SSE tokens, Neon Auth session watcher.
- `/app/frontend/src/lib/authClient.js` — better-auth React client + `getJwt()` for backend calls.
- `/app/frontend/src/lib/api.js` — axios with global JWT bearer + `X-Capcode-Session` interceptor.
- `/app/frontend/src/components/ChainViewer.jsx` — lineage + terminal + download/verify/push buttons.
- `/app/frontend/src/components/SettingsPanel.jsx` — role/model picker + BYOK keys.

## Environment variables
### Backend (`/app/backend/.env`)
- `POSTGRES_URL` — Neon connection string.
- `NEON_AUTH_URL` — `https://<endpoint>.neonauth.<region>.aws.neon.tech/<branch>/auth`.
- `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `VENICE_API_KEY` — server-default LLM keys.
- `CORS_ORIGINS` — comma-list or `*`.

### Frontend (`/app/frontend/.env`)
- `REACT_APP_BACKEND_URL` — public backend URL (Kubernetes ingress in dev, Vercel URL in prod).
- `REACT_APP_NEON_AUTH_URL` — same as backend's `NEON_AUTH_URL`, exposed to the browser.
- `WDS_SOCKET_PORT=443`.

## Status (2026-08-09 — Postgres + Neon Auth migration)

### ✅ Shipped this session (2026-08-09)
- **Mongo → Neon Postgres migration.** Built `docdb.py` — a tiny mongo-look-alike over JSONB (`find_one`, `find`, `insert_one`, `update_one`, `update_many`, `count_documents`, `.sort().limit().to_list()`, `$set`, `$push`, upserts). Swapped all ~15 mongo call sites in `server.py` without rewriting business logic. Verified end-to-end: chain built, files generated, scored 2.62 composite, owner-isolated (404 on wrong session). Motor & DB_NAME/MONGO_URL removed.
- **Emergent Google Auth → Neon Managed Better Auth.** Backend verifies EdDSA JWTs from Neon's JWKS. Frontend uses `better-auth/react` — sign-in redirects through Neon → Google → back to app; JWT auto-refreshes and is attached to every `/api/*` request as `Authorization: Bearer`. Sign-in flow verified live (Google OAuth page reached).
- **CORS + trusted domains configured** for the preview URL in the Neon Auth dashboard.

### Historical (previous sessions)
- Real code gen (Artist emits actual source files, seed_template fills gaps).
- Hard failure, never fake success (Artist retries 3× then chain hard-fails).
- SSE streaming (Teacher/Artist tokens live in a two-pane console).
- BYOK (users paste OpenRouter/Venice/NVIDIA keys — never leaked back to client).
- GitHub push (creates repo + writes files + git push via env-fed GIT_ASKPASS).
- Verified filter tab in the Archive.
- Orphan sweep on boot (`running` chains → `failed`).
- Executor kills whole process group (`os.setsid` + `os.killpg`).
- Security audit fixes (SEC-001/002/004 closed).
- Chain ownership across all 8 chain endpoints (SEC-003 closed).

## Backlog

### P0 — Vercel deployability
- Rewrite `executor.py` to use **Vercel Sandbox API** (drop local subprocess). Needs `VERCEL_SANDBOX_TOKEN`. Blocks `vercel.json` and going live.
- Add `vercel.json` + serverless-safe pool lifecycle for asyncpg.

### P1 — Product features
- **6-Man AI Dev Team**: add Architect + Reviewer roles to the current Teacher / Artist / Corrector / Rater lineup. Extend `chain_generator.py` + `SettingsPanel.jsx` role picker + `ChainViewer.jsx` breadcrumb.
- **Novelty metric** in scoring: `composite = coverage*0.4 + rater*0.4 + novelty*0.2`, where `novelty = 1 - jaccard(artist_files, top_exemplar)`, gated on coverage ≥ threshold.
- **Rate limit on `/api/evolve`** (in-process token bucket keyed on `user_id` or `session_id`) to prevent LLM key burn.

### P2 — Polish
- Seed the verified pool with 5-10 pre-verified builds.
- Landing / TOS / Privacy pages.
- BYOK strict `user_id` resolution on the signed-in path.
- `/api/status` cross-tenant `total_chains` leak (scope to caller).
- Obsolete backend tests still reference Mongo (`tests/test_auth.py`, `tests/test_iteration6_fixes.py`) — rewrite for Postgres + Neon JWT or delete.

## Credentials
- All secrets in `/app/backend/.env` and `/app/frontend/.env`. Never committed.
