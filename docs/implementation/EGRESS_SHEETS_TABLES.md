# Follow-ups after v5.8: egress tiers, spreadsheets, PDF tables, scans, time zones

## Egress tiers (`app/egress.py`, migration 0023)

An upload is not an approval to send a file out. Each original file has a tier:

| Tier | When | What leaves |
|---|---|---|
| RAW | a shipped SYNTHETIC fixture, or a file a quality manager (QA_PRODUCTION) approved for external processing | the original text, table cells and images, to Meta |
| MASKED (default for everything else) | not approved | only allowlisted form words (labels, connectives); every other word, number and date becomes a token (`[T3]`, `[N2]`, `[D1]`); no images; no file name. Tokens are mapped back on the server, and the map never leaves. The masked payload that was actually sent is kept on the extraction with its sha256 |
| LOCAL | an in-house model is configured (`LOCAL_MODEL_URL`, `LOCAL_MODEL_NAME`, optional `LOCAL_MODEL_KEY`; OpenAI-compatible, e.g. Ollama or vLLM) and a file is protected | everything goes to that model as is, and nothing leaves the site. Not configured in this repository: the provider class and the routing are in place and tested with a fake endpoint |

Approval: the owner asks (`POST /intakes/{id}/files/{fid}/egress-request`, reason). QA_PRODUCTION sees the
waiting list (`GET /egress-approvals`), may download a file only while it waits, and approves or rejects it with a
reason (`POST /egress-approvals/{fid}`). The person who asked cannot decide. Events are append-only, and evidence
registered from an approved file is `APPROVED_FOR_EXTERNAL`. Setting `intake.MASKED_EGRESS = False` withholds
protected files entirely.

LIVE (`python -m scripts.intake_live_check masked`) gave 7/8. None of the values (reference, LOT, part, phenomenon,
customer) were in the sent payload. The customer's cause guess was missed: that needs the meaning that masking
removes. So masked extraction finds where the fields are; meaning, images and recommendations need RAW or LOCAL.

## Spreadsheets and charts

- XLSX: cells `xlsx:{sheet}!{A1}` with merged span; stored values only (formulas are never evaluated, and a formula
  without a stored value stays empty); hidden sheets read and listed; macro-enabled files refused; external
  links counted, never followed; at most 20,000 cells.
- CSV: cells `csv:r{r}:c{c}`; UTF-8 or CP949; the delimiter is sniffed; plain text without a delimiter is refused;
  at most 20,000 rows.
- Legacy or encrypted Office (OLE container) files are refused with the manual path.
- DOCX charts: the embedded workbook is opened (stored values) and each series is compared with the chart cache.
  The result is `MATCH`, `MISMATCH` (coverage `charts: MISMATCH`, both values shown, a person decides) or
  `NO_WORKBOOK`.

## PDF tables (`docparse-2`)

Text-run positions (pypdf) are grouped into rows and aligned columns, and runs of two or more such rows become
cells `pdf:p{page}:t{t}:r{row}:c{col}`. The text-line locators stay. Coverage `tables: RECONSTRUCTED`, with a note to
check borderless or merged tables against the original.

## Scans and time zones

- A scanned PDF page is sent to Muse as an image when its file may leave (RAW or LOCAL). Its transcription is
  `AI_TRANSCRIPTION`, and a value read from it is `NEEDS_CONFIRMATION`. The parse is never overwritten.
- Request due dates without an offset are read in the request's time zone (`Asia/Seoul`, `KST`, …; `tzdata`) and
  stored with the offset. An unknown zone is refused.

## Checks

`tests/test_egress.py` (masking round trip; masked call without images or file name, values mapped back; approval
flow with role, self-decision and pending-only download; rejection keeps masking; local model gets everything and
the external one nothing; withhold switch), `tests/test_intake_sheets.py`, plus the updates in
`test_intake_in2.py` (scan path, PDF table cells) and `test_requests_rw.py` (zone).
