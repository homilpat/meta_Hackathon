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

## Follow-ups (2026-11-03, same pattern: the AI picks from the server's options as JSON, the server checks, a person confirms)

- **Slots on real-style forms.**
  - **What the server reads now:** content controls (`w:sdt`, labeled by alias/tag, placeholder detected) and text boxes (`w:txbxContent`, skipping the VML fallback copy) as well as cells and paragraphs.
  - **Uncertain slots:** a "-"/TBD/N/A answer is a slot with `certain: false`. The AI maps it or leaves it NONE, and the server fills it only when it is mapped.
- **Per-slot format.**
  - **How it works:** the AI picks one of `FORMATS` (AS_IS, DATE_ISO, DATE_DOT, DATE_SLASH_US, DATE_SLASH_EU, DATE_KO) from the label's own hint. The server converts the ISO dates in the value, and the preview shows the original beside the converted text.
  - **When it fails:** a value the format cannot take blocks the final (`FORMAT_UNCONVERTIBLE`).
  - **Storage:** formats are stored with the mapping (migration 0032). The fields `d2/d3/d4.approved_on` (dates only) were added for this.
- **Period check.** A SOURCE_CELL answer's row date (the table's 검사일 column) must fall in the request period (`2026-10`, a day, or `A..B`). A row without a date is re-asked. Meta is not involved: this is a server check.
- **LIVE** (4 calls, $0.028), form C (table, content control, text box, an N/A answer, a dated label):
  - 4/6 correct. The content control and the text box were mapped right, and N/A was left alone.
  - "Approval Date"/"Approved by" were left unresolved: the form does not say which approval (D2/D3/D4), and a person chose.
  - Formats were 3/3 forms right (DATE_DOT for "YYYY.MM.DD").

## CI failure of a703ede, and its root cause

- **Symptom:** two new routes, `/cases/{case_id}/customer-templates/{template_id}/preview|export`, looked up the form before checking the case. An unassigned user got 404/422, not 403.
- **Root cause:** case access was enforced by each route calling `require_case` by hand, so any new route could get the order wrong.
- **Fix:**
  - **Guard:** `main.case_guard`, one app-wide dependency, checks the user and the case assignment for every `/cases/{case_id}/...` route before any route code runs.
  - **Measured:** all 86 route × method pairs return 403 for an unassigned user, whatever the body.
  - **Test:** the regression test now covers every method of every case route and fills path values by name. It no longer reads FastAPI internals (`ModelField.type_` broke between versions).
  - **Process:** run the full suite before pushing.

## Not verified

- **Real customer forms:** none were provided. The slot finder now also reads content controls and text boxes. Shapes other than text boxes, headers/footers and footnotes are not read.
- **Number formats:** not offered (no numeric case field is mapped yet). Dates are handled.
- **Protected forms with LIVE:** labels go masked except the language's terms; only synthetic (RAW) forms were run.
