# IN1 — Upload and originals (spec v5.8 §23.4–23.5)

## What was built

| Item | Where | Behaviour |
|---|---|---|
| Tables | `migrations/versions/0018_intake.py`, `app/db.py` | `intake_records` (owner, channel `CHAT_UPLOAD`, idempotency key) and `intake_files` (**append-only**: bytes, sniffed media type, size, sha256, data_origin, checks, uploader, time) |
| Routes | `app/intake.py` | `POST /intakes` (AUTHOR, Idempotency-Key, 1–5 files as base64 JSON), `POST /intakes/{id}/files`, `GET /intakes`, `GET /intakes/{id}`, `GET /intakes/{id}/files/{fid}/content` (download only, `nosniff`) |
| Type by bytes | `inspect()` | `%PDF-` → PDF (pypdf opens it); a zip with `word/document.xml` → DOCX; anything else 415, whatever the extension |
| Limits | `inspect()` | 10 MB per file → 413; PDF over 50 pages → 413; DOCX over 2000 entries or 50 MB unpacked → 413 |
| Refused | `inspect()` | encrypted PDF/DOCX, corrupt files (422), macro-enabled DOCX (415). Each reason ends with the manual path ("직접 입력해 접수") |
| Flagged, never run or followed | `checks` | PDF `/JavaScript /JS /OpenAction /Launch /EmbeddedFile`; DOCX external relationships and embedded objects |
| Origin | `FIXTURE_HASHES` | SYNTHETIC only if the sha256 equals a shipped fixture in `app/fixtures/intake/`; every other file is UNKNOWN (names and prompts declare nothing) |
| Access | `require_intake` | owner only (404 for anyone else); linked-case members come in IN3 |
| Fixtures | `scripts/make_intake_fixtures.py` | complaint PDF (12 defects with no inspected quantity, "reply by Friday", customer cause guess, instruction in a caption) and supplement DOCX (inspected 480, a conflicting LOT, table and photo); byte-identical on every run |

`python-docx` moved from dev to runtime dependencies; the fixtures ship as package data.

## Checks (`tests/test_intake_in1.py`, 6)

T01 (no case after upload), T06 (retried upload = one intake), T07 (other user: 404, reviewer: 403), T09 (renamed,
corrupt, macro, non-DOCX zip, zip bomb, oversize: refused with reason + manual path, nothing stored), T10 (restored
after reconnect, original byte-for-byte), active content / external links flagged, `intake_files` append-only.
Fresh-DB `alembic upgrade head` (0018) + `alembic check`: clean.
