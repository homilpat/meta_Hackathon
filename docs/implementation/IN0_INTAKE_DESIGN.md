# IN0 — Intake design check (spec v5.8 §23–25)

Baseline: `fc75797` (spec v5.8). Code unchanged since `a014d86` (last full run at `efe4b7d`: pytest 303, smoke 27/27,
e2e 3/3, frontend 25; CI green through `a014d86`).

## What the existing code gives the intake path

| Area | Today | Consequence for §23 |
|---|---|---|
| `POST /cases` | AUTHOR only; client picks `case_id`; `domain` PCB and `data_origin` SYNTHETIC only; no idempotency | Intake needs its own create-and-link route: server-generated id, Idempotency-Key, atomic link (T01, T06) |
| D0 | `TriageIn.signal_kind` already has `CUSTOMER_COMPLAINT`; routes `NCR_ONLY / FULL_8D / EMERGENCY_FULL_8D` | Reused as is; a new case starts with D0 not done |
| Queue | Only document review/approval tasks | A "D0 판정 대기" task must be added, or new cases never show up in 내 할 일 (T13) |
| Responsibility | `team_events` ASSIGN / ACCEPT / DECLINE / EXCEPTION | Reused for §25.3 hand-over |
| Egress | Data leaves only when source rows are `SYNTHETIC` / `APPROVED_FOR_EXTERNAL` (`tools._rows`, provider `RESTRICTED_PATTERN`) | Uploaded files need an origin rule (decision 2) |
| Parsers | `pypdf` (runtime), `python-docx` (dev only), `lxml`, `PIL` | Move `python-docx` to runtime |
| Upload | No `python-multipart` | Decision 1 |
| Rendering | No PDF or DOCX renderer | Decision 4 |

## Decisions (user, 2026-11-01)

1. **Transport:** JSON body with base64 file content (no new dependency), 10 MB per file limit.
2. **Egress:** a file is `SYNTHETIC` only if its sha256 is in the server's fixture allowlist (the same rule as the
   exact-match synthetic bundle). Every other upload is `UNKNOWN`: stored and parsed locally, never sent to Meta;
   manual intake still works. File names and prompts cannot declare SYNTHETIC.
3. **Model capability (LIVE probe, 2 calls, see META_LIVE_LOG):** muse-spark-1.3 read a synthetic PNG through an
   `image_url` data-URL part (1.9 s) and a synthetic PDF through a `file` part (4.1 s); LOT, quantity and reference
   were read correctly in both. Only this was verified: not scanned PDFs, tables, multi-page files or DOCX.
4. **Rendering:** PDF pages rendered with `pypdfium2` (one wheel, no system install) in a resource-limited step;
   DOCX rendering is NOT_SUPPORTED. DOCX keeps structural locators (paragraph / table-row-cell / image id), and no page
   number is invented.
5. **OCR:** no OCR library. A scanned page goes to Meta as a page image when the file may leave (decision 2). Otherwise
   it is marked unprocessed and manual entry is offered.

## Logical model (IN1–IN3)

- `intake_records`: intake id, owner, channel `CHAT_UPLOAD`, created_at. Access: owner, then the assigned users of a linked case.
- `intake_files` (append-only): file name, sniffed media type, size, sha256, bytes, data_origin, uploaded_by/at.
- `intake_extractions` (append-only, versioned): document classes, fields, coverage, parser / model / prompt
  version, mode (LIVE / TEST_DOUBLE / OFFLINE). User edits are a new version with who / when / why. Each field
  value carries `source_id`, hash, locator, excerpt and status.
- `intake_case_links` (append-only): intake ↔ case, NEW or EXISTING, who / when, idempotency key.

## Gate order

IN1 upload/original → IN2 analysis/draft → IN3 case hand-off (D0, Queue, D2) → IN4 integration → MM document
elements / tool boundary (vision NOT_CONFIGURED) → RW requests/replies/responsibility → final LLM agent design.
