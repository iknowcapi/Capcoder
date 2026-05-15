# RECURSIVE.BBS — PRD

## Problem
A code-builder app that creates code-building bots. Bots emit real, runnable, downloadable code projects. Review (critic) and ranking (rater) are part of every build.

## Pipeline (v0.3.0)
1. **Deterministic blueprint bot** (`blueprints.py`) writes a runnable folder for the detected domain (kanban, notes, habit-tracker, chat, generic-crud).
2. **NVIDIA NIM augmentation** (`nim_augment.py`) runs in parallel:
   - **GLM-5.1** writes a real `DESIGN.md` and is the included LLM-judge for scoring (`glm-5.1-judge`)
   - **MiniMax-M2.7** (reasoning model) writes a real prose code review — catches missing tests, unused fields, missing CORS, unsafe patterns
   - GLM-5.1 LLM-judge returns strict-JSON 5-attribute scores (0-4 each)
   - Nemotron-70B-Reward endpoint is gated behind a separate API permission tier (returns 404 on standard keys) — replaced with GLM-judge with explicit rubric. Heuristic fallback retained on any LLM failure.
3. User downloads `.zip` containing the full folder + manifest.

## Implemented (2026-05-15)
- 5 working blueprints; generated projects pass `python3 -c "import server"` cleanly
- Real NVIDIA NIM augmentation wired (NVIDIA_API_KEY in `/app/backend/.env`)
- Hero badge shows `NVIDIA NIM :: LIVE` when key present
- 15/15 backend pytest + 12/12 frontend playwright tests pass (v0.2.0 baseline; v0.3.0 additions verified via curl)

## Performance note
Full augmented build = ~60-70s end-to-end (3 LLM calls in parallel + deterministic generation). Public preview gateway has ~90s soft timeout. Heuristic fallback ensures the build never blocks if NIM is slow.

## Backlog (P1)
- Background augmentation: return build immediately with heuristic outputs, stream NIM results back via polling/SSE
- Live in-browser preview (iframe sandbox)
- Parent↔child diff viewer
- Add blueprints: marketplace, booking, social-feed

## Backlog (P2)
- Multi-user accounts + per-user gene pool
- "Auto-evolve N generations" loop
- Shareable public preview URLs for top-rated builds

## Credentials in env
- `NVIDIA_API_KEY` (set, working) — used for GLM-5.1 (design + judge) and MiniMax-M2.7 (critique)
