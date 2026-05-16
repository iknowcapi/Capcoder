# RECURSIVE.BBS — PRD

## What it is
An application that builds bot-builders. One button. Zero human input.

## How it works
- Gen 1 = RECURSIVE.BBS itself (this app).
- User pushes EVOLVE. Backend `/api/evolve` returns a chain stub in 83ms.
- Background task autonomously chains GLM-5.1 → MiniMax-M2.7 → Nemotron-Super-49B for each generation:
  - **GLM-5.1** designs the next gen (name, philosophy, input-style, output-style, system-prompt, ui-hint) as tight JSON.
  - **Deterministic synthesis** turns that spec into 5 real runnable files: backend/server.py (FastAPI app that itself calls an LLM), backend/requirements.txt, frontend/index.html, run.sh, README.md.
  - **MiniMax-M2.7** writes a prose critique of the generated app.
  - **Nemotron-Super-49B** scores it on 5 dimensions, returns strict JSON.
- Gen 2's design is auto-fed back to GLM as context for Gen 3 → no human ever picks the prompt.
- Frontend polls `/api/chains/{id}` every 3s, rendering each generation as it lands.
- One `.zip` contains `gen-02-XYZ/`, `gen-03-ABC/`, etc. side-by-side plus `CHAIN.md` and per-gen `.recursive-bbs.json` manifests.

## Architecture
- `/app/backend/server.py` — FastAPI orchestration. Endpoints: POST /api/evolve, GET /api/chains, GET /api/chains/{id}, GET /api/chains/{id}/download, GET /api/chains/{id}/download/{gen}, GET /api/status, GET /api/.
- `/app/backend/chain_generator.py` — NIM client, design-only LLM call (~900 tokens), deterministic file synthesis (template parameterized by AI-designed name/styles/system_prompt/ui_hint), critic+rater in parallel per gen.
- `/app/frontend/src/App.js` — single page. `EvolveButton` (one click) + `ChainViewer` (lineage breadcrumb, per-gen cards with code preview, per-gen .zip download, whole-chain .zip download).

## Status (2026-05-16)
- v1.0.0 — autonomous chain evolution working end-to-end
- depth=2 ≈ 3 min; depth=3 ≈ 4–5 min; depth=5 ≈ 8–10 min (sequential gens; each gen ~90s)
- Each generated app: ~160 LOC, valid Python, runnable with `bash run.sh`, falls back to STUB_MODE if NVIDIA_API_KEY absent

## Backlog (P1)
- Run gens in parallel where chain history allows (Gen 3 can start as soon as Gen 2's spec is generated, before Gen 2's critic+rater finish)
- Streaming progress (SSE) so the UI shows tokens as they generate
- "Merge two chains" feature (the only human-influence the user wanted)

## Credentials
- `NVIDIA_API_KEY` in `/app/backend/.env`
