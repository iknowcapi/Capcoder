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
- **Deploy target**: Split — **Frontend on Vercel**, **Backend on Render** (persistent container; Render was chosen over Vercel Serverless because the code-execution sandbox needs a real `subprocess.Popen`, which serverless can't reliably support).

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

## Status (2026-08-18 — Pricing page, trial repricing, annual billing)

### ✅ Shipped this session (2026-08-18)
- **New Pricing page** (`PricingPage.jsx`) — 3 plan cards (Free/Trial/Paid), reachable from landing nav, build-view header, and Settings "see full plans" link. Monthly/annual toggle for the Paid card.
- **Trial repriced**: was free/no-card, now a **$2.99 one-time Stripe charge** (`plan=trial` in `/api/tier/checkout`, mode="payment") — priced to cover the trial's own NVIDIA compute cost. `/api/tier/start-trial` (the old free path) is now gated behind `ALLOW_MOCK_BILLING=true` and 410s otherwise.
- **Trial is NVIDIA-only end to end**: `providers.TIER_ASSIGNMENTS["trial"]` and new `TRIAL_FALLBACKS` route all 6 roles (teacher/architect/artist/reviewer/rater/corrector) through NVIDIA only — even the error-path fallback never reaches a metered OpenRouter/Venice call.
- **Annual billing** added for the $16/mo plan (`plan=paid_annual`, same entitlement as `paid`, just a different Stripe price/interval). `billing.get_cycle()` now does lazy 30-day renewal so credits refill monthly regardless of billing interval (no Stripe webhook needed per renewal).
- **`GET /api/tier/prices`** (public, cached 1h) — Stripe-backed with static fallback, so the Pricing page never hardcodes a price that can drift from what Stripe actually charges.
- **Bug fixes** (found by testing_agent iterations 8 & 9): `teacher_step` now raises `TeacherFailedError` instead of silently faking a spec when the LLM returns nothing; `handleEvolve`'s catch branch now calls `refresh()` so failed builds show up in history immediately; Pricing page's back button now returns to wherever it was opened from instead of always landing; **correction-pass trigger bug** — `correct` stage was gated on `stderr` or `review_notes` being non-empty, so a failed build with no stderr (e.g. SIGTERM/-15 timeout, static HTML never binding a port) silently skipped correction and reported "already working" right after EXECUTE said "failed to start". Fixed in both the checkpointed `run_stage` path and the legacy (dead but fixed for consistency) `evolve_chain_with_callback`.
- Env vars still needed on Render (user creating in Stripe, not yet supplied): `STRIPE_PRICE_ID_TRIAL` (one-time $2.99), `STRIPE_PRICE_ID_PAID_ANNUAL` (recurring yearly). `STRIPE_PRICE_ID_PAID`/`STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET` + 5 Groq keys already added by user in Render.

### Previously shipped (2026-08-09 — Postgres + Neon Auth migration)
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

### P0 — none open

### P1 — Product / billing follow-ups
- Add `stripe`-key-holder must paste `STRIPE_PRICE_ID_TRIAL` and `STRIPE_PRICE_ID_PAID_ANNUAL` into Render once created (one-time price for trial, recurring-yearly price for annual) — everything else is already wired.
- Credit top-up packs (user mentioned wanting these once annual/trial landed) — no price/size decided yet, needs its own round of clarification before building.
- `billing.get_cycle()`'s lazy renewal refills on `status=="active"` alone — doesn't check a paid-through timestamp, so a lapsed annual subscription with a missed webhook would still refill. Low-risk edge case, revisit if it becomes real.

### P2 — Polish
- Seed the verified pool with 5-10 pre-verified builds.
- TOS / Privacy pages.
- `/api/auth/me` 401s on every signed-out page load are cosmetic console noise (frontend calls it on mount + 60s poll) — consider 200 `{user:null}` or skipping the call with no JWT present.
- `/api/tier/prices` cache has no manual bust (`?refresh=1`) like `/providers/models` does — 1h staleness after a Stripe price edit.
- BYOK strict `user_id` resolution on the signed-in path.
- Obsolete backend tests still reference Mongo (`tests/test_auth.py`, `tests/test_iteration6_fixes.py`) — rewrite for Postgres + Neon JWT or delete.

### Known env gap (this preview only, not production)
- No `GROQ_API_KEY` configured here → default anonymous free-tier builds fail at the Teacher step with a clear error (not a silent fake). User confirmed 5 keys already in Render for production. Workaround for testing here: point Settings at an OpenRouter model.

## Credentials
- All secrets in `/app/backend/.env` and `/app/frontend/.env`. Never committed.
