# AG0 — Agent-First baseline and compatibility (spec §22.7)

Base: `main` at `d24c6b5` (merge of PR #1). Run locally on Windows 11, Python 3.12 `.venv`, Node 24.18, on 2026-10-30.
No product code changed in AG0.

## Baseline results

| Check | Command (from `backend/` or `frontend/`) | Result |
|---|---|---|
| Backend tests | `python -m pytest -q` | 261 passed (7m19s) |
| Lint | `python -m ruff check .` | All checks passed |
| Migrations | `alembic upgrade head` + `alembic check` on a fresh scratch `DATABASE_URL` | head `0016_v5_g8`; `alembic check`: no new upgrade operations (no drift) |
| Frontend types | `npm run typecheck` | PASS |
| Frontend tests | `npm test` | 14 passed (5 files) |
| Frontend build | `npm run build` | PASS; output equals the committed `backend/src/app/static/web` except CRLF/LF (local `core.autocrlf=true`); hashed asset names unchanged |
| CI | GitHub Actions `CI` on `d24c6b5` (run 41006853191) | success (backend, frontend, integration) |
| Meta LIVE | — | BLOCKED_NO_CREDENTIALS (no `MODEL_API_KEY`); unchanged |

Note: the spec's §22.7 says "247 backend / 13 frontend"; the current tree has more tests than that (G9, G10, C and frontend tests added since).
Local setup gap found: an older `.venv` still imported the pre-monorepo root `app/`. `pip install -e "backend[dev]"` fixed it. CI was not affected.

## What Agent-First can reuse (no new domain logic needed)

| Need (§22) | Existing code / route |
|---|---|
| Identity and role | `workflow.make_auth` (X-User), `/me`; role and case checks in `require_role` / `require_case` |
| Case evidence, integrity, ML/XAI, history, gaps, experience, documents | `tools.EvidenceTools` (read-only, egress-gated, role-scoped): `get_case_summary`, `check_data_integrity`, `get_prediction`, `explain_prediction`, `retrieve_historical_cases`, `get_evidence_gaps`, `search_experience`, `search_documents` |
| SPC | `GET /cases/{id}/spc` (`spc.from_items`) |
| 8D state and gates | `GET /cases/{id}/stages`, `GET /cases/{id}/gates` (policy decisions explained per user) |
| Drafts, validation, review, decisions | `POST /cases/{id}/{kind}` (idempotent, claim validator), `POST …/validate`, `POST …/request-review` (policy reviewer check), `POST …/decision` (human only), G9 `/edits`, `/diff`, `/edit-proposals` |
| Queue / handoff | `GET /queue?scope=mine\|department` (REVIEW, BASIS_CHECK, SEND_FOR_REVIEW, WAITING_UPSTREAM, REDRAFT, ANSWER_COMMENT) |
| Export | `GET /cases/{id}/documents/{kind}/export`, `GET /cases/{id}/report/export` (approved / closed only) |
| Audit | `workflow.log` → `workflow_events` + hash chain; `GET /cases/{id}/timeline`, `/audit/verify` |
| Model boundary | `model_provider.MetaProvider` (LIVE only, egress checks), `investigator` bounded tool loop, `taskrouter` (SERVER / MODEL / OFFLINE) |
| Idempotency | `IdempotencyKey` table + `run_idempotent` on every document mutation |

Frontend: `App.tsx` shell with 11 screens under `features/`, shared `api/client.ts` (X-User, Idempotency-Key), `useLoad`, `components/ui.tsx`, existing `Queue` (mine/department).

## Real gaps (what AG1–AG4 must add)

1. **No agent run state.** Nothing stores a goal, a plan, tool steps, or a pause point. §22.4 needs this to survive a refresh (T08). A new migration is needed (0017: runs, plus append-only steps).
2. **No goal → plan → tools orchestration.** `investigator` is a single model loop producing a report, and it returns 503 without a key. §22 needs a planner that also works offline, using server rules (T07).
3. **No allowlisted write path for the agent.** The writes must go through the existing route handlers (draft, validate, request-review) as the signed-in user. There must be no approve, cause-confirm, execute or close tool (T02).
4. **No pause/resume with human confirmation** before a handoff such as review request. The pause must re-read state before resuming (stale = 409/BLOCKED, T05), and a duplicate resume must create no second review (T09).
5. **No scope check.** A goal naming another case, or a LOT the case doesn't have, has to be asked back to the user (T01).
6. **UI:** the default screen is still the dashboard. Missing:
   - the Agent chat with plan, tool cards and composer
   - "승인 대기" as its own menu (the existing queue holds the data)
   - the right-hand case context panel
   - the "전문 도구" group around the existing screens
   - `/agent` in the Vite proxy list

   Layout follows the local Figma Make mock-up `agent_first design/`, which is not committed: every value in it is hard-coded, so only the layout and CSS are reused.

## Not changed / out of scope for AG0
No refactor. No new routes. No migrations. `agent_first design/` stays untracked.
