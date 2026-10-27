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

## Run locally

Python 3.12+:

```sh
python -m venv .venv
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET /health` returns `{"status":"ok","stage":"S6"}` (web process only). Open `http://127.0.0.1:8000/ui` and pick a
demo user in the header: alice/dave (author), bob/carol (NCR reviewer), erin (QA/Production), frank (process
engineer). Demo identities are selected by the `X-User` header with no password; this is not real authentication.

## Web UI

`http://127.0.0.1:8000/app/` is the main UI (React + Vite, source in `web/`, design started in Figma Make and wired
to the API; every value shown comes from the API). The built files are committed in `app/static/web/`, so Node is
not needed to run it. To change the UI: `cd web && npm install && npm run dev` (proxies the API to :8000), then
`npm run build` to update `app/static/web/`. The older single-file UI at `/ui` is kept as a fallback.

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

The same flow by API is covered by `tests/test_s6_followups.py`.

**Collaboration:** *할 일* shows "내 할 일" (items you own: reviews assigned to you, basis checks on plans you
approved, redrafts and comment answers on your documents) and "부서 할 일" (everything open for your role).
Reviewers leave comments on a single claim; the author answers and resolves them, and every comment stays in the
append-only log. Each document shows a *책임 추적* trail (who did what, in which role). Concurrent use was
simulated with `python -m scripts.concurrency_sim` ([results](docs/CONCURRENCY_RESULTS.md)): it found three
race conditions, which are fixed and covered by a regression test.

## Meta LIVE

Put `MODEL_API_KEY=...` in the git-ignored `.env` (see `.env.example`). **Calls may incur API charges.**

- `python -m scripts.meta_smoke` — one fixed synthetic prompt. Exit 0 LIVE ok, 1 LIVE failure, 2 no key (no call).
- `python -m scripts.meta_investigate_smoke` — one tool-calling investigation on a synthetic case.

Only SYNTHETIC + APPROVED_FOR_EXTERNAL rows can reach the model: tools fail closed on anything else, and the
provider blocks any outbound payload carrying another origin/sensitivity, the word CONFIDENTIAL, or secret-like
text before the network call. **LIVE Meta has not been run in this repository yet.**

## Evaluation

- `python -m scripts.eval_s7` → [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md): deterministic checks on 30 held-out
  synthetic cases (revision impact precision/recall, unsupported template claims, validator recall on seeded bad
  claims, egress gate). The A/B/C/D model comparison (incl. History OFF/ON) is **NOT RUN** until LIVE access exists.
- `python -m scripts.train_model` → [docs/MODEL_CARD.md](docs/MODEL_CARD.md).
- `python -m scripts.history_compare` → [docs/HISTORY_COMPARISON.md](docs/HISTORY_COMPARISON.md) (deterministic
  planner log, not an LLM result).

## Data and scope

PHME 2022 access and usage rights are unresolved and none of its content is included.

**Real public data check:** `python -m scripts.steel_model` downloads [UCI Steel Plates Faults](docs/UCI_STEEL_PLATES.md)
(CC BY 4.0, hash-verified, kept in git-ignored `data/`) and runs the same LightGBM + TreeSHAP method as a separate
fault-*type* classifier: test macro F1 0.810 vs 0.699 logistic regression and 0.074 majority class
([model card](docs/STEEL_MODEL_CARD.md); shown on the prediction screen). Every row is a faulty plate, so it does
not measure defect detection; its rows never enter a case or a model prompt. See [dataset
decisions](docs/DATASET_ACCESS.md) and the [data dictionary](docs/DATA_DICTIONARY.md).

Sources: [Meta event](https://dev.meta.ai/events/global-hackathon), [Meta API](https://dev.meta.ai/docs/overview),
[Meta models](https://dev.meta.ai/docs/models). AI-assisted coding was used. Dependencies and licences:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). A repository licence has not been chosen yet.
