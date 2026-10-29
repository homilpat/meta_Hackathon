# G10 — approved DOCX/PDF export and the single-case demo (MASTER §6, phase D)

Code: `backend/src/app/export.py` (no migration). UI: `frontend/src/components/ExportButtons.tsx`, used on the
documents screen (APPROVED versions) and on the D8 card (CLOSED case).

| Endpoint | Exported only when | Refused (409) |
|---|---|---|
| `GET /cases/{id}/documents/{kind}/export?format=docx\|pdf[&version=n]` | version is APPROVED, last APPROVE names its exact content hash, no newer approved version, latest validation not BLOCK | DRAFT / IN_REVIEW / BASIS_CHANGED / REVALIDATION_REQUIRED / SUPERSEDED / REJECTED, replaced by a newer approval, BLOCK |
| `GET /cases/{id}/report/export?format=docx\|pdf` | latest closure is CLOSED; every document in its snapshot still has the archived hash; audit chain verifies | not closed / REOPENED, snapshot mismatch, broken audit chain |

Report content (from the closure snapshot): closure (who, when, policy, route, snapshot SHA-256), D0–D8 states,
every document version with its status at closure and hash, the claims of each approved D2/D3/D4 document (class,
statement, value, unit, evidence ids) with signers and the hash each one signed, validation result and whether it is
still current, confirmed causes, D3/D5 actions, D6 results, D7 revisions and trained operators, D8
acknowledgements, residual risks, customer notification, audit chain head. Header and footer: case, generator,
time, reference hash, "synthetic data".

**Output ↔ snapshot check (server side).** After writing, the file is read back (DOCX `word/document.xml`, PDF via
pypdf) and every required field must be present; otherwise 500 and no file. Fields: claim ids, values, units,
evidence ids (LOTs), ASCII statements, version labels, approvers, document / snapshot hashes, stage states,
actions, causes, D6 results, D7 revisions, acknowledgements. For case L that is 1,770 fields (report) and 1,681
(NCR v2). This check found a real defect during development: a table row taller than a page (139-claim NCR with
long evidence lists) dropped one line per page break in the PDF. Long evidence lists now continue on extra rows.

DOCX is written with the standard library (OOXML zip: content types, rels, document, core properties with
creator/date/snapshot). PDF uses reportlab (A4, repeating table headers, page footer with the reference hash) with the
built-in Korean CID font `HYSMyeongJo-Medium`.

## Verification

| Check | Result |
|---|---|
| TC-D-01 `test_g10_export::test_closed_case_report_and_approved_document_match_the_snapshot` | DOCX opened with python-docx, PDF with pypdf; snapshot hash, every document version/status/hash, NCR v2 statements/values/evidence, the Docs edit "(all lots)", D0–D8 states, actions, causes, D7 revisions match; 4 `EXPORTED` events; audit ok |
| TC-D-02 `test_unapproved_stale_or_replaced_documents_are_not_exported` | report before closure 409; v2 DRAFT 409; v1 still exportable while current; after v2 approval v1 409 "replaced"; CONTAINMENT `BASIS_CHANGED` 409; refusals are not logged as exports |
| read-back check fires | `test_file_missing_a_snapshot_field_is_not_returned`: a field missing from the file → 500 for DOCX and PDF, nothing logged |
| real HTTP (`scripts/e2e_http.py`, also in integration CI) | fresh scratch DB + uvicorn: success → CLOSED, 4 files downloaded and opened (report DOCX 54 KB / PDF 248 KB, 84 pages; NCR v2 DOCX 31 KB / PDF 152 KB); failure scenario 409; snapshot `19517fb45ba0de1b` identical across runs |
| browser (`/app` on uvicorn, scratch DB) | as bob: D8 card "8D 보고서 PDF" → `L_8D_report_19517fb45ba0.pdf` (application/pdf, 1,770 fields checked); documents screen NCR v1 → "409: NCR v1 was replaced by approved v2"; NCR v2 → DOCX download |
| server restart | same DB after restart: report DOCX, RCA/CONTAINMENT PDF 200, NCR v1 409, audit ok |
| visual | the report PDF opened in Chrome's PDF viewer: title, metadata, D0–D8 table and document table render with wrapping, no clipping on the pages inspected |

Not done: Word desktop rendering (Word automation on this PC stops at a hidden dialog, so the DOCX was checked with
python-docx only). Hangul statements are not part of the read-back comparison (see README).
