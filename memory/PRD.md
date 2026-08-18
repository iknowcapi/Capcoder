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

## Status (2026-08-18 — Recursive self-improvement Layer #5: Evaluation-Criteria Meta-Loop)

### ✅ Shipped this session (2026-08-18, third pass)
- **`backend/eval_meta.py`** (new): the composite score's fixed weights (coverage×0.4 + rater×0.4 + novelty×0.2) are now data-driven. `maybe_recompute()` (throttled, ≤1/hr, called opportunistically from `/verify` and `/check-edits`) buckets recent complete builds into "good" (✓ Verify AND never edit-diffed) vs "bad", measures the mean-gap per dimension, floors each weight at 0.1, and blends 70% prior / 30% freshly computed for stability. Gated on `MIN_SAMPLE_SIZE=15` so early on the rubric stays exactly at defaults.
- `GET /api/eval-weights` (public) — current weights + sample_size + is_default, for transparency.
- `chain_generator.composite_v2()` now takes a `weights` param (`.get()`-safe against a partial/malformed doc — testing_agent-flagged fix); every scored generation on trial/paid tiers stamps `eval_weights` used. Free tier (teacher+artist only) never touches this path — unchanged, pre-existing behavior.
- Frontend: `ChainViewer.jsx` shows a small "scored via: cov X% · rater X% · novelty X%" line under COMPOSITE when present.
- **2 LOW bugs fixed from iteration_10**: `edits.py`'s `_store_diff` now returns `seconds_since_build` immediately in the `check-edits` response (no reload needed); `App.js`'s auth check now skips `/api/auth/me` entirely when there's no Neon JWT (was 401-spamming on every anon page load).
- Tested: testing_agent iteration_11 — 18/18 backend pytest + full Playwright frontend, 100% pass, no critical issues.

### Not yet built (deferred, per user's stated order: #7 done → #5 done → #1 next)
- **#1 — Prompt/instruction self-tuning**: rewrite Teacher/Artist system prompts based on outcome data. `corrections_digest()` (Layer #7) already feeds per-build hints into the Teacher prompt, but the prompts themselves are still static — this is the next planned layer.
- **#2, #3, #4, #6, #8** (test-gen loop, error-pattern library, architecture-decision tracking, dependency allow/avoid list, auto-doc context): not scoped, no sequencing decided beyond #7→#5→#1.

### Previously shipped (2026-08-18, second pass — Layer #7 User Edit Diffing)
User asked to make every decision layer of the app recursive (prompt/instruction, test-gen, error-pattern library, architecture decisions, eval-criteria meta-loop, dependency selection, user-edit diffing, docs/context). Agreed sequencing: **#7 (User Edit Diffing) first** — it's the ground-truth signal everything else (#5, #1) would otherwise guess at.

- **`backend/edits.py`** (new): every completed build gets a `build_manifest` (sha256 per file) + `built_at` stamped on the chain doc (`Chain` Pydantic model gained these + `github` fields — root-cause fix for a bug where they were silently stripped from every API response).
- **`POST /api/chains/{id}/check-edits`**: two ways in — (a) if pushed to GitHub, diffs the pushed commit vs current HEAD via GitHub's compare API (`check_git_edits`, untested live — no PAT available in this env); (b) upload the edited project as a `.zip` (`check_upload_edits`) — hash-compared against the manifest, real unified diffs via `difflib`. Upload takes priority over the git path when both are present. Path-normalization handles one level of nested-zip folders. Append-only storage with de-dup against the last identical hunk (no spam on repeat checks).
- **`GET /api/chains/{id}/edit-diffs`**: persisted history of detected corrections per chain.
- **Feedback loop closed**: `corrections_digest()` pulls the 5 most recent cross-tenant corrections and injects them into every new build's Teacher prompt as "COMMON USER CORRECTIONS ACROSS PRIOR BUILDS" — this is what makes the loop recursive, not just a diff viewer.
- **Frontend**: `ChainViewer.jsx` gained a "check for edits"/"upload edits" button (context-sensitive on whether the chain was pushed), a hidden `.zip` file input, and a "LEARNED CORRECTIONS" panel with per-file expandable diff hunks.
- **Storage**: `edit_diffs` is a new logical collection inside the *same* single Postgres `docs` table (docdb.py) — no new database, no migration, confirmed auto-created and populated.
- **Bug found+fixed mid-session** (correction-pass trigger in `chain_generator.py` was gated on non-empty stderr, silently skipping correction + reporting "already working" right after EXECUTE said "failed to start" — now fixed in both the checkpointed and legacy code paths, verified live via curl).
- Tested: testing_agent iteration_10 — 13/13 backend pytest cases + full Playwright frontend flow, 100% pass, no critical issues (2 cosmetic LOW items noted below).

### Not yet built (explicitly deferred, next up per user's stated order)
- **#5 — Evaluation criteria meta-loop**: recursively refine the scoring rubric itself using acceptance signals (✓ Verify button + now also edit-diff volume/severity as a proxy). NOT started.
- **#1 — Prompt/instruction self-tuning**: rewrite Teacher/Artist system prompts based on which produced the highest-scoring, least-corrected builds. NOT started (the corrections_digest feed into the Teacher prompt is a first step toward this, but the prompts themselves are still static).
- **#2, #3, #4, #6, #8** (test-gen loop, error-pattern library, architecture-decision tracking, dependency allow/avoid list, auto-doc context): not scoped yet, no user decision made on sequencing beyond "#7 → #5 → #1".

### Previously shipped (2026-08-18, first pass — Pricing page, trial repricing, annual billing)
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

### P1 — Recursive self-improvement layers (user's stated priority: #7 done, #5 done → #1 next)
- **#1 Prompt/instruction self-tuning**: rewrite Teacher/Artist system prompts based on outcome data (which prompts→highest scores, fewest corrections). `corrections_digest()` already feeds the Teacher per-build; the prompts themselves are still hand-written/static.
- GitHub compare path (`check_git_edits` in edits.py) and paid/trial-tier `eval_weights` wiring have never been exercised live end-to-end — no Google login / GitHub PAT available in this env. Verified by code inspection + unit-level calls only.
- (Optional, LOW) `eval_meta.maybe_recompute()` runs inline inside `/verify`/`/check-edits` — once sample_size clears 15 it scans up to 500 chains on that one request. Fine at current scale; move to `BackgroundTasks` if it ever becomes noticeable.
- `tiers.py`'s monthly-plan price lookup now accepts BOTH `STRIPE_PRICE_ID_PAID` and the shorter legacy `STRIPE_PRICE_ID` (user already had the latter set in Render for the pre-existing monthly plan) — `STRIPE_PRICE_ID_PAID` wins if both are set. Trial/annual only accept their own explicit names (`STRIPE_PRICE_ID_TRIAL` / `STRIPE_PRICE_ID_PAID_ANNUAL`, added this session).

### P1 — Product / billing follow-ups
- User needs to paste `STRIPE_PRICE_ID_TRIAL` and `STRIPE_PRICE_ID_PAID_ANNUAL` into Render once created in Stripe.
- Credit top-up packs — no price/size decided yet.

### P2 — Polish
- Seed the verified pool with 5-10 pre-verified builds.
- TOS / Privacy pages.
- Neon's own `/token` endpoint still logs ~6-14 401s per anon session in console (out of scope for the auth-me fix this round — gate on a Neon session cookie if a fully clean console matters).
- `edits._normalize_upload_paths` only strips one leading path segment — a zip nested 2+ levels deep would still miss.
- `GET /edit-diffs` caps at 50 rows, no pagination.
- `/api/tier/prices` cache has no manual bust — 1h staleness after a Stripe price edit.
- BYOK strict `user_id` resolution on the signed-in path.
- Obsolete backend tests still reference Mongo (`tests/test_auth.py`, `tests/test_iteration6_fixes.py`) — rewrite for Postgres + Neon JWT or delete.

### Known env gap (this preview only, not production)
- No `GROQ_API_KEY` configured here → default anonymous free-tier builds fail at the Teacher step with a clear error (not a silent fake). User confirmed 5 keys already in Render for production. Workaround for testing here: point Settings at an OpenRouter model.

## Credentials
- All secrets in `/app/backend/.env` and `/app/frontend/.env`. Never committed.
