# CapCode — PRD

## What it is
CapCode is a recursive bot-builder. Human types the app they want; the system runs **Teacher → Artist → Product → Rater**, delivering a runnable downloadable code folder. Dark 1980s neo-noir BBS aesthetic. Not a Cursor/v0 competitor — CapCode strictly generates a fresh runnable project, not IDE assistance.

## Strict topology (do not deviate)
1. Human types the app they want built.
2. **TEACHER** bot (rigid, strict) reads the target + top-verified prior chains and writes a brief for the Artist. Default: OpenRouter `deepseek/deepseek-v4-flash`.
3. **ARTIST** bot (creative, novel) — **writes the actual source files** as a `files: [{path, content}]` array. Default: OpenRouter `anthropic/claude-sonnet-5`. Auto-retries once with terser directive if the first response is truncated/unparseable.
4. **Product** is materialized to `/workspaces/<chain>/<name>/`. `seed_template.render()` uses Artist files verbatim and only fills gaps (adds `run.sh`, `package.json`, `Cargo.toml`, `go.mod`, `README.md` if missing).
5. **Executor** runs `bash run.sh` in an isolated process group and polls the port up to 25s (Python/WebGL) or 90s (Node/Rust/Go — allow install/compile). Whole process group is SIGTERM/SIGKILL'd on shutdown so children don't leak.
6. If the app fails to start, **one** correction pass runs (corrector rewrites `files` based on real stderr).
7. **RATER** scores. Composite score = weighted sum. Default rater: OpenRouter `inclusionai/ling-3.0-flash:free`.
8. Human clicks **✓ Works — Verify** on a completed chain → +0.5 composite boost + fed into the Teacher exemplar pool.

## Architecture
- `/app/backend/server.py` — FastAPI routes: `POST /api/evolve`, `GET /api/chains`, `GET /api/chains/{id}`, `GET /api/chains/{id}/download`, `POST /api/chains/{id}/verify`, `GET /api/status`, `GET /api/providers/models`, `GET/POST /api/settings?session_id=…`.
- `/app/backend/chain_generator.py` — Teacher / Artist / Corrector / Rater steps. Robust JSON extractor (`strict=False`, brace-aware, string-quote-aware).
- `/app/backend/executor.py` — subprocess spawn with `os.setsid()`, process-group tear-down.
- `/app/backend/seed_template.py` — `render()` uses Artist files verbatim; `_fill_gaps()` adds missing scaffolding per stack.
- `/app/backend/providers.py` — OpenAI-compatible clients for OpenRouter/NVIDIA/Venice. Defaults route through OpenRouter with Venice fallback (NVIDIA de-prioritized after PAYG friction).
- `/app/frontend/src/App.js` — orchestration + polling; per-device `session_id` in localStorage.
- `/app/frontend/src/components/EvolveButton.jsx` — human target textarea + stack picker.
- `/app/frontend/src/components/ChainViewer.jsx` — Teacher/Artist/Product breadcrumb, download .zip, ✓Verify button.
- `/app/frontend/src/components/SettingsPanel.jsx` — pick model per role (teacher/artist/rater), saved per-device.

## Status (2026-08-06 — final state)

### ✅ Shipped this session
- **Real code gen.** Artist emits `files: [{path, content}]` real source. `seed_template` fills gaps only. Verified with WebGL, Vite, and mixed builds (OrbitCube, VoidCube, CubeOrbiter, SatoshiPulse).
- **Hard failure, never fake success.** Artist retries 3× with decreasing token budgets; if still empty, chain hard-fails with a red banner and a clear reason. No more silent boilerplate.
- **Truncated-JSON repair.** `_repair_truncated_json` closes unfinished strings + dangling `"key":` fragments + open braces so partial LLM outputs still yield valid file sets.
- **Real recursion.** Every ✓Verify pushes the chain's actual Artist files into a rolling exemplar pool. Next Artist sees the file layout + 600-char code snippet from up to 2 verified prior builds and copies patterns that worked.
- **SSE streaming.** `GET /api/chains/{id}/stream` emits Teacher/Artist token deltas + stage transitions. UI shows live tokens in a two-pane console (Teacher cyan, Artist magenta). Confirmed live: real per-token deltas arriving during a build.
- **BYOK.** Users paste their own OpenRouter/Venice/NVIDIA keys in Settings. Keys are stored per-device only; the frontend only sees `keys_set` booleans, never the values. If a user key is set for a provider, it overrides the server default for that user's chains.
- **GitHub push.** `POST /api/chains/{id}/push` creates a new GitHub repo (public/private), writes the Artist files + `TEACHER_SPEC.md` + `ARTIST_NOTES.md`, git-inits, force-pushes to `main`. UI has a "PUSH TO GITHUB" button with a repo-name field. Requires the user to have saved a GitHub username + PAT (scope `repo`) in Settings.
- **Verified filter tab** in the Archive so returning users can see only human-approved chains.
- **Orphan sweep on boot.** Any chain still marked `running` when the backend starts gets moved to `failed` with reason "backend restarted before build finished — try again." No more zombie chains after supervisor reloads.
- **Executor kills whole process group.** `os.setsid` + `os.killpg` — no more orphaned `python3 -m http.server` / `vite` children leaking after builds.

### Security posture (2026-08-06 — post audit)
Audit ran; **DO NOT LAUNCH** verdict addressed by fixing the P0/P1 issues without breaking the framework:

- ✅ **SEC-001 (Critical)** — Executor child env is now whitelisted (`PATH/HOME/TERM/LANG/LC_ALL/LC_CTYPE/USER/TMPDIR/PWD/SHELL` + injected `APP_PORT`). Provider keys and Mongo URL never reach AI-generated `run.sh`. Verified by testing agent: env dump contains no `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY`, `MONGO_URL`, `DB_NAME`, nor their values.
- ✅ **SEC-002 (High)** — Every Artist/corrector-authored file path goes through the shared `_is_safe_relpath` predicate (rejects `..`, absolute paths, backslashes, null bytes); `executor.materialize()` also `Path.resolve()`s and confirms the write target sits inside the workspace root. Verified against `../../etc/passwd`, `/tmp/pwned`, `..\pwn`, `dir/../../out`, `x\x00y`, `a/b/../../../../oops.txt` — all rejected.
- ✅ **SEC-004 (Medium)** — GitHub push endpoint uses `GIT_ASKPASS` (PAT never in argv / `/proc`). `--force` only used when the repo was just freshly created (HTTP 201), not for existing repos (422).

**Deferred out of scope (documented, not shipped):**
- SEC-005 (rate limit on `/api/evolve`) — deferred; enable when BYOK usage rules are decided.
- Global `/api/status` `total_chains` count is cross-tenant (informational only, no prompt/code leak).
- Model assignments (BYOK preferences) still resolved from body `session_id` even on the authenticated path — signed-in-only clients that don't send a session_id get server defaults.

### Chain ownership + rater fix (2026-08-07 — iteration 6, 60/60 pass)
- ✅ Every chain doc gets stamped with `user_id` (signed-in) OR `anon_session_id` (anonymous) at `/api/evolve`.
- ✅ SEC-003 closed. All 8 chain endpoints filter by owner and return 404 for non-owners: `/api/chains`, `/api/chains/{id}`, `/api/chains/{id}/download`, `/api/chains/{id}/download/{gen}`, `/api/chains/{id}/verify`, `/api/chains/{id}/stream`, `/api/chains/{id}/push`, `/api/chains/{id}/workspace/{gen}`.
- ✅ Frontend axios interceptor auto-injects `X-Capcode-Session` header on every /api/* request from `localStorage.capcode.session_id` (created on first page load, no click required). EventSource + `<a href>` downloads pass the same value as `?session_id=…` since they can't send headers.
- ✅ Rater default swapped from `inclusionai/ling-3.0-flash:free` (404) to `openai/gpt-3.5-turbo` (+ `openai/gpt-4o-mini` fallback). Startup validator confirms responsiveness at boot.
- ✅ Rater system prompt rewritten so weak models can't parrot a zero example → real differentiated scores. All-zero degenerate responses rejected → deterministic fallback (2.8 if exec started, 1.2 otherwise). Verified: 6/6 fresh builds all scored composite 3.37-3.63.

## Backlog (post-reliability)
- P1: BYOK — let users paste their own OpenRouter/Venice keys.
- P1: Auth + per-user chain ownership; rate limits per plan tier.
- P1: SSE streaming so the UI shows Artist tokens live.
- P2: Landing page, docs, TOS + privacy; deploy to real domain.
- P2: Git PAT vault + one-click GitHub push.
- P2: Verified-only leaderboard tab in the archive.

## Credentials
`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY` in `/app/backend/.env`.
