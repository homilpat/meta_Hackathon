# v5.8 §23–25 — Implementation and verification status

Status words: **PASS** = implemented and the named check was run and passed; **P2 / NOT_IMPLEMENTED** = out of
this MVP by the spec; **LIMIT** = implemented with a stated limitation. Nothing unrun is counted as passing.

## Requirements

| ID | Requirement | Where | Checked by | Status |
|---|---|---|---|---|
| IN-FR-01 | PDF·DOCX attach in the Agent chat with or without a case; progress/errors | `frontend/src/features/intake/Intake.tsx`, `app/intake.py` | `tests/Intake.test.tsx`, browser capture (Agent with no case), `test_intake_in1.py` | PASS |
| IN-FR-02 | classification, structured extraction, locators, missing/conflict, partial processing | `app/docparse.py`, `app/intake_extract.py` | `test_intake_in2.py`, `test_vision_mm.py`, LIVE `intake_live_check` 8/8 | PASS |
| IN-FR-03 | edit the draft and explicitly confirm into a new case or an existing one | `app/intake.py` (edits), `app/intake_case.py` | `test_intake_in3.py`, `Intake.test.tsx`, e2e_http intake scenario | PASS |
| IN-FR-04 | originals, extraction versions, edits, links audited and restored | append-only `intake_files/_parses/_extractions/_case_links`, `INTAKE_LINKED` audit | `test_intake_in1/2/3.py` (T10, append-only) | PASS |
| IN-FR-05 | D0 / Queue / D2 reuse; customer claims apart from internal facts | CUSTOMER_REPORTED / HYPOTHESIS evidence, `d0_task` in `/queue`, existing triage route | `test_intake_in3.py` (T12, T13), e2e_http | PASS |
| IN-FR-06 | file limits, access, injection/egress, idempotency, manual fallback | `inspect()`, `require_intake`, fixture-hash origin, OFFLINE/FAILED drafts | `test_intake_in1.py` (T09), `test_intake_in2.py` (T08, withheld), retries (T06) | PASS |
| IN-FR-07 | mail intake | — | — | P2 / NOT_IMPLEMENTED |
| IN-FR-08 | automatic case creation by policy | — | — | P2 / NOT_IMPLEMENTED |
| MM-FR-01 | server structure extraction vs Muse understanding; text/table/image/chart provenance | `docparse` locators, `intake_extract` (values only from text/cells/chart data) | `test_intake_in2.py::test_parser_locators…` | PASS |
| MM-FR-02 | captions / surrounding text / product-LOT links to images; ambiguity shown | caption links, duplicates, Muse links as AI_OBSERVATION | `test_intake_in2.py`, LIVE (image linked) | PASS |
| MM-FR-03 | chart source values vs picture reading; coverage; render failure; manual fallback | DOCX chart cache (server totals), PDF charts IMAGE_ONLY, `render_check`, page render 422 fallback | `test_vision_mm.py`, `test_intake_in2.py::test_render…` | PASS (chart cache vs embedded workbook compared: MATCH / MISMATCH shown, `test_intake_sheets.py`) |
| MM-FR-04 | vision adapter contract and NOT_CONFIGURED | `app/vision.py`, `vision_requests` | `test_vision_mm.py` | PASS |
| MM-FR-05 | real vision model, evaluation, results as evidence | — | — | P2 / NOT_IMPLEMENTED |
| RW-FR-01 | supplier / audit / internal origins with fields, existing D0 path | `quality_cases.origin/channel`, `case_profiles`, `/origin-cases` | `test_requests_rw.py`, e2e_http | PASS |
| RW-FR-02 | request card: items, deadline, owner, reviewer, version state | `case_requests` | `test_requests_rw.py` | PASS |
| RW-FR-03 | PDF/DOCX reply upload linked to the request; AI per-item opinion with sources | submissions through the intake pipeline, `/ai-review` | `test_requests_rw.py`, `Intake.test.tsx` (requests screen) | PASS (TEST_DOUBLE / OFFLINE; request review not LIVE-checked) |
| RW-FR-04 | human accept / revise / reject; stale and duplicate blocked; separate from domain approvals | `/decisions` with version + file hash, duplicate check, no gate change | `test_requests_rw.py`, e2e_http | PASS |
| RW-FR-05 | responsibilities, acceptance, handover, audit, Queue sync | `responsibility_events`, handover routes, `/responsibilities`, `request_tasks` in `/queue` | `test_requests_rw.py`, e2e_http audit scenario | PASS |
| RW-FR-06 | outside portal, mail, external systems | — | — | P2 / NOT_IMPLEMENTED |

## Required counterexamples (§23.7)

T01 no case before confirmation · T02 table values and locators (PDF lines, DOCX cells incl. merged header) ·
T03 no rate without an inspected quantity · T04 missing/conflicting quantity, LOT and relative deadline · T05 customer
cause guess stays HYPOTHESIS · T06 double click / retry = one case · T07 other users' intakes and cases ·
T08 caption instruction flagged, UNKNOWN files never sent · T09 encrypted / corrupt / oversize / macro / zip bomb /
scanned page refused or marked with a manual path · T10 restore after reconnect · T11 a requirement or supplement is
not forced into a complaint (classes per file, several allowed) · T12 no copied internal data, internal data
UNKNOWN · T13 D0 through the existing route and Queue · T14 linking never reopens a closed case or changes approved
work. All in `test_intake_in1/2/3.py` and `test_vision_mm.py`.

## Runs

| Command (from `backend/` unless noted) | Result |
|---|---|
| `python -m pytest -q` (MODEL_API_KEY empty) | 337 passed |
| `python -m scripts.integration_smoke` | 27/27 |
| `python -m scripts.e2e_http` (real uvicorn, fresh Alembic DB per scenario) | 6/6, three of them v5.8 |
| `alembic upgrade head` + `alembic check` on a fresh DB (0018–0022) | clean |
| `frontend/`: `npm run typecheck`, `npx vitest run`, `npm run build` | clean, 27 tests, bundle rebuilt |
| headless Chrome on a scratch server: Agent with no case, intake card (OFFLINE draft, coverage, flags) | rendered |
| `python -m scripts.intake_live_check` (Meta LIVE, separate fixture) | 8/8 fields, 8.4 s (META_LIVE_LOG) |

LIVE-checked since (META_LIVE_LOG): request AI review 2/2, PDF+DOCX+scan in one call 3/3, masked (unapproved) extraction 7/8. Follow-ups (egress tiers, XLSX/CSV, PDF table cells, scans, time zones): `EGRESS_SHEETS_TABLES.md`. Remaining limits: DOCX is not rendered (structural locators only); X-User is a demo identity (login with role-based permissions is on the roadmap); the in-house model path is wired but no model is installed here.
