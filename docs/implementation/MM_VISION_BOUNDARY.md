# MM — Document understanding and the specialist vision boundary (spec v5.8 §24)

Roles: the server parser extracts structure and locators (`app/docparse.py`, see IN2); Muse reads meaning, captions
and relations (`app/intake_extract.py`, links are `AI_OBSERVATION`); a specialist vision model (P2) will detect,
segment, classify and measure through `app/vision.py`; the server and people control access, schema, numbers,
state and approval.

## Vision adapter contract (`app/vision.py`)

| Part | Contract |
|---|---|
| Request (`POST /vision/requests`, Idempotency-Key) | exactly one of `intake_id` / `case_id`; `file_id`; image `element_id`; `analysis_type` DEFECT_DETECTION / SEGMENTATION / CLASSIFICATION / MEASUREMENT; optional `reported_phenomenon` (kept as CUSTOMER_REPORTED); requester. Access: intake owner, or a case member for a file linked to that case. The image's sha256 is recomputed from the stored bytes and must equal the parsed element's |
| Recorded (`vision_requests`, append-only) | intake, case, file sha256, element, image sha256, page, type, reported phenomenon, requester, status, result |
| Today | no adapter: status `NOT_CONFIGURED`, `result` null, message says there is no detection or measurement and to rely on the customer report and human inspection. `GET /vision/status` says the same |
| Result (P2, `VisionResult`) | analysis id, input sha256, model and version, settings, coordinate system (`IMAGE_PIXELS_TOP_LEFT`), preprocessing, regions (bbox, label, score, measurement with unit and calibration), status, limitations. Validated before storing; a result whose input hash is not the requested image → 502, not stored; `usable()` refuses a result for a replaced image |
| Egress (P2) | a connected adapter may receive only SYNTHETIC files, as for the language model |

Statement types kept apart: `CUSTOMER_REPORTED` (고객 보고), `AI_OBSERVATION` (Muse 문맥 해석, 결함 판정 아님),
`VISION_RESULT` (none yet), `HUMAN_INSPECTION` (existing human verifications).

## Charts

DOCX charts: series, categories and values from the chart part (`source: CHART_CACHE`, total and max computed by the
server); the follow-up implementation opens embedded-workbook stored values and compares each series with the cache,
showing MATCH / MISMATCH / NO_WORKBOOK. Both values are retained on mismatch for human review; no macros or formulas
are executed. See [follow-ups](EGRESS_SHEETS_TABLES.md) and `tests/test_intake_sheets.py`. Charts inside a PDF are pictures (`charts: IMAGE_ONLY`): a number read off
one is refused as a value source (UNVERIFIED); Muse may describe the trend (AI_OBSERVATION, ambiguous when unclear).

## Checks (`tests/test_vision_mm.py`, 4)

NOT_CONFIGURED with input hashes and the customer's report kept separate; image element and access required
(text element, unknown element, other user, both or neither scope, case scope via the link, non-member 403); the
P2 contract with a labelled contract test double (validated, wrong input hash refused, stale result not usable);
a blurred-chart number refused while DOCX chart data is a valid source; coverage per file.
