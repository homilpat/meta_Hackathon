# QualityOps AI — evidence-governed quality investigation

Built for the Meta Global AI Developer Hackathon with Meta **`muse-spark-1.3`**.

**▶ Demo video: https://youtu.be/V2bcRva2lkM**

## In one minute

**Problem.** When a customer complains about a defect, a quality engineer has to read the customer's PDF/Excel/Word
files, dig through SPI/AOI/repair records, and write an 8D report (D0–D8). This is slow, and an AI that "just
writes the report" is dangerous: a wrong number, an invented cause or a self-approved document reaches the customer.

**Approach: the AI proposes, the server verifies, a person approves.**
1. **The AI does the reading and writing.** Meta reads customer documents, investigates the case with tools, finds
   similar past cases and writes every answer and draft sentence in Korean.
2. **The server checks facts, not style.** Every number, LOT, code and calculation the AI writes is re-checked
   against the records (and recomputed). A failed check goes back to the AI with the reason, and the AI rewrites.
3. **People decide.** The AI never approves, confirms a cause, closes a case or sends anything out. Approvals are
   role-checked, bound to the exact document version and written to a hash-chained audit log.

**Where Meta is used**

| Step | What Meta does | What the server checks |
|---|---|---|
| Customer document intake (PDF, DOCX, XLSX) | Extracts part, LOT, quantities and dates with their source location; proposes column mappings for unknown spreadsheets | The value really is at that location; a person confirms before a case exists |
| AI Agent chat | Understands the request, picks tools, asks back when unclear, writes the answer | Only allowed tools run, as the signed-in user; every cited fact exists |
| Quality investigation | Reads SPI/AOI/verification data, compares the customer's claim with internal records, proposes next checks | Recomputes every calculation; refuses uncited or wrong claims and sends them back |
| Past cases (Experience Memory) | Recognises the same problem written in other words or languages | Scope and permission filters; a precedent is never treated as proof |
| D2–D4 drafts and 8D report | Writes the sentences and translates record text | Numbers and codes must match the facts exactly |

**Measured with Meta LIVE** (details in [EV_LOCAL_EVAL](docs/evaluations/EV_LOCAL_EVAL.md) and the
[LIVE log](docs/evaluations/META_LIVE_LOG.md)):

| What | Result |
|---|---|
| Investigation loop, 8 tasks × 4 runs (after fixes) | pass^1 **0.94**, pass^4 **0.75**, false completions 0 ([trace](docs/evaluations/ev/loop_eval_LIVE_v2_2026-11-03T053316.html)); before: 0.69 / 0.25 |
| Past cases written in other words or languages | found **6/6** (keyword search alone: 2/6) ([details](docs/implementation/EXPERIENCE_AI.md)) |
| Customer file not approved for external use | masked: 3/3 valid reports, the secret LOT never sent to the model |
| Synthetic document extraction | 33/33 dev and 17/17 validation checks |

**Try it:** follow [Run locally](#run-locally) (install, `alembic upgrade head`, `uvicorn`), open
`http://127.0.0.1:8000/app/`, start a case with **SPC 라인 모니터링** or **+ 새 사건**, and talk to the **AI Agent**.
Without a Meta key a deterministic server planner runs instead, so the app also works offline.

All manufacturing data in this repository is **fictional and generated** (SYNTHETIC, `SELF_GENERATED` licence). There are no measured factory-quality improvements or business results.

## What it does

QualityOps AI is an **evidence-governed, human-controlled manufacturing quality investigation** demo for a synthetic PCB/SMT line. A statistical alarm is not treated as a confirmed defect, a hypothesis is not a confirmed cause, and an AI proposal is not a human approval. Customer-document intake and supplier/audit requests feed the same controlled case workflow; the manufacturing demonstration remains a synthetic PCB/SMT line. Project work and test evidence are tracked in the [work log](HACKATHON_WORK_LOG.md).

| Capability | Implemented behavior |
|---|---|
| Document intake | Agent-chat PDF/DOCX intake, structured values with source locators, missing/conflicting fields, human-confirmed case creation or linking; XLSX/CSV supplements |
| Requests and responsibility | Supplier/audit requests, versioned replies, human accept/revise/reject, owner handover and existing Queue/audit integration; no external portal or mail delivery |
| Data and SPC | Versioned SPI/AOI/verification and repair data; source-row provenance and data-quality checks; X-bar/R, Western Electric rules and Cpk on a synthetic SMT line |
| D0–D3 | Human triage (NCR_ONLY / FULL_8D / EMERGENCY_FULL_8D), team assignment, evidence-linked 5W2H/IS–IS NOT, urgent containment and independently verified action events |
| D4 | 6M/fishbone, 5-Why, hypotheses, controlled experiments and independent human cause decisions; SHAP or precedent alone cannot confirm a cause |
| D5–D6 | Cause-linked action selection, execution lifecycle, pre-registered effectiveness criteria and server-computed effectiveness; failure reopens cause investigation |
| D7–D8 | Controlled SOP/FMEA revision and training gates, current-evidence closure checks, human acknowledgements, archived closure snapshots and reopen history |
| Docs and reports | G9 versioned human editing, difference review, claim revalidation, hash-bound approvals; G10 approved DOCX/PDF exports with read-back checks |
| Experience Memory | Scope/permission-filtered precedent search: KNOWN / ANALOGICAL / NO_RELEVANT_HISTORY. Failed, recurrent, stale or condition-mismatched precedents are not blindly prescribed |
| AI and Agent-First | Meta-backed read-only investigation and a hybrid agent planner over allowlisted tools; every answer is written by Meta and fact-checked by the server; persisted runs, ask-back, D0 form proposals, draft preparation and explicit human hand-off; deterministic offline fallback |
| Audit and verification | ClaimValidator, policy-driven approval, least-privilege tools, immutable evidence/document references, audit checks and backend/frontend/integration CI |

**Boundaries:** All production-style records and operational outcomes here are SYNTHETIC/SIMULATED; a logged “executed” action represents a simulated workflow event, not a physical factory operation. The demo uses role switching via an `X-User` header, not production authentication. A final 8D report requires the appropriate closed case; the NCR_ONLY route can produce its own closure report. Model predictions, explanations and prior cases are evidence for investigation, not independent proof of causation.

## Current snapshot — 2026-11-05

Checked locally on `3ce3bfe` (GitHub Actions minutes ran out on 2026-11-04, so CI is now manual-dispatch only and
the same steps were run locally): backend pytest **465 passed**, ruff clean, frontend typecheck + **34** tests,
integration smoke **27/27**, HTTP end-to-end **7/7**. The 23-scene demo ran end to end against Meta LIVE.

Added since 2026-11-02:
- **The AI writes every answer.** Agent replies, the investigation report and D2–D4 draft sentences are written by
  Meta in Korean; the server only checks numbers, codes, evidence and recomputed values, and sends failures back.
- **Screens read like a product:** Korean labels, evidence named by what it is (e.g. "SPI 측정 8건") instead of
  record ids or hashes; the 8D and NCR-closure reports are Korean D0–D8 documents; the admin picks the translation
  language (`TRANSLATE_LANGUAGE`: ko, ja, zh, OFF).
- **Customer forms:** unknown XLSX layouts get an AI column mapping that a person confirms and that is reused for the
  same layout; customer DOCX forms are filled from the case (content controls and text boxes included).
- **Protected files** go to the model masked; the server scans tool results for embedded instructions.
- **Experience Memory with Meta** finds the same problem written in other words or languages (2/6 → 6/6).
- **Case archive (보관):** any case conversation can be archived; nothing is deleted, an append-only event records it.

- **Implemented and checked:** file intake → draft review → human-confirmed case → existing D0 gates; supplier/audit request and reply review; responsibility/handover. See [v5.8 verification](docs/implementation/V58_VERIFICATION.md).
- **LIVE measured:** Muse document extraction, the read-only investigation loop (pass^1 0.94, pass^4 0.75 after the fixes) and Experience Memory; see [Evaluation](#evaluation-scripts-run-from-backend).
- **Not implemented:** specialist defect-vision model (`NOT_CONFIGURED`), mail integration, unattended case creation, external supplier accounts, production authentication.
- **Limits:** DOCX uses structural locators and is not rendered; PDF tables are reconstructed; masked inputs lose semantic information. This is not a production QMS or a validated manufacturing deployment.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`src/app`), Python tests (`tests`), scripts (`scripts`), Alembic (`migrations`), `pyproject.toml`, `alembic.ini` |
| `frontend/` | React + Vite UI (`src/features`, `src/components`, `src/api`, …) and its tests (`tests`) |
| `docs/` | `architecture/` (decisions, data, [refactor audit](docs/architecture/REFACTOR_AUDIT.md)), `implementation/` ([status](docs/implementation/V5_IMPLEMENTATION_STATUS.md)), `evaluations/` (measured results), `archive/` (superseded specs) |

## Run locally

Python 3.12+, from `backend/` (package/resources are configured for the monorepo layout):

```sh
cd backend
python -m venv .venv
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m alembic upgrade head          # DB: $DATABASE_URL, default backend/qualityops.db
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m scripts.integration_smoke     # real uvicorn on a fresh migrated scratch DB
```

`GET /health` returns `{"status":"ok","stage":"S6"}` (web process only). Open `http://127.0.0.1:8000/app/` and pick a
demo user in the header: alice/dave (author), bob/carol (NCR reviewer), erin (QA/Production), frank (process
engineer), gina (AI admin). Demo identities are selected by the `X-User` header with no password; this is not real authentication.

## Web UI

`http://127.0.0.1:8000/app/` is the main UI (React + Vite, source in `frontend/src/`, design started in Figma Make and wired
to the API; every value shown comes from the API). The built files are committed in `backend/src/app/static/web/`, so Node is
not needed to run it. To change the UI: `cd frontend && npm ci && npm run dev` (proxies the API to :8000), `npm test`
(vitest), then `npm run build` to update `backend/src/app/static/web/` (CI fails if the committed bundle is stale). The older single-file UI at `/ui` is kept as a fallback.

The app opens on the **AI Agent** (Agent-First, spec §22). For example: "이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘."
- **What the server does:** it uses a server situation card and (when LIVE is available) one strict-JSON model plan to run allowlisted tools as the current user (`backend/src/app/agent.py`, routes `/agent/*`). It can save and validate the next 8D draft, then stops until you pick a reviewer and confirm.
- **What it never does:** approve, confirm a cause, execute an action, close a case, or download a file for you.
- **Without a Meta key:** a server rule planner runs instead.
- **Manual path:** 내 할 일, 부서 할 일 and 승인 대기 read the same `/queue`, and every earlier screen is under **전문 도구**.
- Records: `docs/implementation/AG0_BASELINE.md` … `AG5_RELEASE_VERIFICATION.md`.

## Demo: Agent-first and manual 8D

Open `/app/` and select a synthetic case and demo role. In the **AI Agent** screen, try:

- “이번 SPC 경보, 8D로 가야 할지 판정해 줘” — inspect evidence, then offer a human-reviewed D0 form; **nothing is automatically submitted**.
- “이번 LOT 불량 원인을 조사해 줘” — evidence and prior-case lookups, with a proposed summary rather than a causal determination.
- “이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘” — status checks plus the next eligible document draft and validation, stopping before any human review request or approval.

For the full controlled path, use **전문 도구 → D0~D8 진행** and **문서 · 결재**. D0 triage → D1 team → D2 NCR → D3 containment/verification → D4 experiment and confirmed cause → D5/D6 action and measured effectiveness → D7 controlled prevention → D8 closure. Edit and revalidate documents in G9; download the final report or an approved document only when its export gate passes. An NCR_ONLY case closes through its shorter permitted route and exports an “NCR closure report”.

The older `/ui` is maintained as a fallback interface, not the primary demo. A repeatable end-to-end scenario is available via `python -m scripts.e2e_http` from `backend/`.

**Collaboration:** *할 일* shows "내 할 일" (items you own: reviews assigned to you, basis checks on plans you
approved, redrafts and comment answers on your documents) and "부서 할 일" (everything open for your role).
Reviewers leave comments on a single claim; the author answers and resolves them, and every comment stays in the
append-only log. Each document shows a *책임 추적* trail (who did what, in which role). Concurrent use was
simulated with `python -m scripts.concurrency_sim` ([results](docs/evaluations/CONCURRENCY_RESULTS.md)): it found three
race conditions, which are fixed and covered by a regression test.

**Line monitoring (SPC → case):** *SPC 라인 모니터링* replays a synthetic SMT line run (3 lots, 144 boards, 1,152
SPI pins, lot/shipment traceability). The monitor builds an X̄-R chart per board (n = 8 pins) with limits taken
from the reference lot, then applies Western Electric rules 1–4 and an R-chart check. The first signal in a later lot
opens a case automatically, logged as `SPC_ALARM` and assigned to the team. With seed 7 the worn-stencil lot L02
signals at panel 2, 77 minutes before AOI plus human review confirm the first defect there. The NCR cites the
limits, signals and per-lot Cpk as CALCULATED claims, and the containment plan proposes a lot-level hold of the
unshipped panels plus a QA decision on the shipped ones. A signal is a statistical cue: it is not a defect finding
and not a cause. The replay stands in for a live event feed such as IPC-CFX, which is not implemented.

## Document intake, reading policy and request review

In the Agent chat, attach PDF/DOCX files (XLSX/CSV can supply tabular evidence). Analysis produces a source-linked
draft with missing/conflicting values. A person resolves open items and confirms either a new case or a link to
an accessible existing case. Uploading or analysing alone creates no case. New cases start at D0; customer
reports are not internal verification, and no SPI/AOI/shipment data is invented. See [case hand-off](docs/implementation/IN3_CASE_HANDOFF.md).

The server parses text, tables, figures and chart data; Muse interprets the document and links context.
The default reading policy is **WHOLE_FIRST**: read all parsed elements when they fit the model input and any
configured per-call cost cap, otherwise use navigation reading (`HYBRID` in code). Navigation sends selected
elements and a document map, then reads requested parts within the round limit. This differs from the
server-parser-plus-model division of responsibilities. The choice and coverage are recorded.
See [operating limits and policy](docs/implementation/LIMITS.md).

DOCX chart caches are compared with stored embedded-workbook values; mismatches are shown for human review.
PDF chart pictures are not trusted numeric sources. Scans may be transcribed when the file's processing route
allows it, and their values require confirmation. The specialist vision adapter is present but returns
`NOT_CONFIGURED`: document understanding is not validated defect detection.
See [document/vision boundary](docs/implementation/MM_VISION_BOUNDARY.md).

Supplier/audit cases reuse the case workflow: register a request, upload a versioned reply, review item-level
evidence, then accept, ask for revision or reject as a person. Reply acceptance does not confirm a cause,
prove effectiveness or close a case. Handover keeps the previous owner responsible until acceptance; tasks use
the existing Queue. External replies are uploaded by an internal owner; nothing is emailed outside.
See [requests and responsibility](docs/implementation/RW_REQUESTS_RESPONSIBILITY.md).

Uploads do not authorise raw external processing. The implemented routes are RAW (synthetic fixture or approved
file), MASKED (tokenised values, no images) and LOCAL (configured in-house provider; no real local model installed
here). Masking reduces meaning and is not a proof of anonymisation or production confidentiality.
See [egress and spreadsheet details](docs/implementation/EGRESS_SHEETS_TABLES.md).

## One synthetic case end to end, with DOCX/PDF export (G10)

```sh
cd backend
python -m scripts.e2e_http [--out DIR]   # fresh migrated scratch DB + real uvicorn per scenario; prints where files went
```

The success scenario (`tests/test_c_e2e.py::success`) runs the SMT line case L: past-case retrieval (KNOWN) and a
human "review prior response" choice → D0 triage → D1 team → D2/D3/D4 approvals → D3 hold executed and independently
verified → D4 cause confirmed → D5 action → D6 EFFECTIVE on a pre-registered plan → D7 SOP/FMEA revisions with
training → a person edits the approved NCR (a wrong count is refused 422; a wording edit becomes v2 and is
re-validated) → D3/D4 flagged `BASIS_CHANGED` and re-confirmed → **CLOSED** → the case becomes a
`NOT_YET_OBSERVED` reference for the next search. It then downloads the 8D report and the approved NCR as DOCX and
PDF (default: a new temp directory). The failure scenario records D6 NOT_EFFECTIVE: the cause is reopened and closure is refused.

- `GET /cases/{id}/report/export?format=docx|pdf` renders the snapshot archived by the **CLOSED** closure (every
  document hash re-checked, audit chain must verify). `GET /cases/{id}/documents/{ncr|containment|rca}/export
  ?format=docx|pdf[&version=n]` exports an **APPROVED** version whose approval names its exact content hash. Drafts,
  `BASIS_CHANGED` / `REVALIDATION_REQUIRED`, BLOCK-validated or replaced versions get a 409 with the reason.
- After writing, the server reads the file back (DOCX XML / PDF text) and checks every required value, unit,
  claim id, version and approver (the content hash is checked against the approval before writing); a miss returns 500 and no file. Each export is
  logged (`EXPORTED`, file SHA-256). In `/app`: *문서 · 결재* (approved version) and *D0~D8 진행* → D8 (closed case).
- Limits: synthetic data only. Hangul text is rendered in the PDF with reportlab's built-in CID font, but PDF text
  extraction only round-trips ASCII, so Hangul statements are not part of the read-back check.
- Reset: every run uses a new scratch DB; nothing touches `backend/qualityops.db`.

## Security

[SECURITY.md](SECURITY.md) lists each enforced control with the test that proves it (egress allowlist, least-privilege tools, output validation, prompt-injection test, separation of duties, hash-chained append-only audit with `GET /audit/verify`, investigation quota) and what a real deployment still needs (SSO, self-hosted model or provider contract for real data, encryption, external anchoring of the audit chain).

## Meta LIVE and offline behavior

Set `MODEL_API_KEY=...` in a git-ignored `.env` or the environment (see `.env.example`). **Real model calls may incur charges.** The backend tests isolate the real key so running pytest does not intentionally invoke paid LIVE calls.

From `backend/`:

- `python -m scripts.meta_smoke` — minimal structured-response check.
- `python -m scripts.meta_investigate_smoke` — synthetic-case, read-only investigation and report validation.

**Real Meta `muse-spark-1.3` calls have succeeded**, including the structured smoke, an Agent-First draft/validation hand-off and the hybrid planner. See the [LIVE run log](docs/evaluations/META_LIVE_LOG.md), which also records failed calls. When an investigation report fails a server check, the server refuses it and sends the reasons back to the model for a rewrite; it never shows unsupported content. The latest LIVE re-measurement completed 30 of 32 runs (pass^1 0.94); LIVE connectivity is not a 100% success rate.

The hybrid planner uses the model as an intent classifier (one strict-JSON call over a server-generated situation card); the tools for each intent are a fixed server workflow, so the same request runs the same tools LIVE or offline. The fixed chat investigation workflow adds a summary call at `reasoning_effort=minimal` (LIVE: about 9 s end to end). Intent accuracy is measured with `python -m scripts.intent_eval` (LIVE 30/30 incl. 5 held-out, see the LIVE log). When the goal is ambiguous it asks a clarifying question; if no key is available it uses a deterministic server planner. The agent does not approve documents, execute plant actions, confirm causes or close a case.

Case investigation tools retain their SYNTHETIC/APPROVED_FOR_EXTERNAL checks. File intake additionally has the RAW/MASKED/LOCAL routes described above; a masked call is still an external call. Never use real factory or personal data without a separate production security and governance design.

## Evaluation (scripts run from `backend/`)

[Evaluation report and limitations](docs/evaluations/EV_LOCAL_EVAL.md) distinguish offline server checks, recorded
LIVE responses and new model collection. Scoring saved traces is free/local: **0 network connections, 0 model
calls, no LLM judge**. New LIVE collection can cost money and requires an explicit opt-in, key and confirmed budget.

| Evaluation | Recorded result | Meaning / limit |
|---|---|---|
| CUAD held-out subset, one run | Navigation span recall 0.632; full parsed-document recall 0.719 | 10 English legal contracts; not a manufacturing benchmark or official full-CUAD score |
| Synthetic file fixtures | Parser 40/40 checks; LIVE extraction 33/33 dev and 17/17 validation checks | Small functional fixtures; no general accuracy or defect-vision claim |
| AgentEvals paired workflow checks | 16/16 variants: 14 fixed-server, 2 model-loop TEST_DOUBLE | Verifies branches, arguments, state and safe hand-off; not autonomous-model success |
| LIVE investigation loop | First run 22/32, pass^1 0.688, pass^4 0.25; re-measured after the fixes (2026-11-03): 30/32, pass^1 0.938, pass^4 0.75, 0 false completions | 8 tasks × 4 runs; the two remaining failures were refused by the server, not passed |

pass^4 measures all-four success consistency per task, averaged across the eight tasks; it is not “at least one
success in four attempts”. These are custom tests inspired by τ-bench/BFCL, not official benchmark scores.
The server refused the recorded invalid calculation reports. Rejection safety does not imply high task completion.
Some recorded runs have a `+dirty` source stamp; their hashes/versions and limitations are retained in the reports.

```sh
python -m scripts.cuad_eval score       # requires separately prepared saved traces
python -m scripts.fixture_eval
python -m scripts.agent_eval
python -m scripts.loop_eval score      # requires saved investigation traces
```

Raw traces and CUAD data are git-ignored. Scores are committed under [docs/evaluations/ev/](docs/evaluations/ev/);
without local traces, replay may report NOT_RUN rather than reproduce a LIVE run. Data preparation and paid
collection commands are documented separately in the evaluation report. The following older evaluations measure
other parts of the product:


- `python -m scripts.eval_s7` → [docs/evaluations/EVAL_RESULTS.md](docs/evaluations/EVAL_RESULTS.md): deterministic checks on 30 held-out
  synthetic cases (revision impact precision/recall, unsupported template claims, validator recall on seeded bad
  claims, egress gate). The A/B/C/D model comparison (including History OFF/ON) is **not established by these deterministic checks**; do not present unrun comparisons as measured results.
- `python -m scripts.train_model` → [docs/evaluations/MODEL_CARD.md](docs/evaluations/MODEL_CARD.md).
- `python -m scripts.history_compare` → [docs/evaluations/HISTORY_COMPARISON.md](docs/evaluations/HISTORY_COMPARISON.md) (deterministic
  planner log, not an LLM result).

## Data and scope

PHME 2022 access and usage rights are unresolved and none of its content is included.

**Real public data check:** `python -m scripts.steel_model` downloads [UCI Steel Plates Faults](docs/evaluations/UCI_STEEL_PLATES.md)
(CC BY 4.0, hash-verified, kept in git-ignored `data/`) and runs the same LightGBM + TreeSHAP method as a separate
fault-*type* classifier: test macro F1 0.810 vs 0.699 logistic regression and 0.074 majority class
([model card](docs/evaluations/STEEL_MODEL_CARD.md); shown on the prediction screen). Every row is a faulty plate, so it does
not measure defect detection; its rows never enter a case or a model prompt. See [dataset
decisions](docs/architecture/DATASET_ACCESS.md) and the [data dictionary](docs/architecture/DATA_DICTIONARY.md).

Sources: [Meta event](https://dev.meta.ai/events/global-hackathon), [Meta API](https://dev.meta.ai/docs/overview),
[Meta models](https://dev.meta.ai/docs/models). AI-assisted coding was used. Dependencies and licences:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). A repository licence has not been chosen yet.
