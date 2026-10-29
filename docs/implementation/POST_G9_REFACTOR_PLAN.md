# Post-G9 integration audit (MASTER §5, phase C)

One synthetic SMT line case driven end to end through the API: `backend/tests/test_c_e2e.py` (in-process) and
`backend/scripts/e2e_http.py` (same scenarios against a real uvicorn on an Alembic-migrated scratch DB; also in
`integration-ci.yml`).

| Scenario | Path | Result |
|---|---|---|
| TC-C-01 success | Experience retrieval (KNOWN, `VERIFIED_NO_RECURRENCE`) → `REVIEW_PRIOR_RESPONSE` (creates no action) → D0 triage → D1 team → D2/D3/D4 documents approved → D3 hold executed + independently verified → D4 cause confirmed by experiment + independent decision → D5 cause-linked action → D6 precommitted plan, execution, EFFECTIVE → D7 FMEA/SOP revisions released and deployed with training → Docs edit of the approved NCR (wrong count 422; wording edit → v2 + validation) → closure 409 while D2 is a draft → v2 approved → D3/D4 **BASIS_CHANGED** → closure 409 → basis checks by their approvers → acknowledgements → **CLOSED**; approvals carry the content hash they approved, v2 validation current, audit chain ok, the case is indexed as `NOT_YET_OBSERVED` | PASS |
| TC-C-02 failure | same up to D6 with NOT_EFFECTIVE → D4/D6 not DONE (cause reopened) → closure 409 → new D5 selection on the reopened cause refused → audit chain ok | PASS |

The additional negative cases in MASTER §5 were already covered by existing tests and were re-run in the full
suite: SPC signal alone (`test_spc_signal_alone_cannot_be_triaged_as_confirmed_defect`), legitimate D0 urgent hold
(`test_emergency_hold_allowed_after_d0_before_team_and_documents`), cross-site/customer/ACL leaks
(`test_document_search_filters_before_ranking`, `test_acl_and_scope_are_applied_before_ranking`,
`test_meta_tools_respect_the_callers_access`), SHAP/precedent/model-only D4 (`test_ai_shap_or_precedent_alone_cannot_confirm`),
planned ≠ executed (`test_no_invented_execution…`, `test_selected_is_not_implemented…`), D6 sample / inspection change /
post-hoc criteria (`test_sample_insufficiency_is_inconclusive`, `test_changed_inspection_rule_is_inconclusive`,
`test_criteria_cannot_be_registered_after_execution_or_results`), D7 without a revision or training
(`test_fmea_claim_without_a_real_revision_is_not_d7`, `test_untrained_operator_keeps_d7_open`), D8 with open items
(`test_closure_needs_route_and_every_route_stage`, `test_changed_evidence_blocks_closure`), source/policy change during
approval (`test_source_correction_during_review_blocks_the_stale_approval`, G9 `test_concurrent_edit_review…`),
revoked recommendations (`test_revoked_effect_makes_decisions_stale…`), egress (`test_security.py`).

## Findings

| # | Priority | Finding | Action |
|---|---|---|---|
| 1 | **P1** (fixed) | Re-approving a D2/D3 document (a template re-draft or a G9 edit) left the downstream D3/D4 approvals standing on the old version (`based_on: NCR v1`) with no flag, so D8 could close on a basis nobody re-checked. Source corrections already flagged this; document re-approval did not. | `impact.flag_downstream` (extracted from `impact.reopen`, behaviour unchanged there) is now also called when a version is approved and an earlier version of the same type had been approved: latest approved downstream documents become `BASIS_CHANGED`, logged with the required approver; the existing `basis-check` clears them. Covered by TC-C-01 |
| 2 | P2 | The server's own NCR template claim C5 ("centre, LCL, UCL" in one claim) draws the A-phase `TEXT_EXTRA_VALUE` WARN on every template NCR | keep WARN (approvable). Split C5 into three claims together with the next template version (changes template hashes, so not done in an audit phase) |
| 3 | P2 (fixed after F) | BM25 tokenizer ignored Korean wording (see `G8_FOCUSED_AUDIT.md`) | `backend/src/app/glossary.py`: one canonical term per concept with its Korean / Japanese / Chinese / English wording; non-ASCII words are cut into glossary words longest-first (particles, compounds, no-space scripts), unknown words kept as written; `bm25-k1.5-b0.75-glossary2`; `tests/test_glossary.py` (same top past cases and documents for the same query in 4 languages). Limit: only wording in the glossary is translated; no analyser, no vector DB |
| 4 | P2 | Reason minimums differ (Experience decision 10 chars, Docs edit 5 chars) | harmonise with the next API version; both are enforced server-side |
| 5 | P2 | D5–D8 records are not editable through the Docs workspace (their own append-only approval sources) | by design for G9; G10 renders them read-only from the approved snapshot |

P0 open: **0**. Demo-blocking P1 open: **0**.

## Verification

See `HACKATHON_WORK_LOG.md` (phase C) for the commands and counts of the run recorded with this commit.
