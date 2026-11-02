# Local evaluation (spec §26, v5.10 §26.7): what ran, what did not

Everything here runs locally and for free. Scoring makes **0 network connections and 0 model calls**; `evalkit.no_network` enforces this and records it in every report. There is no LLM judge.

New Muse LIVE calls are **off by default**. They run only when all three of these are present:
- `--live` on the command line
- a confirmed budget in `QO_EVAL_LIVE_BUDGET_USD`
- a configured key

A key on its own never starts a paid call.

**No LIVE trace has been collected under this contract yet. Every model-performance number is therefore NOT_RUN.**

| Mode | Meaning |
|---|---|
| `LIVE` | Trace from the real model (paid, opt-in) |
| `TEST_DOUBLE` | Scripted stand-in: checks the pipeline and the scorer. **Never a model result** |
| `OFFLINE_REAL_CODE` | The product code itself, with no model (parser, server workflow, routes) |
| `NOT_RUN` | Not executed; never reported as a pass |
| `OFFLINE_REPLAY` | How every score is computed: saved traces are re-run through the same code with the recorded replies. A different request marks the trace `STALE_TRACE` |

Data, traces and gold live in `.eval_data/` (git-ignored, or wherever `QO_EVAL_DATA` points). Committed reports in `docs/evaluations/ev/` hold ids, hashes and scores, not document text.

## Commands (run from `backend/`)

```
python -m scripts.cuad_eval prepare --download        # or --from DIR; network only here; hashes pinned
python -m scripts.cuad_eval collect --split heldout --condition A --double     # TEST_DOUBLE, free
python -m scripts.cuad_eval collect --split heldout --condition A --live       # paid: needs QO_EVAL_LIVE_BUDGET_USD
python -m scripts.cuad_eval score                     # offline replay of every saved trace
python -m scripts.fixture_eval                        # synthetic manufacturing files: parser, vision, extraction replay
python -m scripts.fixture_eval collect --live         # paid extraction traces for the fixtures
python -m scripts.agent_eval                          # AgentEvals matchers + paired scenarios
python -m pytest -q tests/test_eval_ev.py             # the evaluation itself is tested (CI runs it)
python -m scripts.e2e_http                            # real uvicorn, from real PDF/DOCX files
```

## A. CUAD (EV-FR-01): `scripts/cuad_eval.py`, manifest `ev/cuad_manifest.json`

### Source and split

- **Data:** CUAD v1 (aok_v1.0), CC BY 4.0.
  - Zenodo `CUAD_v1.zip`, sha256 `88b694d9…`.
  - Official split from `data.zip` at the authors' commit `67faa0e`, sha256 `f8161d18…`.
  - Both hashes are checked on every prepare.
- **Code licence:** the authors' repository states no licence. `evaluate.py` is therefore not copied; its matching rule (Jaccard ≥ 0.5, plus substring matching for Parties) is reimplemented and unit-tested.
- **Subset:** seed 20261102, PDFs of at least 10 pages.
  - dev: 3 contracts from train (408; 223 eligible).
  - held-out: 10 contracts from test (102; 47 eligible).
- **Questions:** 5 categories (Parties, Agreement Date, Governing Law, Expiration Date, Termination For Convenience).
  - 65 questions, of which 14 have no answer.
  - 112 gold spans, of which 96 are found in our parsed PDF text. A question with a span that is not found is left out of the parse-included score and counted separately.
- **Gold handling:** gold is kept in a separate file whose hash is recorded. Collection never reads it, and labels and prompt use only the official question text (tested).

### Conditions

| Condition | What it reads |
|---|---|
| A | HYBRID as the product runs |
| B | HYBRID without the author's contents or heading candidates |
| C | WHOLE on the parsed PDF |
| T | WHOLE on CUAD's own text, with no parser |

All four go through the product's `intake_extract` with a CUAD task; the reading is not copied.

### Metrics (all local)

- Span precision and recall, using the official matching rule at the model's own output.
- Token F1 on answerable questions.
- Correct "no answer" (denominator: questions with no gold answer).
- Evidence validity: the quote is found in the cited element.
- Quotes not found anywhere in the document.
- Schema pass and failure counts.
- Page recall and the round in which the answer page was first read.
- Tokens, cost and seconds.

**Official AUPR / P@80R / P@90R: UNSUPPORTED.** evaluate.py needs n-best candidates with probabilities for every test question. The model returns quotes without calibrated probabilities, and this is a subset.

### Results (held-out, TEST_DOUBLE = BM25 first hit, no model; a floor, not a model result)

| Condition | Span P | Span R | No-answer correct | Page recall | Network | Model calls |
|---|---|---|---|---|---|---|
| A | 0.119 | 0.088 | 0/10 | 0.807 | 0 | 0 |
| B | 0.119 | 0.088 | 0/10 | 0.807 | 0 | 0 |
| C | 0.119 | 0.088 | 0/10 | 1.0 | 0 | 0 |
| T | 0.268 | 0.179 | 0/10 | – | 0 | 0 |

- **Muse LIVE A/B/C/T: NOT_RUN** (no confirmed budget). The plan's estimate is about 50–60 calls, roughly $2–3.
- **Limits:**
  - CUAD has been public since 2021, so the model may have seen it in training.
  - English contracts say nothing about manufacturing complaints, photos, charts or Korean documents.
  - The CUAD score must not be combined with B into one "document accuracy".

## B. Synthetic manufacturing fixtures (EV-FR-02): `scripts/fixture_eval.py`

Truths were written by hand from the generators, and each locator was checked once against the parser. This is **not a manufacturing benchmark**.

| Part | dev | validation | Mode |
|---|---|---|---|
| Parser: coverage, merged header, cells, captions, duplicate photo, chart data and workbook mismatch, scan needs vision, instruction in a caption flagged | 28/28 | 12/12 | OFFLINE_REAL_CODE |
| Vision: request recorded, `NOT_CONFIGURED`, no result, same on re-read | 5/5 | – | OFFLINE_REAL_CODE |
| Model extraction: value, unit, locator, CONFLICT, MISSING, NEEDS_CONFIRMATION, image–caption link, wrong confirmations | NOT_RUN | NOT_RUN | no saved trace |

Earlier LIVE checks (`intake_live.json`, `holdout_live.json`) saved scores, not raw replies, so they cannot be replayed. They stay as reported LIVE summaries.

## C. Agent trajectories (EV-FR-03): `scripts/agent_eval.py`

- **Matcher:** AgentEvals 0.0.9 (MIT, a dev dependency).
  - `superset` for independent reads (legal reorders pass; extra calls are counted).
  - `strict` with exact arguments for writes.
  - Forbidden tools are checked separately.
- **Checks the matcher cannot make**, done in code:
  - the next call uses the earlier result's id/version (e.g. `validate_document.version == create_draft.result.version`);
  - the final state is re-read from the API or DB;
  - no false success.
- **Inputs:** the document reading is fixed (a scripted extraction), so its errors are kept separate.

| Pair (same request, one tool result or state changed) | Variants | Result |
|---|---|---|
| approval state: no doc / DRAFT / IN_REVIEW / REJECTED / APPROVED → create+validate / validate only / no write, wait / v2 / next doc | 5 | 5/5 |
| permission: REVIEWER asks for a draft → DENIED, BLOCKED, 0 documents | 1 | 1/1 |
| stale: document changed after the question → not sent, 0 reviews | 1 | 1/1 |
| tool failure: data integrity fails → ERROR recorded, other reads run, no reply cites it | 2 | 2/2 |
| duplicate: same Idempotency-Key → same run, no new step or document | 1 | 1/1 |
| intake conflict: LOT L02 vs L03 → confirm 409 until resolved, stale version 409; stored LOT = L02 only | 2 | 2/2 |
| inspection: AOI FAIL without a human decision → UNKNOWN / FULL_8D; DEFECT_CONFIRMED → EMERGENCY_FULL_8D | 2 | 2/2 |
| model loop (TEST_DOUBLE): tool error recorded ok=false, uncited evidence is not VALIDATED | 2 | 2/2 |

- **FIXED_SERVER (14/14)** shows that the server rules branch correctly. It is not evidence of autonomous planning.
- **MODEL_LOOP with LIVE: NOT_RUN.**
- **Not evaluated:** whether the wording of a reply or a proposed investigation makes sense. That needs fixed-rubric human review of a sample.

## D. Business state and safety (EV-FR-04): pytest and HTTP

| Must never happen | Tests (state re-read, not only the status code) |
|---|---|
| A case before a person confirms | `test_intake_in1::…no_case_is_created`, `test_intake_in3::test_a_case_needs_a_resolved_confirmed_draft_and_a_retry_makes_one_case`, agent_eval `intake_conflict` |
| Approval without authority or by oneself | `test_s2_workflow::test_author_cannot_approve_and_reviewer_cannot_author`, `test_v5_g2_foundation::test_denied_approval_wrong_role_and_self_approval`, `test_v5_g3_d0_d1::test_only_authorised_role_executes_and_verifier_must_be_independent` |
| Duplicates | `test_intake_in1::test_a_retried_upload_is_one_intake`, `test_agent_ag2::test_same_idempotency_key_returns_the_same_run`, agent_eval `duplicate` and `approval_state/draft_exists` |
| Access to another case | `test_intake_in3::test_others_cannot_confirm_or_link_into_cases_they_cannot_see`, `test_agent_ag2::test_unassigned_user_cannot_run_the_agent_on_a_case` |
| Accepting stale input | `test_s2_workflow::test_stale_version_cannot_be_approved`, `test_agent_ag3::test_a_document_changed_after_the_question_is_not_sent`, agent_eval `stale` and `intake_conflict` |
| False success after a failed API call | agent_eval `permission` and `tool_failure`, `test_agent_ag2::test_model_failure_or_a_broken_plan_is_recorded_and_falls_back_to_the_server_plan` |
| External transfer without approval | `test_egress::test_an_unapproved_file_goes_masked_without_images_and_its_values_come_back_checked`, `test_egress::test_protected_files_can_be_withheld_entirely` |

The HTTP E2E (`scripts/e2e_http.py`, real uvicorn, starting from real PDF/DOCX files) passes 6/6.

## Requirement ↔ code ↔ test

| ID | Code | Test |
|---|---|---|
| EV-FR-01 | `scripts/cuad_eval.py`, `ev/cuad_manifest.json` | `tests/test_eval_ev.py` (matching rule, replay and stale, evidence validity, no leakage) |
| EV-FR-02 | `scripts/fixture_eval.py` | `test_eval_ev.py` (parser truths, vision NOT_CONFIGURED, wrong confirmations caught, NOT_RUN without traces) |
| EV-FR-03 | `scripts/agent_eval.py` | `test_eval_ev.py` (matchers reject a missing read, a wrong argument or a wrong order; every pair) |
| EV-FR-04 | existing routes | the table above |
| EV-FR-05 | `scripts/evalkit.py` (code SHA, parser and evaluator versions, command, mode, budget, no-network count) | `test_eval_ev.py` (LIVE gate, no network) |

The only product change is that `intake_extract.extract(..., task=None)` and `doc_select.select(..., labels=None)` take an evaluation task. The default is exactly the product's intake task (tested), so the measured reading is the real one.
