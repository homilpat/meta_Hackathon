# QualityOps AI — S0 foundation

New code started on 2026-10-27 KST for the Meta Global AI Developer Hackathon. This repository contains only the S0 foundation. The older prototype at `homilpat/meta_-hackathon` is not copied or imported. The three planning documents in the parent workspace predate this implementation and are not submitted as newly built functionality.

The intended product is an evidence governed manufacturing quality investigation system. **No PCB ingestion, ML, agent investigation, document approval, or historical learning is implemented yet.** A 90+ score is a goal, not a forecast. There are no measured quality or business results.

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

`GET http://127.0.0.1:8000/health` returns `{"status":"ok","stage":"S0"}`. This endpoint checks the web process only; it does not certify a database or Meta connection. SQLite currently contains only Alembic's revision table.

## Meta LIVE smoke

[Meta's model docs](https://dev.meta.ai/docs/models) list `muse-spark-1.3`. Account access is not established by that listing. The smoke script sends only a fixed synthetic sentence and asks for one structured JSON field, following [Meta's structured output documentation](https://dev.meta.ai/docs/cookbook/structured-output). It prints no key or model response body. **Running this may incur API charges.**

Put `MODEL_API_KEY=...` in the local, Git ignored `.env` file (or set the environment variable), then run `python -m scripts.meta_smoke`. Exit code 0 means one validated LIVE response; 1 means LIVE failure; 2 means no key and no call. There is no mock path. Do not put production or restricted data in a prompt. The script does not implement the full outbound privacy gateway planned for later stages.

## Data and scope

PHME 2022 source access and usage rights are unresolved. PHM Society 2018 was also checked: it covers ion-mill equipment faults, not the required PCB SPI/AOI/operator chain, and its reuse rights remain unverified. [docs/DATASET_ACCESS.md](docs/DATASET_ACCESS.md) records both decisions and the explicitly labeled synthetic PCB path for S1. No fixture or dataset is included in S0. No data is sent to Meta by this app or CI.

The [work log](HACKATHON_WORK_LOG.md) records actual local checks and any unresolved Gate items. CI runs on GitHub Actions only after this repository is pushed; local commands alone are not a CI result.

Sources: [Meta event](https://dev.meta.ai/events/global-hackathon), [Meta API](https://dev.meta.ai/docs/overview), [PHME 2022](https://github.com/PHME-Datachallenge/Data-Challenge-2022). AI assisted coding was used. Dependencies and licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

