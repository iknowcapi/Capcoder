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

## Status (2026-08-06)

### ✅ Working end-to-end
- Real code gen verified with two independent test builds:
  - **OrbitCube** (chain `9cf2fc80`): 378-line hand-rolled WebGL cube with WASD orbit camera, custom shaders, matrix math.
  - **VoidCube** (chain `4ab8ab1d`): 5910-char WebGL cube, retry loop kicked in (attempt 1 succeeded after attempt 0 failed), executor started on port 8123, composite 3.075.
- Per-device model settings persist via `session_id`.
- `POST /api/chains/{id}/verify` boosts score + feeds Teacher exemplars.
- Multi-stack: Python-FastAPI, Node-Vite, Rust, Go, WebGL.
- Zip download includes Product files + `TEACHER_SPEC.md` + `ARTIST_NOTES.md` + `.recursive-bbs.json`.

### 🟡 Known reliability gaps (P0 for next session)
- Artist success rate ≈ 60–70% first try, ≈ 90%+ with retry. When both attempts fail (truncated / bad JSON), we fall through to boilerplate → user gets a hello-world instead of their app. **Fix:** third attempt on a cheaper coder (kimi-k2.7-code) + hard-fail the chain if still empty rather than silently rendering boilerplate.
- Executor false-negative when Node/Vite `npm install` exceeds 90s → correction pass unnecessarily. **Fix:** stream stdout, detect "vite listening" line instead of pure port poll.
- WatchFiles auto-reload kills in-progress background tasks → chains stuck in `running`. **Fix:** disable `--reload` in supervisor (or move chains to a real task queue).

## Backlog (post-reliability)
- P1: BYOK — let users paste their own OpenRouter/Venice keys.
- P1: Auth + per-user chain ownership; rate limits per plan tier.
- P1: SSE streaming so the UI shows Artist tokens live.
- P2: Landing page, docs, TOS + privacy; deploy to real domain.
- P2: Git PAT vault + one-click GitHub push.
- P2: Verified-only leaderboard tab in the archive.

## Credentials
`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY` in `/app/backend/.env`.
