# Third-party notices

This repository contains no vendored third-party source, PCB dataset, or model weights. Runtime and development packages are installed from PyPI and are not included in Git.

| Package | Purpose | License (upstream) |
|---|---|---|
| FastAPI | HTTP API | MIT |
| Pydantic | Response validation | MIT |
| Uvicorn | Local ASGI server | BSD-3-Clause |
| SQLAlchemy | SQLite persistence foundation | MIT |
| Alembic | Migrations | MIT |
| pytest | Tests | MIT |
| HTTPX | FastAPI test client transport | BSD-3-Clause |
| Ruff | Lint | MIT |
| NumPy | Feature arrays | BSD-3-Clause |
| scikit-learn | Baselines, split metrics | BSD-3-Clause |
| LightGBM | SPI risk model, TreeSHAP (`pred_contrib`) | MIT |

Direct version constraints are in `pyproject.toml`; transitive package licenses must be checked before public submission. No PHME content is redistributed. Meta Muse Spark is an external service, not a bundled dependency.


## Datasets (not redistributed)

- **UCI Steel Plates Faults** — Buscema, M., Terzi, S., & Tastle, W. (2010). UCI Machine Learning Repository.
  https://doi.org/10.24432/C5J88N — [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Used by
  `scripts/steel_model.py` to train and evaluate a reference classifier. Modified: parsed and split for training;
  only aggregate metrics and SHAP summaries are committed (`docs/steel_eval.json`), no source rows.
