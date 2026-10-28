# v5 implementation status

G0–G4 were pushed to `origin/main` at `4dbb03d` (2026-10-28; the earlier "Nothing is pushed" note predates that push).
v5.5 FINAL (`QualityOps_AI_FINAL_REQUIREMENTS_v5_5_FINAL.md`) supersedes the v5 spec files for status and order:
PREFLIGHT → G5 → G6 → G7 → G8 → G9 → post-G9 audit → G10 → Meta LIVE → stabilisation.

| Gate | Status | What exists (code / route / test) |
|---|---|---|
| G0 audit | BUILT | `docs/V5_GAP_MATRIX.md`, `docs/V5_IMPLEMENTATION_PLAN.md` |
| G1 Meta LIVE | **BLOCKED_NO_CREDENTIALS** | `docs/META_LIVE_LOG.md`; `/provider` `live_status`; `tests/test_meta_smoke.py` |
| G2 policy / evidence quality / adapters | BUILT | `app/policy.py`, `app/quality.py`, `app/process.py`; `/policies`, `/cases/{id}/gates`, `/evidence-quality`, `/process-context`; `tests/test_v5_g2_foundation.py` |
| G3 D0 / urgent / D1 | BUILT | `app/eightd.py`, `app/actions.py`; `/triage`, `/urgent-actions`, `/team`, `/actions/{id}/events`; `tests/test_v5_g3_d0_d1.py`; UI "D0~D8 진행" |
| G4 D2 / D3 | BUILT | `app/factcheck.py`, `ncr._five_w2h` (5W2H / IS-IS NOT inside the NCR, under the approval hash); `/problem-definition`, `POST /actions` (LOT/panel/board/shipment-row targets); UI: 5W2H card + D3 action button; `tests/test_v5_g4_d2_d3.py`; HTTP check on a live server |
| PREFLIGHT approval-gate unification | BUILT | `eightd.approval_gate` is the one D2–D4 approval decision; `workflow.py` request-review / decision / basis-check / queue / stages consume it (`policy.may_decide` + `can_approve`); `reviews.policy_hash` (migration `0012_preflight_review_policy`); `tests/test_v5_5_preflight.py` |
| G5 D4 hypothesis → experiment → decision | BUILT | `app/causes.py` (`CauseHypothesis`, `WhyLink`, `Experiment`, `CausalDecision`, append-only, migration `0013_v5_d4`); `POST/GET /cases/{id}/hypotheses` (6M Fishbone + 5-Why in the GET), `/why-links`, `/experiments`, `/causal-decisions`; D4 stage = `DONE` only with an approved RCA **and** ≥1 CONFIRMED cause (`NO_CONFIRMED_CAUSE` otherwise); UI D4 card; `tests/test_v5_5_g5_d4.py` |
| G6 D5 selection / D6 effectiveness | BUILT | `app/effect.py`; D5 options are `actions(stage='D5')` with `cause_ids` + `details` (feasibility, risk, side effects); selection = `PLAN_APPROVED` (D5 approver, every cause CONFIRMED); `POST /effectiveness-plans` only while selected and not executed; D5 `EXECUTED` needs a plan; `POST /effectiveness` (D6 approver) computes baseline vs post from VALID source rows (mean, n, ~95% interval, inspection-condition check) and allows EFFECTIVE only on `MEETS_CRITERIA`; NOT_EFFECTIVE reopens the causes (`REOPENED` decision, history kept); `POST /cases/{id}/synthetic/post-window` generates the SYNTHETIC post-execution lot L04; migration `0014_v5_d5_d6`; UI D5/D6 card; `tests/test_v5_5_g6_d5_d6.py` |
| G7–G10 | NOT STARTED | — |

## Spec §9 acceptance tests now

| # | Status | # | Status |
|---|---|---|---|
| 1 signal → defect | BLOCKED (`test_spc_signal_alone_cannot_be_triaged_as_confirmed_defect`) | 4 LOT A ev / LOT B text | BLOCKED (`test_valid_evidence_id_but_wrong_lot_in_text_is_blocked`) |
| 2 urgent before D1 | ALLOWED (`test_emergency_hold_allowed_after_d0_before_team_and_documents`) | 5 3.2 → 2.1 | NOT YET (G8/G9) |
| 3 plan → executed | BLOCKED (`test_plan_without_execution_is_not_containment_done`) | 6 SUSPECT evidence → cause | BLOCKED (`test_suspect_evidence_cannot_prove_a_cause`) | 7 SHAP/AI/precedent → cause | BLOCKED (`test_ai_shap_or_precedent_alone_cannot_confirm`) |
| 8 multiple causes | ALLOWED (`test_inconclusive_without_experiment_and_multiple_causes`) | 19 stale policy | RE-EVALUATED (`test_stale_policy_version_is_reevaluated_at_decision`) |
| 9 unconfirmed cause → D5 | BLOCKED (`test_unconfirmed_cause_cannot_be_selected`) | 10 D6 not executed / small n / changed inspection / late criteria | BLOCKED (`test_selected_is_not_implemented...`, `test_sample_insufficiency...`, `test_changed_inspection_rule...`, `test_criteria_cannot_be_registered...`) |
| 11 D6 failure → D4/D5 reopen | REOPENED, log kept (`test_negative_outcome_reopens_d4_and_keeps_history`) | 12–14 | NOT YET (G7–G9) |
| 17 no key → manual | PASSES (503, template path) | 18 regression | PASSES (all 122 original tests still pass) |
| 20 second process | PARTIAL (adapter + policy selection; documents/approvals not exercised) | 15, 16 | as before (decision 409; AI cannot write documents) |

## Known limits

- All data and every action execution are SYNTHETIC / SIMULATED. Source-DB match is not physical ground truth.
- Evidence quality rules cannot see calibration or time sync (not in the sources): recorded as `NOT_IN_SOURCE`.
- The S6 document routes take their approver role, self-approval rule and prerequisites from the active policy
  (PREFLIGHT). Document approvals read upstream *document* states; containment execution completeness (D3 actions
  independently verified) is a stage/closure condition, not a condition for approving the RCA document.
- Author claim numbers are not recomputed yet (only lot/unit/superseded checks): claims carry a value but not how
  it was computed, so the server cannot redo it. Structured calculation predicates are G8; editing a draft is G9.
- NCR template is now `v5.g4` (adds 5W2H / IS-IS NOT claims); stored versions show the template they were built with.
- Affected objects are a snapshot taken when the process context is recorded; contexts recorded before this
  change have LOT/PANEL objects only.
