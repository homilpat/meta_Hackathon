# IN3 — Case hand-off (spec v5.8 §23.2, §23.4)

`POST /intakes/{id}/confirm` (AUTHOR, Idempotency-Key) with `base_version` and `action`:

| Rule | Behaviour |
|---|---|
| Explicit confirmation | Upload, analysis or a refused confirm create no case (T01). The person confirms the draft version they saw; an older version → 409 |
| Open items first | A field in CONFLICT (e.g. LOT L02 vs L03) or NEEDS_CONFIRMATION (e.g. "Friday") blocks confirmation until a person resolves it by an edit with a reason |
| `NEW_CASE` | Server id `CC-{intake}`; `origin` (default CUSTOMER_COMPLAINT) separate from `channel` (CHAT_UPLOAD); `owner_id` = the confirming author; `data_origin` SYNTHETIC only if every file is an allowlisted fixture; the author is assigned |
| `LINK_EXISTING` | Access rechecked (`require_case`); a CLOSED case is refused (409, never reopened); existing documents and approvals are untouched |
| Evidence | One `CUSTOMER_DOC` source asset per file, one evidence row per confirmed value (`EV-IN{intake}-{n}`), classification CUSTOMER_REPORTED or HYPOTHESIS (cause guess), raw record with file, locator, page, excerpt and "entered by a person". UNKNOWN files get `sensitivity=UNKNOWN`, so the existing egress gate keeps that case away from the model |
| No copied data | No SPI/AOI/shipment row is created or copied; `internal_data.linked=false` with what is needed |
| Once | One link per intake (unique); a retried confirm replays the response (T06); a second confirm → 409 |
| D0 / Queue | The case starts with D0 PENDING. `/queue` gains `D0_TRIAGE` for the policy's D0 role (owned by the single assigned holder) and `D0_UNASSIGNED` for the case's authors when nobody holds it. D0 uses the existing route: `CUSTOMER_COMPLAINT` signal, customer evidence citable, a customer report alone cannot be `DEFECT_CONFIRMED` |
| Duplicates | `GET /intakes/{id}/duplicates`: own earlier intakes with the same file hash or customer reference and their case; never merged, never blocking |
| Re-read | `GET /cases/{id}/intakes`: origin, channel, owner, D0 state, assignees, internal-data status, linked intakes |

Migration 0020: `quality_cases.origin` (default PROCESS_SIGNAL), `channel` (default MANUAL), `owner_id`;
`intake_case_links` (append-only).

## Checks (`tests/test_intake_in3.py`, 7)

T01, T06, stale confirm, open-item block, T10 re-read, case listing; customer evidence only and no SPC (T12);
Queue D0_UNASSIGNED → assignment → D0_TRIAGE → existing triage route (T13), DEFECT_CONFIRMED refused on a
customer report; T07 (other user 404, reviewer 403, unknown case 404); link to an existing case keeps documents
unchanged, a closed case is refused (T14); duplicate candidates; the agent runs on a customer-data-only case.
