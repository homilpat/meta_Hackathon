# AG4 — Documents, G9 editing, approvals, G10 export and D0–D8, end to end (spec §22.5, §22.7 AG4)

AG4 connects the agent to what already exists: D5–D8 closure state, G9 human editing, human approval, G10 export.
It adds no new domain logic and no new write path.

## Changes

| Where | Change |
|---|---|
| `agent.py` `stages` tool | Also returns the server's D8 closure readiness from `GET /cases/{id}/closure`: `state`, `blocks`, `ready`, `closed`. Read-only; the reasons come from the closure policy, not from a model. |
| `agent.py` `exports` tool (new intent `EXPORT`: 다운로드 / 내보내 / 승인본 / pdf / docx) | Lists only what G10 would export now: the latest version of each kind if APPROVED, and the 8D report if the case is CLOSED. These are **links**. The agent never calls the export route; the file is made, re-verified and audited (`EXPORTED`) only when the user clicks. |
| `agent.py` intents (bug fix) | "8D" or "NCR" in a status or export question used to plan a draft write. Now a write needs an explicit ask (초안 / 작성 / 써 줘 / 만들어 / draft / write). This is pinned by `test_only_an_explicit_ask_plans_a_write`. |
| `RunView.tsx` | Export card reuses the existing `ExportButtons` (server 409 text shown as is). The stages card shows the D8 readiness and links to the D0~D8 screen. |
| `scripts/e2e_http.py` | Third scenario: the agent scenario over a real uvicorn on a migrated scratch DB. |

Document editing and Diff stay in the existing G9 editor (`DocEditor`, `/edits`, `/diff`, `/edit-proposals`). The agent
links there and always works on the **latest** version, so a human edit is picked up and an old question about the
previous version is refused as stale.

## End-to-end scenario — `tests/test_agent_ag4.py::agent_scenario` (in process and over HTTP)

1. D0 triage and D1 team are done in the existing routes.
2. Agent: NCR v1 drafted and validated, then it stops for the user (`request_review`).
3. The author edits it in G9, which creates v2 (`HUMAN_EDIT`).
4. Agent again: it validates **v2** and asks about v2. The old question about v1 is answered → **BLOCKED (stale)**.
5. The user confirms bob → the server re-reads: v2 IN_REVIEW, and the hand-off goes to bob.
6. bob approves in the existing decision route. The G9 rule (a fresh non-BLOCK validation) is met by the agent's validation run.
7. Agent "NCR 승인본 PDF로 내보내 줘": the only export offered is NCR v2. There is no report because the case is not CLOSED, and there is no agent write step. Downloading the link returns a real PDF.
8. AG-T11: the agent moves on to the CONTAINMENT draft, and exporting that DRAFT is refused with 409.

Also in the file:
- `test_agent_scenario_in_process`: checks the audit timeline holds DRAFT_CREATED, VALIDATED, REVIEW_REQUESTED, exactly one APPROVE (bob's), EXPORTED and AGENT_RUN.
- `test_status_reports_d5_d8_closure_state_read_only`
- `test_only_an_explicit_ask_plans_a_write`

## Covered by existing tests (unchanged, still passing)
- **AG-T03 (D6 FAIL reopens D4):** `tests/test_c_e2e.py::failure`, plus `scripts/e2e_http.py` "failure D6 NOT_EFFECTIVE". The agent's `stages` tool reads that state; it does not change it.
- **AG-T04 (a wrong number or wrong evidence is blocked):** the one claim validator, `tests/test_g9_docs.py`, `tests/test_g8a_validator.py`. The agent's draft and G9 edits go through the same routes, and a validation result of BLOCK stops the run (`prepare_document` → BLOCKED).

## Verification (local)

| Check | Result |
|---|---|
| `pytest tests/test_agent_ag4.py` | 4 passed (agent tests total: 22) |
| full backend `pytest` | 282 passed |
| `ruff check .` | All checks passed |
| `scripts.e2e_http` (real uvicorn) | 3/3: D0→D8 CLOSED + DOCX/PDF, D6 failure, agent scenario |
| `scripts.integration_smoke` | 27/27 |
| frontend typecheck / vitest / build | PASS / 23 passed / bundle committed (LF) |
