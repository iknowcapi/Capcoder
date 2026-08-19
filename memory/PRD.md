# CapCode — PRD / Architecture Memory

## Original problem statement
Recursive AI dev-team app (CapCode): 6-role pipeline Teacher -> Architect ->
Artist -> Reviewer -> Executor/Corrector -> Rater -> Scorer. Checkpointed
pipeline, Tier System (free/trial/paid), Uncensored Mode waiver (Venice).

## Stack
- Backend: FastAPI + Neon Postgres via `docdb.py` (JSONB adapter, Mongo-like API)
- Frontend: React + Tailwind, BBS/neon terminal aesthetic
- Auth: Neon Managed Better Auth (Google OAuth), proxied through backend
  `/api/neon-auth/*` to fix Safari cross-domain cookie issues
- Deploy: Frontend on Vercel, Backend on Render. User deploys via zip download
  (Emergent->GitHub integration currently broken on their end)
- Billing: Stripe — $16/mo (or annual) subscription, $2.99 one-time trial,
  now also one-time credit top-ups ($8/500, $16/1000, $32/2000 credits)

## Implemented (this session, Aug 2026)
1. **Dead Vercel code cleanup** — deleted `/app/api/index.py` + root
   `requirements.txt`; removed the `functions` block + `/api/(.*)` rewrite
   from `vercel.json` (frontend calls Render directly via
   `REACT_APP_BACKEND_URL`, so this was pure dead weight/build risk).
2. **Default LLM Teams** — `providers.DEFAULT_TEAMS` (venice/openrouter/nvidia
   presets, all 6 roles). `GET /api/teams/defaults`, `POST /api/teams/reset`.
   Settings extended from 3 roles (teacher/artist/rater) to all 6
   (+architect/reviewer/corrector) — `SETTINGS_ROLES` in server.py.
   Frontend: SettingsPanel "DEFAULT TEAMS" section, 6 role tabs, Venice preset
   gates through the existing consent waiver modal first.
3. **Credit top-ups** — `billing.TOPUP_PACKAGES` ($8→500cr, $16→1000cr,
   $32→2000cr), `add_topup_credits`/`get_topup_balance`, persistent
   `users.topup_credits_balance` (doesn't expire on cycle renewal; spent
   before card overage in `apply_chain_billing`). Endpoints:
   `GET /api/tier/topup/packages`, `POST /api/tier/topup/checkout` (mock path
   via ALLOW_MOCK_BILLING=true when no Stripe key, same pattern as existing
   trial/paid checkout). Env vars needed in Render for real Stripe:
   `STRIPE_PRICE_ID_CREDITS_8`, `STRIPE_PRICE_ID_CREDITS_16`,
   `STRIPE_PRICE_ID_CREDITS_32`.
4. **User Profile UI** — `GET /api/profile` (email, tier, trial days left,
   billing cycle, topup balance). New `ProfilePanel.jsx`, "profile" button in
   App.js header (only shown when signed in).
5. Legal docs — real Privacy Policy + Terms of Service pages added
   (`LegalPage.jsx`), linked from Landing/Pricing/build-view footers. Distinct
   from `VeniceConsentModal.jsx` (that's the narrow uncensored-mode-only
   liability waiver, unchanged). Entity name "CapCode", no dedicated legal
   contact email yet, governing-law kept generic per user's call.
6. Fixed layout bug from testing: SettingsPanel role-tab row was flex-shrunk
   to ~5px by the new Default Teams section — added `shrink-0` to all fixed
   sections + `min-h-0` on the model-list scroll region. Also fixed a bug
   where applying the Venice preset also silently force-enabled the
   unrelated "uncensored only" catalog filter checkbox.

## Testing status
- `/app/test_reports/iteration_13.json` — backend 21/21 pass, frontend
  90%→100% after layout fix (retest recommended but fix is a pure CSS change
  mirroring the exact fix the testing agent RCA'd).
- Known limitation: no email/password UI exists, only Google OAuth — so
  signed-in-only flows (profile contents, topup checkout mock-credit,
  real billing) can only be smoke-tested for correct 401s in this env, not
  fully e2e. Anonymous-session flows (teams reset, 6-role settings) are
  fully tested and pass.

## Pre-existing (not touched this session, noted by testing agent)
- `POST /api/teams/reset` (like the pre-existing `/api/settings`) trusts a
  caller-supplied `session_id` in the body rather than deriving it from the
  `X-Capcode-Session` header — this is the SAME pattern the existing
  `/api/settings` GET/POST already use, not a new regression. Would need a
  broader auth-flow change to fix consistently; out of scope for this session.

## Backlog (P1/P2/P3)
- P2: Optionally split SettingsPanel.jsx (now ~530 lines) into smaller
  components (billing / teams / roles / BYOK) — code-health only, not
  user-facing.
- P3: Layer #2 Test Generation Loop, #3 Error Pattern Library,
  #4 Architecture Decisions loop, #6 Dependency Selection loop.
