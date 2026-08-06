# CapCode — PRD

## What it is
CapCode is a recursive bot-builder: **one human prompt → Teacher bot → Artist bot → downloadable Product code**. Dark 1980s neo-noir BBS aesthetic. Not a Cursor/v0 competitor — CapCode strictly generates a fresh runnable project, not IDE assistance.

## Strict topology (do not deviate)
1. Human types the app they want built.
2. **TEACHER** bot (rigid, strict) reads the target + the top verified prior chains as few-shot exemplars, and writes a brief for the Artist.
3. **ARTIST** bot (creative, novel) turns the Teacher's brief into the actual product spec.
4. **Product** is materialized from `seed_template.render(spec, stack=…)` into a real folder (Python/FastAPI, Vite/React, Rust, Go, or WebGL/HTML) inside `/workspaces/`.
5. **Executor** runs `bash run.sh` in a subprocess (port check + stdout/stderr capture).
6. If the app fails to start, **one** correction pass is attempted (Artist re-designs using the real stderr), then re-executed.
7. **RATER** scores the result on 5 dimensions; composite score = weighted sum.
8. Human can click **✓ Works — Verify** on a completed chain; verified chains feed the Teacher's exemplar pool for future builds and get +0.5 composite boost (capped at 4.0).

## Architecture
- `/app/backend/server.py` — FastAPI routes: `POST /api/evolve`, `GET /api/chains`, `GET /api/chains/{id}`, `GET /api/chains/{id}/download`, `GET /api/chains/{id}/download/{gen}`, `POST /api/chains/{id}/verify`, `POST /api/chains/{id}/workspace/{gen}`, `GET /api/status`, `GET /api/providers/models`, `GET/POST /api/settings`.
- `/app/backend/chain_generator.py` — `evolve_chain_with_callback(chain_id, target_prompt, on_gen, on_done, assignments, exemplars)`. Roles: `teacher`, `artist`, `rater`.
- `/app/backend/executor.py` — materialize + `bash run.sh` in subprocess with port check.
- `/app/backend/seed_template.py` — multi-stack renderer. `render(mutation, stack=…)` dispatches to `_render_node` / `_render_rust` / `_render_go` / `_render_webgl`; default is python-fastapi.
- `/app/backend/providers.py` — NVIDIA / OpenRouter / Venice OpenAI-compatible clients. `DEFAULT_ASSIGNMENTS` = `{teacher, artist, rater}` (all on NVIDIA `z-ai/glm-5.2` / `z-ai/glm-5.2` / `llama-3.3-nemotron-super-49b-v1.5`).
- `/app/frontend/src/App.js` — orchestration + polling.
- `/app/frontend/src/components/EvolveButton.jsx` — human prompt textarea, stack-hint picker, BUILD button.
- `/app/frontend/src/components/ChainViewer.jsx` — Teacher→Artist→Product breadcrumb, code preview, .zip download, VSCode-workspace hand-off, **✓ Works Verify** button.
- `/app/frontend/src/components/SettingsPanel.jsx` — pick model for each of `teacher / artist / rater` roles.

## Status (2026-08-06)
- ✅ Full Teacher → Artist → Product loop works end-to-end. Verified with curl: build "hello-world FastAPI" completes in ~2 min, produces 6-file downloadable folder with `TEACHER_SPEC.md` + `ARTIST_NOTES.md`.
- ✅ `POST /api/chains/{id}/verify` boosts composite score and stores exemplar.
- ✅ Multi-stack seed templates for python-fastapi / node-vite / rust / go / webgl.
- ✅ Fixed EOL NVIDIA models (`glm-5.1` → `glm-5.2`, `minimax-m2.7` → `glm-5.2` fallback).

## Backlog
- P1: Wire an OpenRouter free coding model as artist_fallback so users can build even with NVIDIA outages.
- P1: Stream Teacher / Artist tokens over SSE so the UI shows progress mid-generation.
- P2: Git subprocess sandbox + GitHub PAT vault (push generated repos directly to GitHub).
- P2: Real code-server (VSCode-in-browser) URL detection so the "VSCODE" button opens the workspace deterministically.

## Credentials
- `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `VENICE_API_KEY` live in `/app/backend/.env`.
