# AG5 — Agent-First regression and release verification (spec §22.6, §22.7 AG5, §22.8)

Base: AG4 `c27e47e`, plus the AG5 data-integrity card fix in this commit. Local Windows 11, Python 3.12, Node 24, Chrome headless.

## Results

| Check | Result |
|---|---|
| Backend full `pytest` | 282 passed (261 pre-Agent + 21 agent); no backend code changed after the AG4 run |
| `ruff check .` | All checks passed |
| Frontend typecheck / vitest / build | PASS / 23 passed / bundle committed with LF (identical to the Linux CI build) |
| Fresh DB, twice (`integration_smoke` + `e2e_http`, each on a new Alembic-migrated scratch DB per scenario) | Round 1 and round 2: `integration_smoke` 27/27, `e2e_http` 3/3 each (D0→D8 CLOSED with DOCX/PDF, D6 failure, agent scenario). The same closed-case snapshot hash `9c378117190f7608` both times. |
| GitHub Actions `CI` (backend → frontend → integration on the same SHA) | Green on `061c1c1` (AG0), `42269bf` (bundle LF fix), `438c998` (AG2) and `c65dbf3` (.gitattributes). `5512bc7` (AG3) and `c27e47e` (AG4) were still running when this was written; their result is recorded in the work log, not assumed here. |
| Real browser (headless Chrome 1440 px, uvicorn on a migrated scratch DB, seeded line case + one real agent run) | Agent screen renders the persisted run: plan 9/11, pending review request with server candidates bob/carol, and all 11 step cards bound to server results (case/LOT table with evidence ids, data-integrity counts, SPC chart with first alarm, evidence gaps, Experience Memory, history, 8D stages with the D8 closure reason, DRAFT "승인 아님" card with its audit event, validation WARN with issues, my tasks). The context panel shows stages, evidence quality counts, my task and approval locks. The data-integrity card showed "결과 없음" in the first screenshot; that is fixed here and re-checked. |
| Meta LIVE tool calling | **BLOCKED_NO_CREDENTIALS**: no `MODEL_API_KEY` in the environment or `.env`. Every model path is verified only with the labelled TEST_DOUBLE planner. That is not a LIVE PASS. |

## What was checked

| Requirement | Evidence |
|---|---|
| Existing G0–G10 unchanged | Full backend suite (all pre-Agent tests unchanged, plus 21 agent tests). `e2e_http` D0→D8 CLOSED with DOCX/PDF and D6 failure. `integration_smoke` (`/app`, `/ui`, access, validator, experience, separation of duties, G9, audit chain). |
| Role separation, AG-T12 | `test_agent_ag2::test_run_is_persisted_restored_and_private_to_its_user`, `test_unassigned_user_cannot_run_the_agent_on_a_case`, `test_agent_ag3::test_server_role_check_refuses_a_draft_for_a_reviewer`, `test_reviewer_must_be_a_server_candidate` |
| Task hand-off, §22.10 (2)–(4) | `test_agent_ag3::test_confirmed_review_is_verified_and_handed_to_the_reviewers_own_queue`, plus the agent scenario over HTTP |
| Model failure and manual fallback, AG-T07, §22.10 (7) | `test_agent_ag2::test_model_failure_falls_back_to_the_server_plan` (server plan completes). Frontend `Agent.test` "service down → manual paths" and `App.test` "fallback → 내 할 일". The queues, approvals and manual 8D/document screens need no model (unchanged tests). |
| Agent reply = persisted DB state | Each reply line names the step(s) it was written from, and steps are append-only rows. A hand-off is reported only after re-reading the document (IN_REVIEW with that reviewer PENDING). Tests compare the agent's results with the screens' own routes (`/spc`, `/ncr/1`, `/queue`) and the agent draft with a manual draft (AG-T10). |
| Restart / refresh, AG-T08 | `test_agent_ag3::test_a_pending_decision_survives_a_server_restart`; runs restored by `GET /agent/runs` (backend and frontend tests) |

## Convenience: interactions for one scenario (§22.6)

Scenario: "investigate this case and get the NCR draft to a reviewer", as alice. **Counted from the UI code, not measured
with users.** No time or error-rate figures are claimed; those need a user study.

| Path | Screens | Clicks / keys |
|---|---|---|
| Existing screens | 8: 전문 도구 → SPC → 제조 데이터·증거 → 품질 예측 → 과거 사례 → D0~D8 (+ 과거 사례 검색) → 문서·결재 (NCR 초안 생성, 검증 실행, 검토 요청) → 내 할 일 | 12 clicks |
| Agent | 1 (Agent, context panel visible) | 1 typed goal + Enter, 1 reviewer choice, 1 "검토 요청 보내기" = 3 actions |

The Agent path runs the same server routes and leaves the same document, validation, review and audit records
(AG-T10). The manual path stays available for every step.

## Remaining limits
- Meta LIVE is unverified (no credentials). The LIVE planner code path is the same one exercised with the TEST_DOUBLE, but the real model's tool choices and latency are not measured.
- The offline planner uses keyword intents (Korean/English). Unrecognised goals fall back to status + tasks, which is a read-only answer, and never to a write.
- The browser check is a headless screenshot review, not an automated click-through. Click paths are covered by vitest (jsdom) and the HTTP scenarios.
- Agent runs are per user and per case. A run interrupted mid-step by a crash is marked FAILED, never resumed automatically.
