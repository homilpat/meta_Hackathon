# v5 implementation status

G0–G4 were pushed to `origin/main` at `4dbb03d` (2026-10-28; the earlier "Nothing is pushed" note predates that push).
v5.5 MONOREPO FINAL (root spec; older v5.5 FINAL now in `docs/archive/`) supersedes the v5 spec files for status and order:
PREFLIGHT → G5 → G6 → G7 → G8 → G9 → post-G9 audit → G10 → Meta LIVE → stabilisation.

| Gate | Status | What exists (code / route / test) |
|---|---|---|
| R0 monorepo | see `docs/architecture/REFACTOR_AUDIT.md` | `backend/{src/app,tests,scripts,migrations}`, `frontend/{src,tests}`, 3-area CI; paths in this table are the post-R0 paths |
| G0 audit | BUILT | `docs/implementation/V5_GAP_MATRIX.md`, `docs/implementation/V5_IMPLEMENTATION_PLAN.md` |
| G1 Meta LIVE | **BLOCKED_NO_CREDENTIALS** | `docs/evaluations/META_LIVE_LOG.md`; `/provider` `live_status`; `backend/tests/test_meta_smoke.py` |
| G2 policy / evidence quality / adapters | BUILT | `backend/src/app/policy.py`, `backend/src/app/quality.py`, `backend/src/app/process.py`; `/policies`, `/cases/{id}/gates`, `/evidence-quality`, `/process-context`; `backend/tests/test_v5_g2_foundation.py` |
| G3 D0 / urgent / D1 | BUILT | `backend/src/app/eightd.py`, `backend/src/app/actions.py`; `/triage`, `/urgent-actions`, `/team`, `/actions/{id}/events`; `backend/tests/test_v5_g3_d0_d1.py`; UI "D0~D8 진행" |
| G4 D2 / D3 | BUILT | `backend/src/app/factcheck.py`, `ncr._five_w2h` (5W2H / IS-IS NOT inside the NCR, under the approval hash); `/problem-definition`, `POST /actions` (LOT/panel/board/shipment-row targets); UI: 5W2H card + D3 action button; `backend/tests/test_v5_g4_d2_d3.py`; HTTP check on a live server |
| PREFLIGHT approval-gate unification | BUILT | `eightd.approval_gate` is the one D2–D4 approval decision; `workflow.py` request-review / decision / basis-check / queue / stages consume it (`policy.may_decide` + `can_approve`); `reviews.policy_hash` (migration `0012_preflight_review_policy`); `backend/tests/test_v5_5_preflight.py` |
| G5 D4 hypothesis → experiment → decision | BUILT | `backend/src/app/causes.py` (`CauseHypothesis`, `WhyLink`, `Experiment`, `CausalDecision`, append-only, migration `0013_v5_d4`); `POST/GET /cases/{id}/hypotheses` (6M Fishbone + 5-Why in the GET), `/why-links`, `/experiments`, `/causal-decisions`; D4 stage = `DONE` only with an approved RCA **and** ≥1 CONFIRMED cause (`NO_CONFIRMED_CAUSE` otherwise); UI D4 card; `backend/tests/test_v5_5_g5_d4.py` |
| G6 D5 selection / D6 effectiveness | BUILT | `backend/src/app/effect.py`; D5 options are `actions(stage='D5')` with `cause_ids` + `details` (feasibility, risk, side effects); selection = `PLAN_APPROVED` (D5 approver, every cause CONFIRMED); `POST /effectiveness-plans` only while selected and not executed; D5 `EXECUTED` needs a plan; `POST /effectiveness` (D6 approver) computes baseline vs post from VALID source rows (mean, n, ~95% interval, inspection-condition check) and allows EFFECTIVE only on `MEETS_CRITERIA`; NOT_EFFECTIVE reopens the causes (`REOPENED` decision, history kept); `POST /cases/{id}/synthetic/post-window` generates the SYNTHETIC post-execution lot L04; migration `0014_v5_d5_d6`; UI D5/D6 card; `backend/tests/test_v5_5_g6_d5_d6.py` |
| G7 D7 prevention / D8 closure | BUILT | `backend/src/app/registry.py` (append-only `controlled_documents`: DRAFT → RELEASED by someone else; SYNTHETIC fixtures SOP/FMEA/CP/templates incl. a SITE-B SOP, a restricted FMEA, an expired CUST-X template); `backend/src/app/closure.py`: `/controlled-documents`, `/controlled-documents/revisions`, `.../release`, `/cases/{id}/prevention`, `/closure`, `/closure/acknowledgements`, `/closure/reopen`; D7 DONE only for released, in-effect revisions raised by this case, still current, operators trained, for every policy-required kind (default FMEA + SOP); D8 re-evaluates route stages, open actions, effectiveness on current data, cause evidence quality, D7, customer notification, residual risk, team acknowledgements; snapshot archived with sha256; migration `0015_v5_d7_d8`; UI D7/D8 cards; `backend/tests/test_v5_5_g7_d7_d8.py` |
| G8 validation / RAG / Experience Memory / hybrid Meta | BUILT (offline; LIVE not verified) | `factcheck.validate` is the one claim validator (document creation, `/validate`, model drafts) with codes (LOT/UNIT/VALUE/TEXT_VALUE mismatch, SUPERSEDED_SOURCE, EXECUTION/CAUSE_UNSUPPORTED, DOCUMENT_NOT_CITABLE, INSTRUCTION_IN_TEXT, TEXT_RULE...) and server recomputation (SPI mean, AOI FAIL %, "x of y" counts); `backend/src/app/validation.py`: `TemplateContract` (deterministic selection + rules), `ValidationRun` (document/evidence/policy/template/rules hashes, stale detection), `/documents/search` (pre-filter ACL/site/process/customer/effective, then BM25); `backend/src/app/experience.py`: Experience Memory over the S5 bank + SYNTHETIC fixtures + closed cases, KNOWN / ANALOGICAL / NO_RELEVANT_HISTORY, negative precedents, human decisions (append-only, audited, not approval), revoke → stale, D8 close indexes / reopen revokes; `backend/src/app/taskrouter.py` + `/task-router`; `/evidence-gaps`; hybrid read-only Meta tools (`get_evidence_gaps`, `search_experience`, `search_documents`, role-scoped); migration `0016_v5_g8`; UI Experience card; `backend/tests/test_v5_5_g8.py` |
| A — G8 focused audit | PASS (CI #37 `8577680`) | `docs/implementation/G8_FOCUSED_AUDIT.md`: `TEXT_EXTRA_VALUE` WARN (`factcheck` v5.5-g8.2), Experience `evidence_level` + closed-case reference warning, revoke records the actor, BM25 limits; `backend/tests/test_g8a_validator.py`, `test_g8a_experience.py` |
| G9 Human Docs | PASS (CI #38 `e312c8b`) | `docs/implementation/G9_HUMAN_DOCS.md`: `/edits` (new version, expected hash, same validator, auto validation), `/diff`, `/edit-proposals` (OFFLINE without key, never applied), HUMAN_EDIT approval needs a fresh non-BLOCK validation; `DocEditor.tsx`; `backend/tests/test_g9_docs.py` |
| C — post-G9 audit | PASS (CI #39 `3a4b684`) | `docs/implementation/POST_G9_REFACTOR_PLAN.md`: E2E success/failure in-process and over real HTTP (`scripts/e2e_http.py`, in integration CI); P1 fixed: re-approved upstream document flags downstream approvals BASIS_CHANGED (`impact.flag_downstream`); P0 0, P2 listed |
| E — Meta LIVE | **BLOCKED_NO_CREDENTIALS** | 2026-10-29: `meta_smoke` / `meta_investigate_smoke` exit 2, no network call (`docs/evaluations/META_LIVE_LOG.md`) |
| G10 | PASS (CI #40 `b81edd7`) | `docs/implementation/G10_EXPORT.md`: `export.py` approved-document and closed-case DOCX/PDF, server read-back check of every snapshot field, 409 for drafts/stale/replaced/not closed, `EXPORTED` audit event; UI download buttons; real-HTTP E2E downloads and opens the files |

## Final status (phase F, 2026-10-29)

```text
BACKEND_WORKFLOW: PASS
G8_RELIABILITY: PASS
G9_DOCS: PASS
POST_G9_INTEGRATION: PASS
G10_EXPORT_DEMO: PASS
META_LIVE: BLOCKED_NO_CREDENTIALS (no MODEL_API_KEY; every model path verified only with the TEST_DOUBLE)
SECURITY_LIMITS: demo X-User identities (no authentication), synthetic data only, single-process SQLite,
                 no real deployment, audit chain not externally anchored
DEMO_READY: YES - offline deterministic demo (python -m scripts.e2e_http, or /app on uvicorn); not a LIVE Meta demo
SUBMISSION_READY: NO for a LIVE-Meta claim (E blocked); YES for the offline demo. Submission itself NOT performed.
```

Final local run: pytest 247 passed, ruff 0, Alembic fresh DB upgrade + `alembic check` (no new operations) +
repeat upgrade, vitest 13, tsc 0, vite build 0, integration smoke 24/24, HTTP E2E 2/2 run twice on fresh DBs
(same snapshot `19517fb45ba0de1b`, same 1,770 / 1,681 checked fields), browser download and restart check
(`docs/implementation/G10_EXPORT.md`). Old root `qualityops.db` unchanged (`e39fac5e96ad602b`).

Residual risks: P2 items in `docs/implementation/POST_G9_REFACTOR_PLAN.md` (template C5 WARN, reason minimums differ;
non-English search covers only glossary wording); Hangul statements are not part of the PDF read-back check; the DOCX was not
opened in Word desktop (python-docx and Chrome PDF only); no measured ROI or plant results are claimed.

## Spec §9 acceptance tests now

| # | Status | # | Status |
|---|---|---|---|
| 1 signal → defect | BLOCKED (`test_spc_signal_alone_cannot_be_triaged_as_confirmed_defect`) | 4 LOT A ev / LOT B text | BLOCKED (`test_valid_evidence_id_but_wrong_lot_in_text_is_blocked`) |
| 2 urgent before D1 | ALLOWED (`test_emergency_hold_allowed_after_d0_before_team_and_documents`) | 5 3.2 → 2.1 | BLOCKED (see row below) |
| 3 plan → executed | BLOCKED (`test_plan_without_execution_is_not_containment_done`) | 6 SUSPECT evidence → cause | BLOCKED (`test_suspect_evidence_cannot_prove_a_cause`) | 7 SHAP/AI/precedent → cause | BLOCKED (`test_ai_shap_or_precedent_alone_cannot_confirm`) |
| 8 multiple causes | ALLOWED (`test_inconclusive_without_experiment_and_multiple_causes`) | 19 stale policy | RE-EVALUATED (`test_stale_policy_version_is_reevaluated_at_decision`) |
| 9 unconfirmed cause → D5 | BLOCKED (`test_unconfirmed_cause_cannot_be_selected`) | 10 D6 not executed / small n / changed inspection / late criteria | BLOCKED (`test_selected_is_not_implemented...`, `test_sample_insufficiency...`, `test_changed_inspection_rule...`, `test_criteria_cannot_be_registered...`) |
| 11 D6 failure → D4/D5 reopen | REOPENED, log kept (`test_negative_outcome_reopens_d4_and_keeps_history`) | 12 FMEA claimed, no revision | BLOCKED (`test_fmea_claim_without_a_real_revision_is_not_d7`) |
| 13 D8 open action / no approval / evidence changed | BLOCKED (`test_open_d6_failure_blocks_closure`, `test_changed_evidence_blocks_closure`, `test_signers_and_notification`) | 14 old template / other-site SOP / no access | BLOCKED (`test_document_citations_need_released_in_effect_site_and_access`, `test_template_contract_selection_and_rules`) |
| 5 3.2% → 2.1% | BLOCKED at document creation (`test_wrong_percentage_text_or_value_is_blocked...`) and in a Docs edit (`test_g9_docs::test_wrong_number_other_lot_and_false_execution_or_cause_are_blocked`) | 15, 16 | as before; G9 edits use the same validator |
| 17 no key → manual | PASSES (503, template path) | 18 regression | PASSES (full suite: 247 passed after G10) |
| 20 second process | PARTIAL (adapter + policy selection; documents/approvals not exercised) | 15, 16 | as before (decision 409; AI cannot write documents) |

## Known limits

- All data and every action execution are SYNTHETIC / SIMULATED. Source-DB match is not physical ground truth.
- Evidence quality rules cannot see calibration or time sync (not in the sources): recorded as `NOT_IN_SOURCE`.
- The S6 document routes take their approver role, self-approval rule and prerequisites from the active policy
  (PREFLIGHT). Document approvals read upstream *document* states; containment execution completeness (D3 actions
  independently verified) is a stage/closure condition, not a condition for approving the RCA document.
- Claim numbers are recomputed only for shapes the server can derive from the cited rows (mean SPI volume, AOI
  FAIL %, "x of y AOI inspections", confirmed-defect counts); other values (Cpk, model scores) are reported as
  `NOT_RECOMPUTED`. Regex text rules catch surface patterns only; not every false sentence is caught.
- Experience Memory: no recurrence data in the S5 bank, so bank precedents are never KNOWN; closed cases are
  `NOT_YET_OBSERVED` (no follow-up window). Search glossary `backend/src/app/glossary.py` (ko/ja/zh/en wording → canonical term) is hand-written; no embeddings.
- Meta LIVE: still BLOCKED_NO_CREDENTIALS. The hybrid tools are exercised with the TEST_DOUBLE only.
- NCR template is now `v5.g4` (adds 5W2H / IS-IS NOT claims); stored versions show the template they were built with.
- Affected objects are a snapshot taken when the process context is recorded; contexts recorded before this
  change have LOT/PANEL objects only.
