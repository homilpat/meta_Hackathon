# Phase A — G8 focused audit

MASTER §3. Failing tests were written first; code changed only where a counterexample reproduced.
Tests: `backend/tests/test_g8a_validator.py` (8), `backend/tests/test_g8a_experience.py` (3), plus the existing
`backend/tests/test_v5_5_g8.py` (20).

| MASTER item | Finding | Change |
|---|---|---|
| 1. KNOWN / ANALOGICAL / NO_RELEVANT_HISTORY | kept; already tested (`test_known_prior_response…`, `test_differing_equipment…`, `test_no_relevant_history…`) | none |
| 2. closed case `NOT_YET_OBSERVED` | retrievable by the next case and never KNOWN (KNOWN needs `recurrence == NONE`), but it was returned as a plain `PRIOR_RESPONSE` with no mark that recurrence is unobserved | every match now carries `evidence_level` (`VERIFIED_NO_RECURRENCE` / `EFFECT_VERIFIED_REFERENCE` / `EFFECT_VERIFIED_RECURRENCE_UNKNOWN` / `UNVERIFIED_EFFECT` / `NEGATIVE`); a verified closed case gets the warning "effect verified at D6, recurrence not yet observed; an effect-verified reference case, not a known fix", shown in the UI's 차이 column |
| 3. failed / recurred precedents | warnings only; `REVIEW_PRIOR_RESPONSE` on them is 422; other choices create no action | none (TC-A-02 added) |
| 4. human decision and revocation audit | decisions are logged per case (`EXPERIENCE_<DECISION>`) and hash-chained; the manual revoke endpoint wrote a REVOKED version **without the actor** | the stored reason now ends with `(revoked by <user>)` (the row is append-only and hash-chained) and the response returns `revoked_by`; no migration. Reopen-driven revocation was already logged with its actor by `closure.reopen` |
| 5. validator counterexamples | a sentence holding the right value and a wrong unit-number (`3.2% … 2.1% after rework`) was accepted silently | `factcheck.RULES_VERSION = v5.5-g8.2`: `TEXT_EXTRA_VALUE` (WARN) for unit-numbers the server did not recompute; `TEXT_VALUE_MISMATCH` (BLOCK) unchanged when the value appears nowhere. WARN rather than BLOCK because the server's own template claim C5 ("centre, LCL, UCL mm3", value = centre) has the same shape. Mixed lots, wrong unit, unexecuted execution and unconfirmed cause were already refused; superseded source rows already make validation stale |
| 6. pre-filter before search | document search excludes `OTHER_SITE`, `ACCESS`, `OTHER_CUSTOMER`, `NOT_IN_EFFECT` before BM25; citations check site, ACL and effective period; TemplateContract checks customer and effective period; Experience retrieval rejects by scope / ACL / revocation before ranking | none (existing tests) |
| 7. BM25 limits | see below | documented |

## BM25 + term map limits (`backend/src/app/retrieval.py`, `bm25-k1.5-b0.75-terms1`)

- **English ASCII only** (fixed later by `app/glossary.py`, see `POST_G9_REFACTOR_PLAN.md` #3). The tokenizer kept `[a-z0-9]+`; Korean (or any non-ASCII) wording contributed no terms.
  A Korean-only query still ranks on the case's own structured text, but the user's words are ignored.
- **Hand-made synonym list** (`TERMS`, ~40 entries) for SMT stencil/paste wording; unseen synonyms, misspellings
  and inflections outside it do not match. No stemming.
- **No semantics:** negation ("not clogged") and word order are ignored; a stop-word list drops "no"/"not".
- **Scores are corpus-relative** (IDF over the visible candidates), so they are only used for ordering, never shown
  as a similarity percentage. A match also needs a shared structured factor (SPI pattern or equipment condition);
  AOI FAIL alone is rejected as generic.
- Not measured on real wording. Embeddings / a vector DB are deliberately not added (MASTER §3.7); revisit only with a
  labelled retrieval evaluation.
