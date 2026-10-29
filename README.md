# QualityOps AI — evidence-governed PCB quality investigation

Built from 2026-10-27 KST for the Meta Global AI Developer Hackathon. All manufacturing data in this repository is
**fictional and generated** (SYNTHETIC, `SELF_GENERATED` licence). There are no measured quality or business results.

What it does, by stage (each stage's checks are in the [work log](HACKATHON_WORK_LOG.md)):

| Stage | Built |
|---|---|
| S1 | Versioned multi-source PCB records (SPI, AOI, human verification, repair, revisions), evidence ids, data-quality issues |
| S2 | NCR drafts from a deterministic template; every OBSERVED/CALCULATED claim cites evidence; review/approval bound to the content hash; audit timeline |
| S3 | Meta `muse-spark-1.3` tool-calling investigator over read-only evidence tools; server-side ClaimValidator recomputes numbers and rejects causal certainty |
| S4 | SPI-only risk model (LightGBM, synthetic label) with TreeSHAP; predictions are citable evidence, not inspection results |
| S5 | Synthetic precedent bank with eligibility filter; next-evidence planner that warns about fixes that failed before |
| S6 | 8D order: D2 NCR (facts only) → D3 Containment **plan** (QA/Production) → D4 RCA **hypothesis** with model scores/SHAP (Process Engineer); drafts may be written ahead, approval only in order; evidence dependency graph; a corrected source row reopens only the dependent documents and flags downstream plans `BASIS_CHANGED`; append-only audit tables; egress gateway |

Containment items are proposals (`NOT_EXECUTED`) and the RCA stays `UNCONFIRMED`; the system never records an action
as executed or a cause as confirmed. SHAP explains model scores, not physical causes.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`src/app`), Python tests (`tests`), scripts (`scripts`), Alembic (`migrations`), `pyproject.toml`, `alembic.ini` |
| `frontend/` | React + Vite UI (`src/features`, `src/components`, `src/api`, …) and its tests (`tests`) |
| `docs/` | `architecture/` (decisions, data, [refactor audit](docs/architecture/REFACTOR_AUDIT.md)), `implementation/` ([status](docs/implementation/V5_IMPLEMENTATION_STATUS.md)), `evaluations/` (measured results), `archive/` (superseded specs) |

## Run locally

Python 3.12+, from `backend/` (paths no longer depend on the working directory):

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

`GET /health` returns `{"status":"ok","stage":"S6"}` (web process only). Open `http://127.0.0.1:8000/ui` and pick a
demo user in the header: alice/dave (author), bob/carol (NCR reviewer), erin (QA/Production), frank (process
engineer). Demo identities are selected by the `X-User` header with no password; this is not real authentication.

## Web UI

`http://127.0.0.1:8000/app/` is the main UI (React + Vite, source in `frontend/src/`, design started in Figma Make and wired
to the API; every value shown comes from the API). The built files are committed in `backend/src/app/static/web/`, so Node is
not needed to run it. To change the UI: `cd frontend && npm ci && npm run dev` (proxies the API to :8000), `npm test`
(vitest), then `npm run build` to update `backend/src/app/static/web/` (CI fails if the committed bundle is stale). The older single-file UI at `/ui` is kept as a fallback.

## Demo walk-through (`/ui` labels; `/app` has the same steps)

1. As alice: **New synthetic PCB case**, then **Assign bob, erin, frank as reviewers**.
2. **Score boards with SPI model** (optional) — click a `PRED-n`/`XAI-n` id for the SHAP view.
3. **Lessons from past cases** shows next checks with history OFF vs ON and why a past fix is not adopted.
4. **Create NCR draft** → request review → switch to bob → APPROVE.
5. As alice **Create Containment plan draft** → erin approves; **Create RCA hypothesis draft** → frank approves.
6. **Import SPI correction** re-measures one SPI row (v3). The *Source corrections and impact* table shows
   before/after: the NCR and RCA that cite that row become `REVALIDATION_REQUIRED`; the Containment plan cites no
   SPI row, so it keeps its content but is flagged `BASIS_CHANGED`. After NCR v2 is approved, erin records
   *no scope impact* (or *revise*) on `/app`; only then can the new RCA be approved. Approval records are unchanged.
7. **Run investigation (LIVE Meta model)** needs a key (below); without one the API returns 503 — there is no mock.

The same flow by API is covered by `backend/tests/test_s6_followups.py`.

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
  evidence id (LOT), version, approver and hash from the snapshot; a miss returns 500 and no file. Each export is
  logged (`EXPORTED`, file SHA-256). In `/app`: *문서 · 결재* (approved version) and *D0~D8 진행* → D8 (closed case).
- Limits: synthetic data only. Hangul text is rendered in the PDF with reportlab's built-in CID font, but PDF text
  extraction only round-trips ASCII, so Hangul statements are not part of the read-back check.
- Reset: every run uses a new scratch DB; nothing touches `backend/qualityops.db`.

## Security

[SECURITY.md](SECURITY.md) lists each enforced control with the test that proves it (egress allowlist, least-privilege tools, output validation, prompt-injection test, separation of duties, hash-chained append-only audit with `GET /audit/verify`, investigation quota) and what a real deployment still needs (SSO, self-hosted model or provider contract for real data, encryption, external anchoring of the audit chain).

## Meta LIVE

Put `MODEL_API_KEY=...` in the git-ignored `.env` (working directory first, then the repo root) (see `.env.example`). **Calls may incur API charges.**

- `python -m scripts.meta_smoke` — one fixed synthetic prompt. Exit 0 LIVE ok, 1 LIVE failure, 2 no key (no call).
- `python -m scripts.meta_investigate_smoke` — one tool-calling investigation on a synthetic case.

Only SYNTHETIC + APPROVED_FOR_EXTERNAL rows can reach the model: tools fail closed on anything else, and the
provider blocks any outbound payload carrying another origin/sensitivity, the word CONFIDENTIAL, or secret-like
text before the network call. **LIVE Meta has not been run in this repository yet.**

## Evaluation (scripts run from `backend/`)

- `python -m scripts.eval_s7` → [docs/evaluations/EVAL_RESULTS.md](docs/evaluations/EVAL_RESULTS.md): deterministic checks on 30 held-out
  synthetic cases (revision impact precision/recall, unsupported template claims, validator recall on seeded bad
  claims, egress gate). The A/B/C/D model comparison (incl. History OFF/ON) is **NOT RUN** until LIVE access exists.
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
