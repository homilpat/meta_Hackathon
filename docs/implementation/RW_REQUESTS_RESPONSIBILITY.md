# RW — Requests, replies, review and responsibility (spec v5.8 §25)

Module `app/case_requests.py`, migration 0022. Built on existing cases, assignments, policy, Queue and audit log; no
second workflow engine or queue, no outside portal, accounts or mail.

## Case origin (§25.1)

`quality_cases.origin` (CUSTOMER_COMPLAINT / SUPPLIER_NONCONFORMITY / AUDIT_FINDING / INTERNAL_INSPECTION /
RECURRING_ISSUE / OTHER; existing cases PROCESS_SIGNAL) is separate from `channel` (CHAT_UPLOAD / MANUAL / REQUEST_REPLY).
`POST /origin-cases` creates a supplier or audit case by hand (`SN-n` / `AF-n`, owner = creator, D0 pending, no
measurements invented). `case_profiles` (append-only, versioned) hold the origin details:

- supplier: supplier, part, delivery lots, problem, requested measures, reply due, internal owner
- audit: source, reference, finding, standard + version, department, required evidence, correction due

`POST /cases/{id}/profile` adds a version to any case.

## Requests and replies (§25.2)

| Step | Who | Rule |
|---|---|---|
| `POST /cases/{id}/requests` → DRAFT | assigned AUTHOR | items get ids (I1…) with requirement / required evidence / criterion / basis; owner and reviewer must be assigned and different; the same open request on a case → 409; due date must carry an offset (`+09:00`), `due_tz` is the label |
| `/open` → OPEN | creator or owner | registered in the system; nothing is sent outside (`sent_outside=false`) |
| `/submissions` → SUBMITTED | the current owner only | files go through the intake checks and parser (channel REQUEST_REPLY); version n+1, the old one kept; `submitted_by` (outside org/person, `DOCUMENT_STATED`) apart from `registered_by`; a reply during review restarts it |
| `/review-start` → IN_REVIEW | reviewer | |
| `/ai-review` | owner or reviewer | Muse opinion per item SUPPORTED / MISSING / CONFLICTED / NEEDS_HUMAN with locators checked like intake values; SUPPORTED without a source that holds → NEEDS_HUMAN; no provider or no cleared file → all NEEDS_HUMAN (OFFLINE); stored as kind AI, decides nothing |
| `/decisions` → ACCEPTED / NEEDS_REVISION / REJECTED | reviewer, not the registrant | must name the current version and its file hash (stale → 409); reason required |
| `/due` | creator, owner or reviewer | old and new date and the reason recorded |

Accepting a reply is the acceptance of that answer only: gates, actions, effectiveness and closure are unchanged
(tested). Reply files are readable by case members through `/requests/{id}/files/{fid}/content`.

## Responsibility (§25.3)

`responsibility_events` (append-only) records every request step and handover with actor, role, from/to, reason
and target version. Handover (request owner or case owner): proposed → the old holder stays responsible and the new
one gets `HANDOVER_ACCEPT` in 내 할 일 → accept or decline; nothing is overwritten. `GET /cases/{id}/responsibilities`
reads each responsibility from where it is already kept: case owner (+ pending handover), D1 team, approver role per
gate (policy), request owners and reviewers, executors (`EXECUTED` action events), effect verifiers
(`INDEPENDENTLY_VERIFIED`, effectiveness reviewers), with the event history. X-User stays a demo identity.

Queue (`/queue`, existing): `REQUEST_OPEN`, `REQUEST_REPLY` (also after NEEDS_REVISION), `REQUEST_REVIEW`,
`HANDOVER_ACCEPT` (request and case owner), with due date and "기한 초과".

## Checks (`tests/test_requests_rw.py`, 7)

Supplier: request → owner-as-reviewer refused → duplicate refused → open → reply v1 (retry = one version, non-owner
403) → decision before review 409 → AI opinion (invalid source → NEEDS_HUMAN) → NEEDS_REVISION → v2 → stale v1
decision 409 → ACCEPTED with gates unchanged → Queue empty → full event trail → reviewer downloads the original.
Reply during review restarts it; OFFLINE AI review. Audit: profile with standard version and department → overdue
→ handover pending (old owner keeps it, new owner cannot submit) → accept → due change with reason (offset
required) → evidence → ACCEPTED, closure not ready. Case owner handover: decline keeps the owner, accept moves it,
full history. Case scope (non-member 403, unassigned owner 422) and reconnect. Origin details validated (422).
