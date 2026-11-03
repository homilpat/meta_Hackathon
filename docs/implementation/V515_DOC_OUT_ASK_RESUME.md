# v5.15 §30 — customer DOCX output and missing-input resume (2026-11-03)

## Where each requirement lives

| ID | Implementation | Tests |
|---|---|---|
| DOC-OUT-01 register, slots, customer/version/hash, reuse first | `customer_docx.slots`, `register`, `reusable`, `template_out`; `POST /customer-templates` (AUTHOR); tables `customer_templates` (append-only, migration 0031) | `test_v515_customer_docx` |
| DOC-OUT-02 Meta proposes slot -> field as JSON, occurrence vs escape apart, ambiguous = unresolved | `customer_docx.PROMPT`, `schema` (enums: the server's slot ids, `FIELDS` + NONE), `propose` (unknown ids dropped as OUT_OF_RANGE); `POST /customer-templates/{id}/proposals`; `customer_template_proposals` | same |
| DOC-OUT-03 checks, preview with real values and sources, 작성 필요, final blocked | `case_values` (value, source, version, approved per field), `fill_view`, `check_mapping`; `GET /cases/{c}/customer-templates/{id}/preview`; `export?mode=draft|final` (409 on REQUIRED_MISSING / NOT_APPROVED / NO_CONFIRMED_MAPPING; other customer 403; not on the case 403) | same |
| DOC-OUT-04 mapping per customer and form version, reuse, change -> review, export record | `confirm` -> `customer_template_mappings`; a new version with a different slot structure has no mapping (NEEDS_REVIEW); `customer_template_exports` (form version, mapping id, case data version, file SHA-256, sources) + timeline `CUSTOMER_FORM_EXPORTED`; `GET /cases/{c}/customer-exports` | same |
| ASK-RESUME-01 record the missing field, scope, held action; AI points at allowed sources; specific question | `input_requests.start` -> `input_requests` (field, LOT, period, held inputs, question); `suggest` (column ids of the case's files only; headers, no values; masked when protected) ; `POST /cases/{c}/calculations/held`, `POST /input-requests/{id}/suggestions` | `test_v515_input_resume` |
| ASK-RESUME-02 cell answer re-read with location and version; typed value kept as user input | `answer`, `read_cell`: SOURCE_CELL stores file id, SHA-256, sheet, cell, raw and the row's LOT; USER_ENTERED stores who, when, case and LOT; evidence validity `USER_ENTERED` / `SOURCE_CELL`, never CHECKED; a different second value is 409 | same |
| ASK-RESUME-03 re-check, compute only the held action, calculation id, idempotent | `resume`: the file and the cell again, type/unit/range (0, < defective), LOT; `calculations.compute(op="quotient")` gives `CALC-…` with the input evidence ids; `input_events` RESUMED once; repeat answers and resumes return the first result | same |

**UI**
- **Customer forms** (`frontend/src/features/documents/CustomerForms.tsx`, under 문서 및 결재): register, AI proposal, one field per slot with the case value and source, required checkboxes, confirm with a reason, draft/final download.
- **Held calculations** (`frontend/src/features/requests/InputRequests.tsx`, under 요청 · 회신 · 책임): defect rate per LOT, the question, AI source pointers, the answer as a number or a cell, and resume.

## Reproduce

Run from `backend/`.

```
python -m pytest tests/test_v515_customer_docx.py tests/test_v515_input_resume.py       # TEST_DOUBLE
python -m scripts.docx_samples fixtures                                                    # (committed) synthetic forms
python -m scripts.v515_demo --double
QO_EVAL_LIVE_BUDGET_USD=0.3 python -m scripts.v515_demo --live                             # Meta: 3 calls
```

**On screen, customer forms**
1. Open a closed case and go to 문서 및 결재 → 고객사 DOCX 양식.
2. Register `src/app/fixtures/intake/customer_form_A_8d_table.docx` (customer `DEFAULT`).
3. Click AI 매핑 제안 받기, then check each slot's field against its value and source.
4. Confirm with a reason.
5. Download the draft and the final.

**On screen, held calculation**
1. Go to 요청 · 회신 · 책임 → 불량률 계산 and enter LOT `0007`. The calculation is held and the question appears.
2. Ask the AI where the value could be.
3. Answer with the cell (or type 120).
4. Click 확인 후 계산 재개. The result is 2.5 %.

## Results

**LIVE** (muse-spark-1.3; 3 calls, $0.018; `docs/evaluations/ev/v515_demo_LIVE.json`)

- **Form A (table, 8 slots): 7/8 correct.**
  - D4 Root Cause went to the occurrence cause and Escape Point to the escape cause, kept apart.
  - "Approved by" was left unmapped. That is conservative, and the person set it (1 edit).
- **Form B (paragraphs, 6 slots): 6/6 correct.**
  - 비고 (remarks) was left NONE, as the gold mapping has it.
- **Both finals on the closed case:** 200, with mapping v1, the same case data version and their own file SHA-256.
- **The same form A on another case:** filled with that case's own id and LOT, and every missing value shows 작성 필요.
  - The final is 409 and names each missing required value.
- **Form A with a row added:** v2, NEEDS_REVIEW.
- **A form of another customer:** 403.
- **LOT 0007:**
  - Held with the question.
  - Meta pointed at `검사 수량` (column B) of the case's XLSX.
  - The answer B3 was rejected (its LOT is 0008). B2 was accepted.
  - Resume gave 2.5 %: `CALC-…`, defective 3 (CUSTOMER_REPORTED) over inspected 120 (SOURCE_CELL). A second resume gave the same id.

**TEST_DOUBLE**
- Typing 120 gives 2.5 % with source type USER_ENTERED.
- Rejected: 0, 2 (< 3 defective), 120.5, unit kg, wrong row LOT, wrong column (불량 수량).
- 403 for a reviewer and for a user not on the case.
- A duplicate answer is kept once. A different value is 409.
- A replaced original holds the resume. The store is append-only, so the test simulates the replacement by dropping the trigger.

## Not verified

- **Real customer forms:** none were provided. The slot finder knows empty cells right of a label, `Label: ____` lines and `{{…}}`. Forms that use content controls or text boxes are not read.
- **Per-slot formats** (dates, number formats in the customer's style): not handled. Values are written as the case holds them.
- **Protected forms with LIVE:** labels go masked except the language's terms; only synthetic (RAW) forms were run.
- **Period checks:** the period is recorded and shown, but only LOT is compared against a source row.
