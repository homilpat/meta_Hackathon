# v5 implementation status

Stopped after G4 at the user's request (2026-10-28). Nothing is pushed.

| Gate | Status | What exists (code / route / test) |
|---|---|---|
| G0 audit | BUILT | `docs/V5_GAP_MATRIX.md`, `docs/V5_IMPLEMENTATION_PLAN.md` |
| G1 Meta LIVE | **BLOCKED_NO_CREDENTIALS** | `docs/META_LIVE_LOG.md`; `/provider` `live_status`; `tests/test_meta_smoke.py` |
| G2 policy / evidence quality / adapters | BUILT | `app/policy.py`, `app/quality.py`, `app/process.py`; `/policies`, `/cases/{id}/gates`, `/evidence-quality`, `/process-context`; `tests/test_v5_g2_foundation.py` |
| G3 D0 / urgent / D1 | BUILT | `app/eightd.py`, `app/actions.py`; `/triage`, `/urgent-actions`, `/team`, `/actions/{id}/events`; `tests/test_v5_g3_d0_d1.py`; UI "D0~D8 진행" |
| G4 D2 / D3 | BUILT | `app/factcheck.py`, `ncr._five_w2h` (5W2H / IS-IS NOT inside the NCR, under the approval hash); `/problem-definition`, `POST /actions` (LOT/panel/board/shipment-row targets); UI: 5W2H card + D3 action button; `tests/test_v5_g4_d2_d3.py`; HTTP check on a live server |
| G5–G10 | NOT STARTED | — |

## Spec §9 acceptance tests now

| # | Status | # | Status |
|---|---|---|---|
| 1 signal → defect | BLOCKED (`test_spc_signal_alone_cannot_be_triaged_as_confirmed_defect`) | 4 LOT A ev / LOT B text | BLOCKED (`test_valid_evidence_id_but_wrong_lot_in_text_is_blocked`) |
| 2 urgent before D1 | ALLOWED (`test_emergency_hold_allowed_after_d0_before_team_and_documents`) | 5 3.2 → 2.1 | NOT YET (G8/G9) |
| 3 plan → executed | BLOCKED (`test_plan_without_execution_is_not_containment_done`) | 6–14, 19 | NOT YET (G5–G9) |
| 17 no key → manual | PASSES (503, template path) | 18 regression | PASSES (all 122 original tests still pass) |
| 20 second process | PARTIAL (adapter + policy selection; documents/approvals not exercised) | 15, 16 | as before (decision 409; AI cannot write documents) |

## Known limits

- All data and every action execution are SYNTHETIC / SIMULATED. Source-DB match is not physical ground truth.
- Evidence quality rules cannot see calibration or time sync (not in the sources): recorded as `NOT_IN_SOURCE`.
- The S6 document routes still use their fixed chain; the policy is consulted at the new v5 entry points only.
- Author claim numbers are not recomputed yet (only lot/unit/superseded checks): claims carry a value but not how
  it was computed, so the server cannot redo it. Structured calculation predicates are G8; editing a draft is G9.
- NCR template is now `v5.g4` (adds 5W2H / IS-IS NOT claims); stored versions show the template they were built with.
- Affected objects are a snapshot taken when the process context is recorded; contexts recorded before this
  change have LOT/PANEL objects only.
