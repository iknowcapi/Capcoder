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

## Status (2026-08-06 — post recursion fix)

### ✅ Working end-to-end AND recursively learning
- **No more silent boilerplate fallback.** If Artist can't produce real files after 3 retries (temperature: 0.7 → 0.4 → 0.2, max_tokens: 12k → 8k → 4k), chain hard-fails with `ArtistFailedError` and the UI shows the reason in red. The user never gets a fake product.
- **Truncated-JSON repair.** When Claude/GPT hits max_tokens mid-response, `_repair_truncated_json()` closes the open string + drops the dangling `"key":` fragment + closes all open braces. Partial-but-valid file sets are recovered instead of being dropped.
- **Real recursion (`RECURSIVE.BBS` was the original name for a reason):** every human ✓Verify on a chain pushes its **actual Artist files** into a rolling exemplar pool. The next Teacher sees the brief-level summary; the next **Artist gets shown the real file layout + a 600-char code snippet** from up to 2 verified prior builds so it copies patterns that actually worked.
- Multi-attempt Artist with per-attempt directives (attempt 1 → "be terser, 3-4 files ≤150 lines", attempt 2 → "tiniest possible working version, one main file ≤120 lines").
- Executor kills whole process group (`os.setsid` + `killpg`) — no more orphaned children.
- Verified end-to-end: CubeOrbiter (chain `2762a8c0`, 4360-char WebGL + Three.js orbit cube) built in **45 seconds** using OrbitCube (chain `9cf2fc80`) as its verified exemplar. Two verified chains now in the exemplar pool.

### Providers
Model choice is user-driven (per-device settings). Sensible defaults route through **OpenRouter** (user has credits): Teacher = `deepseek/deepseek-v4-flash`, Artist = `anthropic/claude-sonnet-5`, Rater = `inclusionai/ling-3.0-flash:free`. Fallback = Venice `qwen3-coder-480b-a35b-instruct-turbo`. NVIDIA de-prioritized (pay-as-you-go friction).

## Backlog (post-reliability)
- P1: BYOK — let users paste their own OpenRouter/Venice keys.
- P1: Auth + per-user chain ownership; rate limits per plan tier.
- P1: SSE streaming so the UI shows Artist tokens live.
- P2: Landing page, docs, TOS + privacy; deploy to real domain.
- P2: Git PAT vault + one-click GitHub push.
- P2: Verified-only leaderboard tab in the archive.

## Credentials
`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY` in `/app/backend/.env`.
