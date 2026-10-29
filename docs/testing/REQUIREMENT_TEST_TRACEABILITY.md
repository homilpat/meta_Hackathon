# Requirement ↔ test traceability

Spec: `QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md` (§9 acceptance cases, §19 R0) and
`prompts/QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md` §10. Commands run from `backend/` (Python) or `frontend/` (npm).
Status is what was actually executed; `NOT_RUN` / `NOT_IMPLEMENTED` are never counted as passing.

## MASTER §10 cases

| ID | Scenario | Where it is checked | Status |
|---|---|---|---|
| TC-R0-01 | backend import / packaging / health after the move | editable install from `backend/`; full `pytest`; `tests/test_health.py`; OpenAPI and tool-schema comparison (REFACTOR_AUDIT R0-B) | PASS (local, R0) |
| TC-R0-02 | Vite proxy + `/app` + `/ui` | `scripts/integration_smoke.py` (`/app` index + every asset, `/ui`); browser check on uvicorn; proxy list in `frontend/vite.config.ts` | PASS (local): `npx vite` dev server served `/app/` and `src/main.tsx` 200 and proxied `/health`, `/me` to uvicorn :8000 |
| TC-R0-03 | integration gate when backend/frontend CI fails | `.github/workflows/ci.yml`: `integration` `needs: [backend, frontend]`, no path filters | PASS — CI run #34 (`f714321`): `backend` failed (ruff), `frontend` passed, `integration` not run |
| TC-R0-04 | fresh scratch DB migration, old DB protected | `DATABASE_URL=<scratch> alembic upgrade head` + `alembic check`; root `qualityops.db` sha256 prefix `e39fac5e96ad602b` before and after | PASS (local) |
| TC-A-01 | closed case retrieved again, recurrence `NOT_YET_OBSERVED` | `test_g8a_experience::test_closed_case_is_an_effect_verified_reference_not_known`; `test_v5_5_g8::test_closed_case_becomes_searchable…` | PASS (local, A) |
| TC-A-02 | failed / recurred prior action chosen | `test_g8a_experience::test_negative_precedent_cannot_be_chosen_as_success_and_choice_is_audited`; `test_v5_5_g8::test_failed_or_recurrent_precedent…`; revocation actor: `test_revocation_records_who_revoked_it` | PASS (local, A) |
| TC-A-03 | right and wrong numbers in one sentence | `test_g8a_validator` (8: extra %, bare value + wrong %, value nowhere, rounding not over-blocked, other lot, wrong unit, unexecuted action, unconfirmed cause) | PASS (local, A) |
| TC-B-01 … TC-F-01 | G9, post-G9, G10, LIVE, final demo | — | NOT_STARTED |

## Frontend tests (`frontend/tests`, vitest)

| Test | Covers |
|---|---|
| `api.test.ts` (4) | X-User header, no idempotency key on GET, fresh Idempotency-Key per mutation, JSON / text bodies, ApiError text for string and structured `detail` |
| `App.test.tsx` (5) | dashboard render with offline Meta status and synthetic notice; user switch reloads as that user and hides author-only actions; refused mutation shows the server error; navigation to the audit screen; queue row → document screen |

## Spec §9 acceptance cases (existing backend tests)

Mapped in `docs/implementation/V5_IMPLEMENTATION_STATUS.md` per gate (G2–G8 test files). This table will gain one
row per §9 case as phases A–D add or confirm tests.
