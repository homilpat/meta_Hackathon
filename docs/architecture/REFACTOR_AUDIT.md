# R0 refactor audit — monorepo move (frontend/ + backend/)

Source of truth: `QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md` §19; execution order: `prompts/QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md` §2.

## R0-A — baseline (HEAD `58d316a`, branch `main`, clean tree, 2026-10-29 KST, Windows 11, Python 3.12 venv, Node 24.19 / npm 11.17)

| Check | Command (repo root, before the move) | Result |
|---|---|---|
| pytest | `python -m pytest -q -p no:cacheprovider --basetemp=<scratch>` | **226 passed**, 1 warning, exit 0 (284 s) |
| Ruff | `python -m ruff check . --no-cache` | exit 0 |
| Alembic | upgrade head + `alembic check` on a fresh scratch SQLite file | 0001_s0 → 0016_v5_g8 (single head), "No new upgrade operations detected" |
| Frontend | `cd web && npm run build` (tsc --noEmit + vite build) | exit 0; output byte-identical to the committed `app/static/web` (only CRLF/LF differences in the working copy) |
| OpenAPI | `create_app(scratch).openapi()` | 74 paths / 89 operations, sha256 prefix `e450d718dd1d384c` |
| Meta tool schemas | `app.tools` SPECS / HISTORY_SPECS / HYBRID_SPECS / ARGS / APPROVED | sha256 prefix `c26c3c653704dfb0` |
| CI | GitHub Actions `S0 checks` (`ci.yml`) | `gh` is not installed here; latest run status NOT_VERIFIED locally |

Environment note: `%TEMP%\pytest-of-user` is owned by another local account, so the default pytest basetemp fails with
`PermissionError` (173 errors). This is environmental; every run here passes `--basetemp` to a writable scratch dir.

Protected local data: the git-ignored `qualityops.db` at the repo root (pre-S0 schema, stamped `0012`; sha256 prefix
`e39fac5e96ad602b`) is never opened, migrated or moved. All migration checks use scratch files.

## Mapping (old → new)

| Old | New | Notes |
|---|---|---|
| `app/` (37 files incl. `static/`) | `backend/src/app/` | package name `app` kept; `static/web` (built React) moves with it |
| `tests/` (21) | `backend/tests/` | `from tests.…` imports keep working (pytest runs from `backend/`) |
| `scripts/` (10) | `backend/scripts/` | `python -m scripts.<name>` from `backend/` |
| `migrations/` (17) | `backend/migrations/` | revision ids/order unchanged |
| `pyproject.toml`, `alembic.ini` | `backend/` | src layout (`where = ["src"]`), package data for `static/**` |
| `web/` (11) | `frontend/` | `src/` split into `features/`, `components/`, `api/`, `types/`; new `tests/` |
| `docs/*.md|json` | `docs/{architecture,implementation,evaluations}/` | nothing deleted; links rewritten |
| root v5.5 FINAL requirements / CODEX prompts | `docs/archive/` | historical; superseded by the MONOREPO spec |
| — | `QualityOps_AI_FINAL_REQUIREMENTS_v5_5_MONOREPO_FINAL.md` (root), `prompts/QualityOps_AI_CODEX_MASTER_R0_G10_FINAL.md` | added |
| `.github/workflows/ci.yml` | `ci.yml` + `backend-ci.yml` + `frontend-ci.yml` + `integration-ci.yml` | reusable workflows, top-level `needs` |

## Path-dependent code found (must change with the move)

- `create_app(database_url="sqlite:///qualityops.db")` and `alembic.ini sqlalchemy.url = sqlite:///qualityops.db`: relative to the CWD.
- `model_provider.read_key()`: reads `.env` from the CWD.
- `main.py` `/reference-models/steel`: reads `docs/steel_eval.json` from the CWD.
- Scripts write `docs/*.md|json` and `data/uci/…` relative to the CWD.
- `tests/test_health.py`: `parents[1] / "app" / "static" / "web"`.
- `web/vite.config.ts`: `outDir: '../app/static/web'`.
- CI: installs/tests from the root.

## Contracts kept identical

Public HTTP paths and schemas (OpenAPI hash above), `create_app` / `app.main:app`, `/health` body, `/app` static
mount, `/ui` legacy page, SQLAlchemy models and migration history, document / policy / template / evidence hashes,
approval and audit-chain semantics, Experience Memory ranking, Meta tool schemas (hash above), TEST_DOUBLE behaviour.

## Work units and rollback points

1. R0-A: this file + spec documents (docs only).
2. R0-B: backend move + path fixes (one commit; revert = `git revert <sha>`).
3. R0-C: frontend move + module split + tests (one commit).
4. R0-D: docs reorganisation, link fixes, CI split (one commit).
5. R0-E: parity evidence appended here.
