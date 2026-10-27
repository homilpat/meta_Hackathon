# QualityOps AI — S1 source and evidence foundation

New code started on 2026-10-27 KST for the Meta Global AI Developer Hackathon. This repository contains S0 and S1 only. The older prototype at `homilpat/meta_-hackathon` is not copied or imported. The three planning documents in the parent workspace predate this implementation and are not submitted as newly built functionality.

The intended product is an evidence governed manufacturing quality investigation system. S1 generates and ingests **fictional, labeled PCB multi-source records**, preserves source versions, and exposes evidence and data-quality issues. **ML, XAI, agent investigation, document approval, and historical retrieval are not implemented.** Historical cases in the fixture have unverified reported outcomes only. A 90+ score is a goal, not a forecast. There are no measured quality or business results.

## Run locally

Use Python 3.12 or later:

```sh
python -m venv .venv
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET http://127.0.0.1:8000/health` returns `{"status":"ok","stage":"S1"}`. This endpoint checks the web process only; it does not certify a database or Meta connection.

Generate a fixture and upload one PCB case:

```sh
python -m scripts.generate_synthetic_pcb --seed 7 --output synthetic-pcb.json
curl -X POST http://127.0.0.1:8000/cases -H "Content-Type: application/json" -d '{"case_id":"DEMO-1"}'
curl -X POST http://127.0.0.1:8000/cases/DEMO-1/sources -H "Content-Type: application/json" --data-binary @synthetic-pcb.json
curl http://127.0.0.1:8000/cases/DEMO-1/sources
curl http://127.0.0.1:8000/cases/DEMO-1/events?entity_type=aoi_inspections
curl http://127.0.0.1:8000/cases/DEMO-1/evidence
curl http://127.0.0.1:8000/cases/DEMO-1/data-issues
```

`synthetic-pcb.json` is generated test data; do not commit it as real manufacturing evidence. The API accepts only the exact reproducible generator output for S1. The default fixture contains missing AOI coverage, a duplicate SPI row, AOI/human disagreement, and a late SPI correction. These are **data quality observations**, not proven physical causes. See [data dictionary](docs/DATA_DICTIONARY.md).

## Meta LIVE smoke

[Meta's model docs](https://dev.meta.ai/docs/models) list `muse-spark-1.3`. Account access is not established by that listing. The smoke script sends only a fixed synthetic sentence and asks for one structured JSON field, following [Meta's structured output documentation](https://dev.meta.ai/docs/cookbook/structured-output). It prints no key or model response body. **Running this may incur API charges.**

Put `MODEL_API_KEY=...` in the local, Git ignored `.env` file (or set the environment variable), then run `python -m scripts.meta_smoke`. Exit code 0 means one validated LIVE response; 1 means LIVE failure; 2 means no key and no call. There is no mock path. Do not put production or restricted data in a prompt. The script does not implement the full outbound privacy gateway planned for later stages.

## Data and scope

PHME 2022 source access and usage rights are unresolved. PHM Society 2018 covers ion-mill equipment faults, not this PCB chain. [UCI Steel Plates Faults](docs/UCI_STEEL_PLATES.md) is a separate real-data candidate for **fault-type classification only**; S1 inspected and deleted its ZIP but defines only an adapter interface and does not ingest or commit its rows. [Dataset decisions](docs/DATASET_ACCESS.md) explain the boundaries. No manufacturing record is sent to Meta by this app or CI.

The [work log](HACKATHON_WORK_LOG.md) records actual local checks and unresolved Gate items. CI runs on GitHub Actions after pushing; local commands alone are not a CI result.

Sources: [Meta event](https://dev.meta.ai/events/global-hackathon), [Meta API](https://dev.meta.ai/docs/overview), [PHME 2022](https://github.com/PHME-Datachallenge/Data-Challenge-2022). AI assisted coding was used. Dependencies and licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

