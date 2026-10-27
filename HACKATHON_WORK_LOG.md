# Hackathon work log

## 2026-10-27 KST — S0

- Created a new local Git repository in `qualityops-ai`; no old prototype source copied.
- Implemented FastAPI `/health`, SQLite/Alembic baseline, pytest checks, Ruff and GitHub Actions workflow.
- Added an optional fixed synthetic Meta structured-response LIVE smoke with redacted output. Official documentation lists `muse-spark-1.3`; account access remains unverified until a successful call.
- Checked PHME repository access/license description. Raw archive password and required usage/egress rights were not available; selected labeled synthetic fallback for S1.
- `python -m venv .venv`: exit 0, using Python 3.12.14.
- `.venv/Scripts/python -m pip install -e '.[dev]'`: exit 1. Package index access was denied (`WinError 10013`), so no application dependencies were installed.
- `.venv/Scripts/python -m compileall -q app scripts tests migrations`: exit 0.
- Direct standard-library smoke contract check (`parse_answer` and blank `read_key`): exit 0. An earlier one-line check failed because PowerShell quoting corrupted its JSON argument; the corrected check passed.
- `.venv/Scripts/python -m scripts.meta_smoke`: Python exit 2, `LIVE NOT TESTED: MODEL_API_KEY is unset`. No provider request was made.
- `.venv/Scripts/python -m pytest -q`, `-m ruff check .`, `-m alembic upgrade head`: each exit 1, modules unavailable after the install failure. Importing `app.main` also exited 1 (`ModuleNotFoundError: fastapi`). `/health` runtime and migration execution remain unverified.
- GitHub Actions CI: workflow authored; no remote repository or CI run exists, so CI status is **NOT RUN**.
- `git check-ignore .env .venv`: exit 0; both local secret file and environment are ignored.
- G0 result: **PARTIAL**. Dependency installation, automated tests, runtime `/health`, migration, CI, and LIVE Meta call remain unverified.
- Implementation commit: `99d152d` (`Build S0 clean-room foundation and record access gates`).

## 2026-10-27 KST — S0 follow-up

- Evaluated the official PHM Society 2018 ion-mill challenge as requested. It cannot supply PCB SPI/AOI/operator events, and raw access plus reuse/egress rights remain unverified. Documented this distinct source and kept the synthetic PCB fallback.
- Python package downloads were blocked (`WinError 10013`) despite the approved `curl` transport working. Downloaded dependency wheels into an untracked local folder outside this repository, then ran `.venv/Scripts/python -m pip install --no-index --find-links ../wheels_s0 -e '.[dev]'`: exit 0.
- `.venv/Scripts/python -m pytest -q`: exit 0, **4 passed, 1 Starlette TestClient deprecation warning**.
- `.venv/Scripts/python -m ruff check .`: exit 0, all checks passed.
- `.venv/Scripts/python -m alembic upgrade head`: exit 0, revision `0001_s0` applied to ignored local SQLite database.
- Ran Uvicorn on `127.0.0.1:8765`; `curl.exe -sS -i http://127.0.0.1:8765/health` returned HTTP 200 and `{"status":"ok","stage":"S0"}`. Stopped the local server afterward.
- Meta LIVE call: **NOT TESTED**; `.env` remains empty. No mock call was made.
- Local follow-up commit: `9b6a615`. Published the same S0 files to the user-specified GitHub `main` while preserving its 2026-10-27 initial commit. Remote S0 commit: `92109cbd24d372d03d14580f7875e5f3a7f6b2e9` (different SHA because the initial local and remote histories were separate).
- [GitHub Actions run 40433263681](https://github.com/homilpat/meta_Hackathon/actions/runs/40433263681) for that remote commit: **success**. Remote tree contains the 20 S0 tracked files; `.env`, SQLite DB, and downloaded wheels are absent.
- G0 acceptance: **PASS via the documented LIVE-unconnected blocker path**. Actual Meta account access remains unverified until a key is provided and the synthetic-only smoke exits 0. PHM 2018 raw-use rights remain unverified; no real dataset is in this repository.
- Remote repository is currently private; public visibility is a later submission requirement and was not changed in S0.

## 2026-10-27 KST — S1

- Started from remote `main` at `e957f1a72dc02b1ae3a7fb7f43587c91005c4f8b`; no older prototype files imported.
- Implemented seeded, explicitly synthetic PCB multi-source generator and source/asset/event/evidence/issue persistence with composite manufacturing keys and v1/v2 source hashes. Added minimal case upload and inspection APIs. Synthetic historical rows carry reported but `UNVERIFIED` outcomes; no retrieval or agent behavior exists.
- UCI Steel Plates Faults official page: 1,941 defect examples, 27 features, seven fault types, CC BY 4.0. Downloaded the ZIP to a temporary local file, verified 1,941 rows of 34 values and exactly one active fault label per row, recorded SHA-256 in `docs/UCI_STEEL_PLATES.md`, then deleted the ZIP. No real row was ingested or committed. Added adapter interface only. PHME/PHM 2018 restrictions remain as previously documented.
- Clean S1 clone setup: `python -m venv .venv` exit 0; offline local wheelhouse `pip install --no-index --find-links ../wheels_s0 -e '.[dev]'` exit 0. Wheels are outside Git.
- `python -m pytest -q`: exit 0, **19 passed, 1 Starlette TestClient deprecation warning**. Includes the four original S0 checks.
- `python -m ruff check .`: exit 0; `python -m alembic upgrade head`: exit 0; `python -m alembic check`: exit 0, no schema drift.
- Live local HTTP: `POST /cases` 201, `POST /cases/DEMO-1/sources` 201 with 12 assets / 42 events / five distinct issue types; `GET /data-issues`, filtered `/events`, `/sources`, `/evidence` returned 200. Source count 12 and evidence count 42. Local server stopped after the smoke.
- Meta API: **NOT TESTED** (S1 does not call it; `.env` is ignored and local only).
- S1 implementation commit: `33a775b` (`Implement S1 synthetic PCB sources and evidence lineage`). Staged secret scan and `git diff --cached --check` found no matches/errors; UCI ZIP and synthetic output were absent from the commit.
- First S1 GitHub Actions run [40435213984](https://github.com/homilpat/meta_Hackathon/actions/runs/40435213984): **FAILED**. Install, pytest, Ruff, and Alembic passed; the final CI smoke still asserted the S0 health-stage string. Updated that assertion to S1; a fresh run is required before G1 can be reported as green.
- Corrected S1 GitHub Actions run [40435309636](https://github.com/homilpat/meta_Hackathon/actions/runs/40435309636) for commit `34d9edb`: **SUCCESS**. All steps including the S1 health smoke passed. G1 is PASS on the reproducible synthetic fixture and documented API evidence; UCI ML validation and Meta LIVE access are not S1 claims.


## 2026-10-27 KST — S2

- Started from remote `main` `275ae98` (S1 PASS). Added `app/ncr.py` (deterministic NCR claim builder + validator + HTML), `app/workflow.py` (identity, case scope, NCR versions, review/decision, timeline, idempotency), `app/static/index.html` (single-page UI at `/ui`), tables `users, assignments, document_versions, document_claims, reviews, approval_events, workflow_events, idempotency_keys` (migration `0003_s2`). `/health` reports `S2`; CI smoke string updated to `S2`.
- Draft generator is **`DETERMINISTIC_TEMPLATE_NO_AI`**: no model/MOCK-LLM involved; shown in UI banner, HTML export, API field `builder` and the audit timeline. Meta Tool Calling is S3 and is not faked.
- Claims are `OBSERVED/CALCULATED/HYPOTHESIS/UNKNOWN`. OBSERVED/CALCULATED and any numeric `value` must cite existing `evidence_id`s; author-added `extra_claims` go through the same validator (422 otherwise). A board with no AOI record yields an UNKNOWN claim ("a missing record is not a PASS").
- Roles: AUTHOR creates/uploads/drafts/requests review; REVIEWER decides. Authors cannot decide; a reviewer must hold a pending review request and a case assignment. Decision carries the reviewed `content_sha256` (mismatch/stale/not-in-review -> 409). Unassigned users get 403 on every case read. POST create/review/decision require `Idempotency-Key`; retries replay the stored response.
- **S1 behavior change (intentional):** S1 case endpoints now require `X-User` and case assignment (`POST /cases` and `/sources` need an AUTHOR). The S1 test client sends `X-User: alice`; no S1 assertion was altered.
- `python -m pytest -q --basetemp=%TEMP%/...`: exit 0, **35 passed** (19 S0/S1 + 16 new S2), 1 Starlette warning. `python -m ruff check .`: exit 0. `alembic upgrade head` and `alembic check`: exit 0, no drift.
- **Browser (Chrome, local Uvicorn, scratch SQLite):** as alice created a synthetic PCB case (42 evidence rows, 5 issue types), assigned bob, created NCR v1 (12 claims, all with evidence ids), requested review; as bob approved with a comment; after full page reload the NCR showed APPROVED with the decision and timeline `ASSIGNED, DRAFT_CREATED, REVIEW_REQUESTED, APPROVE`. Via the same session: alice self-approve 403, carol and dave reading the case 403, bob re-deciding a finished review 403. Stale-version 409, hash-mismatch 409 and idempotent retries are covered by pytest, not exercised in the browser.
- Meta LIVE: NOT TESTED (S2 makes no model call). Data: SYNTHETIC only, nothing sent externally.
- Ceilings: `X-User` demo identities without passwords (`ponytail:` note in `workflow.py`); one NCR per case lineage; no REJECT/REQUEST_INFO UI path beyond the buttons; no D0-D8 or Containment/RCA (S6).
- G2: **PASS** (local). Not pushed; CI for S2 not run.

## 2026-10-27 KST — S3

- S2 pushed first: remote `main` `275ae98..3482048`.
- Added `app/model_provider.py` (`ModelProvider` protocol; `MetaProvider` LIVE adapter for `muse-spark-1.3` chat completions with `tools`; timeout, HTTP/network/malformed/model-id errors raise `ProviderError`; outbound bytes scanned for the key and secret patterns -> `EgressBlocked` before any request), `app/tools.py` (read-only, case-scoped `get_case_context`, `get_manufacturing_events`, `get_evidence`, `check_data_integrity`; any row not `SYNTHETIC`+`APPROVED_FOR_EXTERNAL` -> tool denied, no rows returned), `app/report.py` (`InvestigationReport` Pydantic with `extra=forbid`; `ClaimValidator`: evidence ids must exist in the case, OBSERVED/CALCULATED and numbers need evidence, CALCULATED values recomputed server-side from cited records (mean/sum/count/ratio), causal-certainty wording, URLs and nonexistent `EV-` references in text rejected), `app/investigator.py` (loop max 5 rounds, 8 tool calls, 90 s, 30k tokens; persists `model_runs` and `tool_calls` with argument JSON and result SHA-256, failures included; report must rest on at least one successful tool call), migration `0004_s3`, `scripts/meta_investigate_smoke.py`.
- API: `POST/GET /cases/{id}/investigations` (AUTHOR, assigned, Idempotency-Key; REAL/non-synthetic case -> 422 before any call; no key -> 503, **no mock fallback**). `POST /cases/{id}/ncr` with `investigation_run_id` builds the NCR only from a `VALIDATED` run (else 409); builder `MODEL_<mode>:<model>:run<id>`, plus a standing UNKNOWN root-cause claim; existing S2 claim validator still applies. UI shows each run with a LIVE / TEST DOUBLE badge, tool calls, rejections. `/health` -> `S3`.
- `scripts/meta_smoke.py` now imports `MODEL`, `URL`, `read_key` from `app.model_provider` (no behaviour change; S0 tests unchanged).
- `python -m pytest -q --basetemp=...`: exit 0, **67 passed** (35 S0–S2 + 32 S3). S3 tests use a declared `TEST_DOUBLE` provider and a fake HTTP opener; none claims LIVE. `ruff check .`: exit 0. `alembic upgrade head` + `alembic check`: exit 0.
- In-process smoke without key: `/health` `S3`; `/ui` has the investigations section; `POST /investigations` -> 503 "LIVE model provider not configured".
- **Meta LIVE: NOT TESTED.** `.env` `MODEL_API_KEY` is empty; `python -m scripts.meta_investigate_smoke` and `python -m scripts.meta_smoke` both exit 2 `LIVE NOT TESTED`. The OpenAI-style `tools`/`tool_calls` wire format of the Meta endpoint is assumed and unverified until a LIVE run.
- Secret scan (app, scripts, migrations, docs, CI): no hits. Data: SYNTHETIC only; nothing sent externally.
- G3: **BLOCKED** on the LIVE tool_call proof. Server-side blocking of fabricated evidence, wrong ratio/mean, causal certainty, confidential egress, API failure/timeout/JSON errors: implemented and tested.
