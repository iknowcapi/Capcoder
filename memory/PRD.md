# RECURSIVE.BBS — PRD

## Problem
A code-builder app that creates code-building bots. The bots emit real, runnable code projects that are one-click downloadable. Review (critic) and ranking (rater) are part of every build.

## Architecture
- **Backend** (`/app/backend/`):
  - `blueprints.py` — domain-aware bots that emit real files. Domains: kanban, notes, habit-tracker, chat, generic-crud (fallback). Each blueprint outputs `{bot, app, files:[{path,content}]}`.
  - `server.py` — FastAPI orchestration. Critic = file/endpoint heuristics. Rater = 5-dimension scoring from file metrics. Mongo persists every build + its files.
- **Pipeline**: prompt → blueprint (writes ~5 files) → critic reviews real files → rater scores them → user downloads `.zip` containing a runnable folder + `.recursive-bbs.json` manifest. Top-rated builds feed exemplars to future generations.
- **Frontend**: BBS / neon-punk dashboard. `BuildDetail` shows file tree + code preview + big DOWNLOAD .ZIP button.

## Implemented (2026-05-15 → updated v0.2.0)
- 5 working blueprints emit real FastAPI+HTML projects (~12KB each, ~250 LOC). Verified: generated kanban server parses cleanly and exposes all 8 routes including `PATCH /api/cards/{id}/move`.
- Endpoints: `/api/builds` POST+GET, `/api/builds/{id}` GET, `/api/builds/{id}/download` (zip stream), `/api/builds/{id}/feedback`, `/api/leaderboard`, `/api/lineage`.
- Fork (parent_id), feedback ±0.25, lineage glow-by-score.
- 15/15 backend pytest, 12/12 frontend playwright pass.

## Backlog (P1)
- Add blueprints: marketplace, booking/scheduler, social-feed, auth-walled SaaS
- Live preview pane (run the generated app in an iframe sandbox)
- Diff view between parent and child generated code
- Optional NVIDIA NIM (GLM/MiniMax/Nemotron) augmentation: route the generated skeleton through GLM for elaboration, MiniMax for refactor suggestions, Nemotron for quality scoring

## Backlog (P2)
- Multi-user accounts + per-user gene pool
- "Auto-evolve N generations" unattended loop
- Public shareable URLs for top-rated builds

## Files of note
- `/app/backend/blueprints.py` (1035 lines — split per-domain if more added)
- `/app/backend/server.py` (orchestration)
- `/app/frontend/src/components/BuildDetail.jsx` (file tree + code pane + download)
