# Requirement ↔ test traceability

Spec: `QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md` (§9 acceptance cases, §19 R0, §22 Agent-First). Commands run from `backend/` (Python) or `frontend/` (npm).
Status is what was actually executed; `NOT_RUN` / `NOT_IMPLEMENTED` are never counted as passing.

## MASTER §10 cases

| ID | Scenario | Where it is checked | Status |
|---|---|---|---|
| TC-R0-01 | backend import / packaging / health after the move | editable install from `backend/`; full `pytest`; `tests/test_health.py`; OpenAPI and tool-schema comparison (REFACTOR_AUDIT R0-B) | PASS (local, R0) |
| TC-R0-02 | Vite proxy + `/app` + `/ui` | `scripts/integration_smoke.py` (`/app` index + every asset, `/ui`); browser check on uvicorn; proxy list in `frontend/vite.config.ts` | PASS (local): `npx vite` dev server served `/app/` and `src/main.tsx` 200 and proxied `/health`, `/me` to uvicorn :8000 |
| TC-R0-03 | integration gate when backend/frontend CI fails | `.github/workflows/ci.yml`: `integration` `needs: [backend, frontend]`, no path filters | PASS — CI run #34 (`f714321`): `backend` failed (ruff), `frontend` passed, `integration` not run |
| TC-R0-04 | fresh scratch DB migration, old DB protected | `DATABASE_URL=<scratch> alembic upgrade head` + `alembic check`; root `qualityops.db` sha256 prefix `e39fac5e96ad602b` before and after | PASS (local) |
| TC-A-01 | closed case retrieved again, recurrence `NOT_YET_OBSERVED` | `test_g8a_experience::test_closed_case_is_an_effect_verified_reference_not_known`; `test_v5_5_g8::test_closed_case_becomes_searchable…` | PASS (local + CI #37, A) |
| TC-A-02 | failed / recurred prior action chosen | `test_g8a_experience::test_negative_precedent_cannot_be_chosen_as_success_and_choice_is_audited`; `test_v5_5_g8::test_failed_or_recurrent_precedent…`; revocation actor: `test_revocation_records_who_revoked_it` | PASS (local + CI #37, A) |
| TC-A-03 | right and wrong numbers in one sentence | `test_g8a_validator` (8: extra %, bare value + wrong %, value nowhere, rounding not over-blocked, other lot, wrong unit, unexecuted action, unconfirmed cause) | PASS (local + CI #37, A) |
| TC-B-01 | edit → new version + diff + re-validation, approved version unchanged | `test_g9_docs::test_edit_creates_a_new_version…`; `DocEditor.test.tsx`; smoke "G9 edit -> v2", "v1 unchanged"; browser: edit saved as v2 with diff + validation badge | PASS (local + CI #38, B) |
| TC-B-02 | 3.2%→2.1%, other lot, false execution / cause | `test_g9_docs::test_wrong_number_other_lot_and_false_execution_or_cause_are_blocked`; smoke "G9 wrong number blocked" | PASS (local + CI #38, B) |
| TC-B-03 | concurrent edit / edit during review / policy change before approval | `test_g9_docs::test_concurrent_edit_review_and_stale_validation_are_refused`; smoke "G9 stale base refused" | PASS (local + CI #38, B) |
| TC-B-04 | no-key AI proposal + manual edit | `test_g9_docs::test_ai_proposal_is_not_applied…` (OFFLINE 503, manual PASS, TEST_DOUBLE proposal not applied); browser: "AI OFFLINE" shown | PASS (local + CI #38, B) |
| TC-C-01 | success D0→D8 + history choice + Docs edit/re-validation | `test_c_e2e::test_success_d0_to_d8_with_history_and_document_edit`; `scripts/e2e_http.py` (real uvicorn) | PASS (local + CI #39) |
| TC-C-02 | D6 failure / early closure | `test_c_e2e::test_failed_effectiveness_blocks_closure_and_reenters_d4`; `scripts/e2e_http.py` | PASS (local + CI #39) |
| TC-D-01 | approved snapshot → DOCX/PDF, files opened, same LOT/values/versions/approvers | `test_g10_export::test_closed_case_report_and_approved_document_match_the_snapshot`; `scripts/e2e_http.py` (downloads + opens 4 files) | PASS (local + CI #40) |
| TC-D-02 | unapproved/stale/replaced document as final output | `test_g10_export::test_unapproved_stale_or_replaced_documents_are_not_exported`, `::test_file_missing_a_snapshot_field_is_not_returned` | PASS (local + CI #40) |
| TC-E-01 | Meta LIVE real tool call | `scripts/meta_smoke.py`, `scripts/meta_investigate_smoke.py` | BLOCKED_NO_CREDENTIALS (exit 2, no call) |
| TC-F-01 | fresh-DB final demo twice | `python -m scripts.e2e_http` ×2 on new scratch DBs | PASS (local: same snapshot `19517fb45ba0de1b`, 2/2 each) |

## §22 Agent-First

| ID | Scenario | Where it is checked | Status |
|---|---|---|---|
| AG0 | baseline before Agent-First changes (`d24c6b5`) | `docs/implementation/AG0_BASELINE.md`: pytest 261, ruff, fresh-DB alembic head + check, frontend typecheck / 14 tests / build, CI run 41006853191 | PASS (local + CI) |
| AG1 | Agent-First shell: Agent default screen, 내 할 일 / 부서 할 일 / 승인 대기 menus on `/queue`, all 9 existing screens under "전문 도구", case context panel, honest planner label, manual fallback when the agent API is absent | `frontend/tests/App.test.tsx`, `frontend/tests/Agent.test.tsx`; `docs/implementation/AG1_AGENT_UI.md` | PASS (local): typecheck, 22 vitest, build, `scripts.integration_smoke` 24/24 |
| AG2 | server planner + read-only tools; AG-T01 scope ask-back, AG-T06 forbidden tool denied, AG-T07 offline / model failure, AG-T08 restore, AG-T09 run idempotency, AG-T12 user isolation | `backend/tests/test_agent_ag2.py` (8); `scripts/integration_smoke.py` agent checks; `docs/implementation/AG2_READ_TOOLS.md` | PASS (local) |
| AG3 | allowlisted draft/validate, human-confirmed review request with server candidates, await/resume, restart; AG-T02 no agent approval, AG-T05 stale refused, AG-T09 no duplicate review/draft, AG-T10 agent draft = manual draft; §22.10 (1)–(6) | `backend/tests/test_agent_ag3.py` (10); `docs/implementation/AG3_SAFE_WRITES.md` | PASS (local): pytest 279, smoke 27/27, e2e_http 2/2 |
| AG4–AG5, AG-T03/T04/T11, §22.10 (7) | documents/export end to end, release | — | NOT_IMPLEMENTED |

## Frontend tests (`frontend/tests`, vitest)

| Test | Covers |
|---|---|
| `api.test.ts` (4) | X-User header, no idempotency key on GET, fresh Idempotency-Key per mutation, JSON / text bodies, ApiError text for string and structured `detail` |
| `DocEditor.test.tsx` (2) | manual edit sends only changed fields with the exact base hash; AI proposal shown, not applied until accepted |
| `App.test.tsx` (8) | Agent default screen with offline Meta status, honest planner label and fallback → 내 할 일; dashboard + synthetic notice one click away; all existing screens reachable under 전문 도구; user switch reloads as that user and hides author-only actions; refused mutation shows the server error; audit screen; 내 할 일 row → document screen; 부서 할 일 / 승인 대기 read the same `/queue` |
| `Agent.test.tsx` (5) | persisted run restored from `/agent/runs` (plan, recorded steps, DRAFT shown as not approval, denied tool shown as denied, audit ids); review request needs an explicit reviewer and sends the pending token once on a double click; goal sent for the current case with an Idempotency-Key; service down → fallback to manual paths; planner label never says LIVE without verification |

## Spec §9 acceptance cases (existing backend tests)

Mapped in `docs/implementation/V5_IMPLEMENTATION_STATUS.md` per gate (G2–G8 test files). This table will gain one
row per §9 case as phases A–D add or confirm tests.
