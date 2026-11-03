# Integration plan: spec v5.13 §22–28 (investigation reliability, XLSX intake, responsibility view)

Status: in progress. Each phase is committed only after its own checks pass. Nothing is marked done until it is tested.

## Where each step of a request lives today (reused, not rebuilt)

| Step | Code | API |
|---|---|---|
| Read the request | `agent.classify` (LIVE planner, strict schema), `agent.intents_of` (keyword rules), `agent.server_plan` | `POST /agent/runs` |
| Check it can run | `workflow.require_case` / `require_role`, `eightd.active_policy`, stage `approval_open` / `blocked_by`, `agent.Executor.refuse` (allowlist) | every route |
| Run the tools | `agent.Executor.step` → `AgentStep` (fixed server workflow); `investigator.investigate` + `tools.EvidenceTools` (model picks read-only tools) → `ModelRun` / `ToolCall` | `/agent/runs`, `POST /cases/{id}/investigate` |
| Check the result | `report.validate_report` (citations, recomputation, certainty), `agent.check_polish` / `check_recommendations`, `factcheck` | — |
| Human decision | `workflow` decision routes (`/{kind}/{v}/decision`), triage, `actions.record` (EXECUTED / INDEPENDENTLY_VERIFIED …), effectiveness review | existing routes |
| Record it | `WorkflowEvent` via `workflow.log`, `audit_chain`, `AgentRun` / `AgentStep`, `ResponsibilityEvent` | `/queue`, `/audit`, `/cases/{id}/responsibilities` |
| Intake | `intake.py` (inspect / parse / analyze), `intake_extract`, `intake_case.confirm`, `docparse.parse_xlsx` (cells as elements) | `/intakes/*` |
| Requests and replies | `case_requests.py` (requests, submissions, review, decisions, due, handover, responsibilities) | `/cases/{id}/requests`, `/requests/{rid}/*` |

## Phases (spec §28.1 order)

| Phase | Requirement | Scope |
|---|---|---|
| P1 | REL-FR-04 | Correct the loop evaluation, then re-score the saved 32 runs with the corrected evaluator. Fixes: human verdicts hidden from every tool; first-call order checked apart from the superset check; injection warning vs confirmed claim; separate counts for task success, safe stop, valid report and business completion; the recorded failures fixed as regression cases |
| P2 | REL-FR-01..03 | Server calculations with ids. The model cites a calculation id and the server fills value, unit and inputs. Validation errors as `code, path, category, message, allowed_recovery, retryable`. Bounded repair loop (limits.py), with an early stop on a repeated error. Required items per task contract. A structured injection-warning field |
| P3 | §22 (prompt §2) | Request classes SUPPORTED / NEEDS_INFO / UNSUPPORTED / PARTIAL, plus HUMAN_ONLY and NO_PERMISSION reasons. "응" applies only to the pending proposal. A scope change invalidates the proposal; cancel closes it; resume rechecks permission and version; no duplicate execution |
| P4 | RW-UI-01..06 | `GET /cases/{id}/responsibilities` gains a case summary and per-request and per-action chains (assigned / accepted / executed / verified / decided, with ids, versions and audit links). Statuses: unassigned, handover pending, not executed, effect unverified, overdue, re-review needed. The Requests screen shows them |
| P5 | XLS-IN-01..05 | One synthetic inspection XLSX form: sheet and header preview, a rule-based column mapping that a person confirms, row checks (BLOCK / WARN / INFO), idempotent versioned confirmation into a case, server aggregation through calculation ids, and reconciliation against the PDF/DOCX values (MATCH / MISMATCH / MISSING / AMBIGUOUS / NOT_COMPARABLE) |
| P6 | XLS-IN-06, REL-FR-04, §25.6 | HTTP E2E from real bytes through to DOCX/PDF export and re-reads of DB, Queue and audit. Re-measure the loop (OFFLINE / REPLAY first; LIVE only within the approved budget, about $2.36 left). Final report |

Out of scope (spec §28.7): mail, in-house APIs, company-specific XLSX output, a submission outbox.

## P2 done: the investigation's steps and statuses (REL-FR-01..03)

| Step | Where | Status |
|---|---|---|
| Investigate (the model picks read-only tools, including `calculate`) | `investigator.investigate` | — |
| Structure check (strict JSON Schema; the API holds the model to it) | `REPORT_SCHEMA` | `JSON_ERROR` if broken |
| Evidence, calculation and scope check (ids of this case; `calculation_id` resolved; stale source refused) | `report.validate_report`, `calculations.resolve` | — |
| Required items (one grounded finding; every UNKNOWN has a next check or question; no finding deleted in a repair) | `investigator.required_missing`, `check` | `INCOMPLETE` (rules kept, item missing) |
| Bounded repair: structured errors back to the model, `INVESTIGATION_MAX_REPAIRS` (2), stop on the same errors | `investigator.investigate` loop, `report.structured` | — |
| Re-check | same | `VALIDATED`, or `VALIDATION_FAILED` with every attempt in `model_runs.attempts` |

- **Calculations.** `calculations` table (migration 0026, append-only). The id is derived from case, operation, field, inputs and a hash of the input records. The model's value, unit and inputs are replaced by the server's. A stored report keeps the old `calc` field readable, and test doubles still use it: it is recomputed as before.
- **Data warnings.** A quoted instruction or claim found in the data goes into `data_warnings`, which is checked for ids only, never as a claim.
- **Limits.** Repairs count toward `INVESTIGATION_MAX_ROUNDS`, time and cost limits as before.
- **Not done.** A server-side scan of tool results for instructions, the way intake flags them.

## P3 done: request classes and resume (prompt §2, spec §22)

- `agent.request_class` runs server rules before any planner or tool, for both planners. The class is stored on the run (`agent_runs.request`, migration 0027).

| Class | When | What the agent does |
|---|---|---|
| SUPPORTED | intents found, nothing excluded | runs as before |
| NEEDS_INFO | no intent | asks back (clarify) |
| UNSUPPORTED | mail, messenger, in-house systems | `BLOCKED`: says what cannot be done and the alternative; 0 tools, 0 model calls |
| HUMAN_ONLY | approve, confirm a cause, close, mark an action executed | `BLOCKED`: says who decides and where; 0 tools |
| PARTIAL | supported intents plus any of the above | `confirm_partial`; after yes it runs only the supported part, and the run ends `PARTIAL`, never `COMPLETED` |

- **NO_PERMISSION** is given as a reason up front, for example a draft asked for by a non-AUTHOR. The route still refuses: the label does not replace the check.
- **A generic word alone** ("분석", "이상") no longer starts an investigation without a quality-domain word.
- **Cancel** gives `CANCELLED`, and items not yet run are closed.
- **A scope change** given as an answer to `confirm_scope` or `confirm_partial` voids the earlier confirmation, replaces the old LOT and is checked again.
- **"응"** applies only to the pending token, and a repeated answer is a 409.

## P4 done: responsibility view (RW-UI-01..06)

- `GET /cases/{id}/responsibilities` keeps its earlier fields and adds four more. They are read from the existing records only: requests, ResponsibilityEvent, actions, ActionEvent, EffectivenessResult, DocumentVersion, Review, ApprovalEvent and WorkflowEvent.
  - `summary`: current stage, blocked-by, next action, owner, due date, overdue.
  - `requests`: each request with its states and handover history.
  - `actions`: for each action, who requested it, approved the plan, executed it and verified it; the effect reviews; the action's own audit event ids.
  - `decisions`: for each document version, the approver role, named reviewers or `ROLE_ONLY_UNASSIGNED`, each decision with role, time, reason and hash, `on_current_content`, `RE_REVIEW_NEEDED` and audit events.
- **Requests screen.**
  - A "지금 누가 무엇을" summary card.
  - A "작업별 책임 연결" card per request, action and document version. AI reviews are marked as reference, and links go to D0–D8, 문서 · 결재 and 감사.
  - The old one-line list of executors and verifiers, which mixed actions, is removed.

## P5 done: inspection XLSX (XLS-IN-01..05)

`app/inspection_xlsx.py`, the `inspection_imports` table (migration 0028), routes in `app/intake.py`, and an XLSX check card on the intake screen.

- **Form.** One synthetic reference form (`inspection_results_v1`). The required fields are LOT, inspected quantity and defective quantity. The rule-based mapping version is a hash. Nothing claims real company forms.
- **Preview** (`GET /intakes/{id}/files/{fid}/inspection`) shows:
  - sheets (hidden ones marked), the detected header row and its columns;
  - the suggested mapping, which a person can change and the checks then run again;
  - each row with its cell, raw value, number format and normalized value.
  - It runs within the existing parse time budget, and rows it did not reach are reported as unread. Upload size, zip and macro checks stay at upload.
- **Row checks.**
  - `BLOCK`: MISSING (never 0-filled), NEGATIVE, NON_INTEGER, NOT_A_NUMBER, PRECISION_LOST, FORMULA_NO_CACHE (formulas are never executed), DEFECTIVE_EXCEEDS_INSPECTED.
  - `WARN`: LEADING_ZERO_UNKNOWN (not restored), DATE_AMBIGUOUS, INVALID_DATE, NUMBER_AS_TEXT, DUPLICATE_CANDIDATE (never dropped), UNIT_MIXED.
  - `INFO`: FORMULA_CACHED, LEADING_ZERO_FROM_FORMAT.
- **Confirmation** (`POST /cases/{id}/inspection-imports`).
  - The server re-reads the file. It refuses BLOCK rows, rows that are neither included nor excluded with a reason (so the denominator is explicit), and a changed file hash.
  - The same confirmation again returns the same import. A different one is a new version that supersedes the old.
  - Each included row becomes CHECKED internal-inspection evidence (`EV-XL<import>-<row>`) with file hash, sheet, cells, raw values and the mapping version. It takes the file's own origin and egress tier.
- **Reconciliation** (`GET …/reconciliation?comparable=…`).
  - LOT is MATCH, MISMATCH or MISSING against the customer-reported values, with both locators.
  - Quantities are NOT_COMPARABLE until a person confirms they mean the same over the same scope. Several dated rows for a LOT are AMBIGUOUS.
  - Sums are server calculations (`calculation_id`). The customer's number is never promoted or corrected.

## P6: integrated E2E and checks

- `tests/test_v513_e2e.py::integrated_scenario` runs in process and in `scripts/e2e_http.py` on real uvicorn: PDF+DOCX → manual draft → confirm → D0 → XLSX preview → one blocked row excluded with a reason → idempotent import → reconcile (server sum) → partial agent request → human-only refusal → NCR draft → validate → no export before approval → review → approval → DOCX and PDF export → responsibilities, Queue and timeline re-read.
- Over HTTP the server has no model key, so the investigation loop is not run there. It is covered in process (`tests/test_repair_loop.py`). A LIVE re-measure is separate (budget).

## Requirement → code → test

| ID | Code | Tests |
|---|---|---|
| REL-FR-01 | `calculations.py`, `tools.calculate`, `report.validate_report` | `test_repair_loop` (fill, type, stale) |
| REL-FR-02 | `investigator.investigate` loop, `report.structured`, `INVESTIGATION_MAX_REPAIRS` | `test_repair_loop` (repair, repeat stop, limit) |
| REL-FR-03 | `investigator.required_missing`, `check`, INCOMPLETE, `data_warnings` | `test_repair_loop`, `test_s5_history`, `test_v5_5_g8` |
| REL-FR-04 | `scripts/loop_eval.py` v2 | `test_eval_ev` (fixture holds in every tool, first call, warning vs claim, 11 regressions) |
| §22 request classes | `agent.request_class`, `explain`, resume | `test_request_classes`, `test_agent_ag2`, `test_agent_hybrid` |
| RW-UI-01..06 | `case_requests.chains`, `Requests.tsx` | `test_responsibility_chain`, `frontend/tests/Responsibility.test.tsx` |
| XLS-IN-01..05 | `inspection_xlsx.py`, `intake.add_inspection_routes`, `Intake.tsx` InspectionXlsx | `test_inspection_xlsx`, `frontend/tests/InspectionXlsx.test.tsx` |
| XLS-IN-06, §25.6 | `tests/test_v513_e2e.py`, `scripts/e2e_http.py` | in process and HTTP 7/7 |

## Follow-ups decided on 2026-11-03

- **Protected evidence goes masked, not refused** (user decision).
  - The investigation gives `EvidenceTools` one `egress.Masker` per run. Evidence not approved for external processing goes to the model as tokens (`[T1]`, `[N1]`; the same value gives the same token), and the system prompt explains the tokens.
  - A calculation over a protected input sends its value as a token; the server fills the real value from the calculation id.
  - The final report is unmasked on the server before it is validated and stored.
  - Without a masker (the agent's server reads) protected rows are refused, as before, so the system fails closed.
  - Synthetic line types used by the summary still refuse a protected row, so the summary never carries a raw value.
  - Test: `tests/test_masked_investigation.py`. No protected value appears in any message the model sees, and the stored report has the value.
- **The server scans tool results for instructions.**
  - It uses the same pattern as intake (`intake_extract.INJECTION`), on the unmasked text, which stays on the server.
  - Hits are added to the report's `data_warnings` with `source: SERVER`; the model's own warnings carry `source: MODEL`.
  - The investigation screen shows both, and marks them as text found in the data that was not followed.
- **Company forms are registered by the admin.**
  - `inspection_forms` (migration 0029, append-only): header words per field, required fields (LOT always required) and the number of header search rows.
  - `GET /inspection-forms` returns the forms and a blank template. `POST /inspection-forms` is for `AGENT_ADMIN` only; each change is a new version.
  - The preview picks the registered form that names the most columns (the built-in one on a tie), and a person can switch it. Each import stores the form name and its version hash.
  - Screens: 감사 · 보안 → 검사 결과 XLSX 양식 (blanks to fill), and the form selector on the XLSX card.
