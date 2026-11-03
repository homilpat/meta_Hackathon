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
