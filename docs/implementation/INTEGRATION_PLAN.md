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
