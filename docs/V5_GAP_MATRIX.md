# v5 GAP matrix (G0 audit)

Audited 2026-10-28 against the code, not the README. Spec: `QualityOps_AI_FINAL_REQUIREMENTS_v5.md`.

## Repository state at G0

| Item | Observed |
|---|---|
| Branch / HEAD | `main` @ `aafbba3` (= spec's `aafbba37`), tracking `origin/main`, nothing ahead/behind |
| Uncommitted | `web/vite.config.ts` (dev-proxy list missing `/audit`, `/monitoring`, `/reference-models`, `/queue`); the two v5 spec files untracked |
| Python | system 3.10.6 does not satisfy `requires-python >=3.12`; tests run in a local `.venv` on 3.12.8 |
| Tests | `python -m pytest -q` → **122 passed**, 1 warning (starlette httpx deprecation), 53.5 s |
| Lint | `python -m ruff check .` → All checks passed |
| Alembic | single head `0009_audit_chain` (0001 → … → 0009, linear) |
| Meta key | no `.env`, `MODEL_API_KEY` unset → LIVE not runnable here |

## Route map (main.py + workflow.make_router + ml_api.make_ml_router)

`GET /health` · `POST /cases` · `GET /cases/{id}` · `POST|GET /cases/{id}/sources` · `GET /cases/{id}/spc|events|evidence|data-issues` · `POST /monitoring/line-replay` · `GET /synthetic/{seed}`, `/synthetic/line/{seed}`, `/synthetic/{seed}/spi-correction` · `GET /provider` · `GET /reference-models/steel` · `GET /ui` ·
`GET /me` · `GET /cases` · `POST /cases/{id}/assignments` · `POST /cases/{id}/{ncr|containment|rca}` · `GET /cases/{id}/{kind}[/{v}[/html]]` · `POST .../{v}/request-review|decision|basis-check|comments|comments/{cid}/resolve` · `GET /cases/{id}/stages` · `POST /cases/{id}/source-revisions` · `GET /cases/{id}/change-impact` · `POST|GET /cases/{id}/investigations` · `GET /cases/{id}/history|next-evidence|timeline` · `POST /cases/{id}/history/links` · `GET /audit/verify` · `GET /queue` · ML routes in `app/ml_api.py` (`/models`, predictions, XAI).

## Specific inspections

- `workflow.KINDS={ncr,containment,rca}`, `APPROVER={NCR:REVIEWER, CONTAINMENT:QA_PRODUCTION, RCA:PROCESS_ENGINEER}`, `PREREQ={CONTAINMENT:NCR, RCA:CONTAINMENT}`, `STEP={D2,D3,D4}` (workflow.py:44-47). `_based_on` walks PREREQ: drafts may be written ahead, review/approval need every upstream APPROVED. There is **no** path to any containment action before an approved NCR — v5 §2.4 conflict (only documents exist; no action entity at all).
- `DocumentVersion` statuses: DRAFT, IN_REVIEW, INFO_REQUESTED, APPROVED, REJECTED, SUPERSEDED, REVALIDATION_REQUIRED, BASIS_CHANGED. Content is immutable: there is no edit endpoint; a change = new version via `create_doc`. Approval binds to `content_sha256` (Decision.content_sha256 must equal the stored hash). Hash covers case/version/builder/claims/based_on — **not** evidence snapshot, policy, template contract, or rules version.
- `ncr.validate_claims` (used for template and author `extra_claims`): checks class, `DONE_CLAIM` regex, evidence_ids present + known. It does **not** recompute values or check that a lot/board named in the text matches the cited evidence. → spec acceptance #4 (LOT A evidence, LOT B text) and #5 (3.2 → 2.1) are **not blocked** for author claims today.
- `report.validate_report` / `_expected` (model output only): unknown evidence, CALCULATED recompute for mean/sum/count/ratio, causal-certainty / SHAP-as-cause / URL regex, precedent eligibility, failed-action recommendation. Not applied to `extra_claims`.
- Source correction: `impact.import_revision` + `reopen` + `EvidenceDependency` graph → affected docs `REVALIDATION_REQUIRED`, downstream `BASIS_CHANGED`, `ChangeImpact` row. Selective; no full-revalidation fallback when dependency unknown.
- Evidence: `Evidence.validity` only `CHECKED` used by `_evidence`; `DataQualityIssue` rows (MISSING_LOT, LOT_MISMATCH, etc.) are not linked to suitability for D4/D6.
- Egress: `tools.APPROVED`, `MetaProvider.chat` secret/restricted regex, quota 10/h, no mock (503). `ModelRun.mode` LIVE | TEST_DOUBLE.
- Roles: `require_role`, `require_case` (assignment), author cannot decide own doc, reviewer must be assigned and of APPROVER role.
- Audit: append-only triggers on approval_events, workflow_events, doc_comments, audit_chain; hash chain via `audit.chain` on flush.
- Frontend `web/src/App.tsx` (481 lines): stage list, review/approve/basis-check, comments, SPC, ML, history. **No document editing UI**; only comment/decision text inputs.

## FR mapping

Legend: **BUILT** = code + test exist; **PARTIAL** = some behaviour exists, gap noted; **MISSING** = nothing.

| FR | Status | Evidence (file / endpoint / test) | Gap |
|---|---|---|---|
| FR-01 signal ≠ defect | PARTIAL | `app/spc.py`, `POST /monitoring/line-replay` logs `SPC_ALARM`; NCR wording "statistical signal, not a defect finding"; `tests/test_line.py` | No stored signal/defect state per case; nothing blocks marking a signal as a confirmed defect (no such action exists) |
| FR-02 D0 triage, urgent action | MISSING | — | No triage entity/route; containment only as document after approved NCR |
| FR-03 D1 team | PARTIAL | `POST /cases/{id}/assignments`, `Assignment`; self-approval blocked in `decide` | No responsibility, acceptance, due date, required-role check, exception log |
| FR-04 D2 5W2H / IS-IS NOT / DB check | PARTIAL | `ncr.build_claims` (counts per lot, cites evidence); `tests/test_s2_workflow.py` | No 5W2H/IS-IS NOT structure; author claims not cross-checked against DB values/lots |
| FR-05 D3 plan/approve/execute/verify | PARTIAL | `ncr.build_containment` (PROPOSAL, `NOT_EXECUTED` note), approval by QA_PRODUCTION; `tests/test_s6_followups.py` | No execution/verification events, no independence rule, no scope binding to source rows |
| FR-06 D4 hypothesis/experiment/decision | PARTIAL | `ncr.build_rca` (HYPOTHESIS claims, UNCONFIRMED); `report.CAUSAL_CERTAINTY`, `SHAP_AS_CAUSE` | No hypothesis/why/experiment/decision entities |
| FR-07 D5 action selection | MISSING | — | — |
| FR-08 D6 execution/effectiveness | MISSING | (`HistoricalOutcome` has VERIFIED/INSUFFICIENT for synthetic precedents only) | — |
| FR-09 D7 prevention revisions | MISSING | — | — |
| FR-10 D8 closure | MISSING | — | — |
| FR-11 WorkflowPolicy | MISSING | hard-coded `KINDS/APPROVER/PREREQ/STEP` | — |
| FR-12 EvidenceQualityAssessment | MISSING | `Evidence.validity`, `DataQualityIssue` exist as raw inputs | No assessment state, no suitability gate |
| FR-13 structured fact back-check | PARTIAL | `report._expected` recompute for model findings | Not for author/template claims; no lot/date/unit/denominator predicate check |
| FR-14 selective revalidation | BUILT (selective) / PARTIAL | `impact.reopen`, `EvidenceDependency`, `ChangeImpact`; `tests/test_s6_followups.py` | No full-revalidation fallback; policy/template revision not a trigger |
| FR-15 Docs editing, 409 | MISSING | (`decide` returns 409 on stale hash/version) | No draft edit endpoint, no ETag/If-Match, no validation issue locations |
| FR-16 AI read-only, UNKNOWN, egress | BUILT | `app/tools.py`, `app/investigator.py`, `app/model_provider.py`; `tests/test_s3_investigation.py`, `tests/test_security.py` | LIVE never run (no key) |
| FR-17 immutable approval, hash bind | PARTIAL | content-hash approval, append-only `approval_events`; `tests/test_security.py` | Hash does not include evidence/policy/template/rules versions |
| FR-18 TemplateContract | MISSING | `ncr.TEMPLATE_VERSION="s6.1"` constant only | — |
| FR-19 hybrid RAG with ACL | PARTIAL (other domain) | `app/history.py` eligibility filter over synthetic precedents | No SOP/FMEA document registry, no BM25 |
| FR-20 semantic conflict assist | MISSING | — | — |
| FR-21 AI diff proposal | MISSING | — | — |
| FR-22 DOCX/PDF export | MISSING | `GET .../html` render only | — |
| FR-23 queue / multi-case UI | PARTIAL | `GET /queue` (mine/department), `GET /cases`; App.tsx 할 일 | No due dates / escalation |
| FR-24 time/token/cost tracking | PARTIAL | `ModelRun.prompt_tokens/completion_tokens`, `scripts/token_budget.py` | No authoring/edit time, latency, cost |
| FR-25 TaskRouter | PARTIAL | Deterministic builders + server recompute; LLM only in `investigator` | No explicit router; manual path exists (template) when model 503 |
| FR-26 process-neutral core | MISSING | PCB-specific `entity_key` / SPI everywhere | — |
| FR-27 MES/QMS/ERP | MISSING (P2, out of scope) | — | requires site approval |
| FR-28 SSO/MFA/TLS/KMS | MISSING (P2) | `SECURITY.md` lists as not implemented | — |
| FR-29 CRDT / vector / multi-agent | MISSING (P2) | — | — |

## Acceptance tests (§9) at G0

| # | Today | # | Today |
|---|---|---|---|
| 1 signal → defect | N/A (no defect action) | 11 D6 fail reopen | MISSING |
| 2 urgent before D1 | FAILS (no path) | 12 fake FMEA revision | MISSING |
| 3 D3 plan → executed | N/A (no execution) | 13 premature D8 | MISSING |
| 4 LOT A ev / LOT B text | **NOT BLOCKED** for extra_claims | 14 stale template/SOP | MISSING |
| 5 3.2 → 2.1 | **NOT BLOCKED** for extra_claims (no edit path; via new draft) | 15 concurrent edit 409 | PARTIAL (decision 409; no edit) |
| 6 SUSPECT evidence D4 | MISSING | 16 AI changes approved doc | BUILT (AI cannot write docs; drafts need human) |
| 7 SHAP-only cause | PARTIAL (regex in model reports) | 17 no key → manual | BUILT (503, template path) |
| 8 multiple causes | PARTIAL (multiple HYPOTHESIS claims) | 18 regression | BUILT (122 tests) |
| 9 D5 unverified cause | MISSING | 19 policy change | MISSING |
| 10 D6 invalid effect | MISSING | 20 second process | MISSING |

## Risks

1. **Scope**: G1–G10 add ~20 entities. Mitigation: one new module per gate, reuse `WorkflowEvent` for audit, append-only triggers for every event table, no frontend rebuild.
2. **Regression of existing D2/D3/D4 semantics**: new policy is consulted only at new endpoints; old `_based_on` stays.
3. **Hash binding change** (G9) must not invalidate existing approvals: new signature binding stored in new table, old `content_sha256` unchanged.
4. **SQLite-only triggers**: append-only for new tables follows the same `APPEND_ONLY` mechanism.
5. **No Meta key**: G1 can only record `BLOCKED_NO_CREDENTIALS`; any LLM feature (FR-21 proposals) is tested with a TEST_DOUBLE labelled as such.
6. **DOCX/PDF**: no library installed; adding one is a new dependency — justify in G10 or ship a stdlib-only DOCX (zip+XML) and mark PDF as not built.
