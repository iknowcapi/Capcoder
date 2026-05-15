# RECURSIVE.BBS — PRD

## Problem
Build an intelligent ML bot that improves itself by building app-builders that build app-builders.

## Architecture
- **Backend**: FastAPI + Motor (MongoDB). Three-model pipeline via NVIDIA NIM OpenAI-compatible API:
  - Generator: `z-ai/glm-5.1` → emits `{meta_builder, app_spec}` JSON
  - Critic: `minimaxai/minimax-m2.7` → emits 3-clause critique
  - Rater: `nvidia/llama-3.1-nemotron-70b-reward` → 5-dim score (helpfulness/correctness/coherence/complexity/verbosity)
- **Self-improvement loop**: Top-rated past builds are fetched and injected as exemplars in every new generator prompt. User feedback (thumbs up/down ±0.25) reshapes the gene pool.
- **Stub mode**: When `NVIDIA_API_KEY` is empty, deterministic stubs (md5-seeded) produce realistic specs/critique/scores so app is fully testable offline.
- **Frontend**: Single-page React dashboard, dark 1980s BBS / neon-punk CRT aesthetic (VT323 + IBM Plex Mono, scanlines, vignette, grain, neon green/magenta/cyan/yellow).

## Implemented (2026-05-15)
- Pipeline: GLM→MiniMax→Nemotron orchestrated in `POST /api/builds`
- Endpoints: `/api/`, `/api/status`, `/api/builds` (POST+GET), `/api/builds/{id}` (GET), `/api/builds/{id}/feedback` (POST), `/api/leaderboard`, `/api/lineage`
- Fork support: `parent_id` increments generation
- UI: TerminalHero with ASCII art, PromptConsole with blinking cursor + sample prompts, Pipeline visualization with active-stage flicker, BuildDetail with ASCII progress bars + JSON viewers, Leaderboard, Recent Library, LineageTimeline with glow-by-score
- 13/13 backend pytest pass, frontend 100%

## Backlog (P1)
- Real NVIDIA NIM key wiring + production retries
- Streaming SSE for token-by-token generation preview
- Diff view between parent and child meta_builder specs
- Export build as scaffold (zip of files)

## Backlog (P2)
- Multi-user accounts + per-user gene pools
- "Auto-evolve" mode that loops N generations unattended
- Code preview from app_spec (live render)

## Credentials
- `NVIDIA_API_KEY` in `/app/backend/.env` (currently empty placeholder → stub mode)
- Obtain at https://build.nvidia.com/settings/api-keys
