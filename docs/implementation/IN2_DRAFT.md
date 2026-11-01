# IN2 — Parsing and the intake draft (spec v5.8 §23.3, §24.2)

## Roles

| Who | Does | Where |
|---|---|---|
| Server parser | reads the file: text lines / paragraphs, table cells (grid column, merged span, vMerge), images (sha256, caption link, duplicates), DOCX chart data (series, categories, values, totals from the chart cache), scanned pages, coverage, PDF page render | `app/docparse.py` |
| Muse | classifies documents, proposes field values **with the element ids and excerpts they come from**, links images/charts to text (AI_OBSERVATION), asks only what is missing or contradictory | `app/intake_extract.py` (strict JSON schema `intake_extract`) |
| Server check | keeps a value only if the element exists, is text / a table cell / chart data (never an image), contains the excerpt, and every number of the value is in the excerpt; distinct verified values → CONFLICT (never merged); a relative deadline → NEEDS_CONFIRMATION; nothing computed (no defect rate) | `intake_extract.draft` |
| Person | edits values with a reason (new version; source re-checked or marked "원문 근거 없음"); stale base refused | `POST /intakes/{id}/draft/edits` |

Locators: `pdf:p{page}:l{line}`, `pdf:p{page}:img{i}`, `pdf:p{page}:scan`, `docx:p{i}`, `docx:t{t}:r{row}:c{col}`,
`docx:img{i}`, `docx:chart{i}`. DOCX has no page numbers (it is not rendered: `render: NOT_SUPPORTED`).

Semantic kinds: every value from a customer document is `CUSTOMER_REPORTED`; `customer_cause_claim` is `HYPOTHESIS`;
Muse's image/chart readings are `AI_OBSERVATION`. None becomes an internal fact, a confirmed cause or a defect judgement.

Egress: only files whose bytes match a shipped SYNTHETIC fixture are sent (as element JSON + PNG data URLs, at most 6
images); others are listed as `withheld` (status PARTIAL), and if nothing is cleared there is no call (OFFLINE).
No provider or a model failure gives an empty draft (all MISSING) for manual entry: never example values.

Coverage per file: text / tables (PDF: PARTIAL, text lines only) / images / charts (PDF: IMAGE_ONLY, no source
numbers) / scan (NEEDS_VISION) / render (PDF: OK, PARTIAL, FAILED with the structural fallback; DOCX: NOT_SUPPORTED).

## Routes

`POST /intakes/{id}/analyze` (Idempotency-Key) · `GET /intakes/{id}/draft` · `POST /intakes/{id}/draft/edits`
(`base_version`, changes with reason) · `GET /intakes/{id}/files/{fid}/pages/{n}` (bounded PDF render, 422 with the
fallback on renderer failure, 409 for DOCX) · `GET /intakes/{id}/files/{fid}/images/{element_id}` (owner only).

Tables (migration 0019, append-only): `intake_parses` (elements + coverage per file and parser version),
`intake_extractions` (versioned drafts with mode, status, model, prompt version, raw model output, withheld files,
edits). Dependencies: `pypdfium2` (render).

## Checks (`tests/test_intake_in2.py`, 8)

Value/source checks (wrong number, image as source, unknown locator → UNVERIFIED), LOT conflict across PDF/DOCX
(T04), relative deadline, customer cause guess as HYPOTHESIS (T05), injection caption flagged (T08), no inspected
quantity → no rate (T03), UNKNOWN files never in the payload, nothing cleared → no call, OFFLINE / FAILED → empty draft,
edits versioned with reason / stale base 409 / retry idempotent, owner-only (T07), parser locators (merged cell span,
chart values and total, caption links, duplicate image, scan page, no DOCX page numbers), render OK and the
renderer-failure fallback. All with a TEST_DOUBLE provider; LIVE is checked separately (META_LIVE_LOG).
