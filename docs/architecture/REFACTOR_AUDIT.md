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

## R0-B … R0-D — what changed (commits on `main`)

| Phase | Commit | Local checks |
|---|---|---|
| R0-A | `334cf8d` | baseline above; docs only |
| R0-B | `365e91c` | from `backend/`: pytest 226 passed; ruff 0; scratch `alembic upgrade head` + `alembic check` clean; OpenAPI byte-identical (89 ops); tool SPECS / HISTORY_SPECS / HYBRID_SPECS identical (the earlier hash differed only because `ARGS` holds Python sets whose `str()` order varies per process); `history_compare` / `token_budget` output identical to a `58d316a` worktree run except the printed docs path; uvicorn started from an unrelated directory served `/health` `/app/` `/ui` `/me` `/reference-models/steel` = 200 |
| R0-C | `0fd4927` | `tsc --noEmit` (also `--noUnusedLocals`) 0; vitest 9 passed; vite build 0 (CSS byte-identical, JS +0.3 kB for `ApiError`) |
| R0-D | `f714321`, fix `ac5cd20` | `scripts.integration_smoke` 19/19; ruff 0 after the fix; relative markdown links 0 broken |

Behavioural notes:
- `.env` lookup: the working directory is still read first (kept for `test_key_loads_from_local_env_file`), then the repo root.
- Default DB moved from "`qualityops.db` in whatever directory you started in" to `backend/qualityops.db` (or `DATABASE_URL`). The old root file is not read.
- The committed `docs/evaluations/TOKEN_BUDGET.md` / `token_budget.json` were stale since G5–G8 (summary 1055 → 1065 chars); regenerated, same output as `58d316a`.
- Frontend split is a verbatim cut of `App.tsx` (generated by line range, then `export` added); the only logic change is that `request()` lives in `api/client.ts` and raises `ApiError`, which `App` turns into the same error-bar text and the same `Error(status)` throw. The Experience Memory card moved into `features/experience/ExperienceCard.tsx` with its state passed as props.

## R0-E — parity and acceptance (HEAD `ac5cd20`)

| Exit criterion (§19.5 / MASTER R0-E) | Evidence | Result |
|---|---|---|
| 1. `frontend/src,tests` and `backend/src,tests` hold real code | 37 + 21 backend files moved, 22 frontend source files, 2 frontend test files | PASS |
| 2. install / dev / build / serve paths | editable install from `backend/`; `npm ci`-equivalent install, build into `backend/src/app/static/web`; uvicorn serves `/app`, `/ui` | PASS (Vite dev server: `/app/` 200, `/health` and `/me` proxied to uvicorn :8000) |
| 3. 226 tests before vs after | baseline 226 passed at `58d316a` (root); 226 passed at `ac5cd20` from `backend/` (277 s); no test removed or edited except the static path in `test_health.py` and one comment | PASS |
| 4. permissions / approval / evidence / 8D / Experience Memory / validator / TEST_DOUBLE / audit contracts | full pytest; integration smoke (403 unassigned, 403 self-approval, 409 stale hash, validator WARN/PASS, KNOWN retrieval, 503 without key, audit chain ok) | PASS |
| 5. imports, pytest discovery, Alembic, static assets, scripts, links | as above; `scripts.history_compare` / `token_budget` / `integration_smoke` from `backend/` | PASS |
| 6. Backend / Frontend / Integration CI on the same SHA, integration not bypassable | CI `#36` on `a462edf`; `#34` showed the gate | PASS |
| 7. small commits + this audit | 4 phase commits + 1 fix | PASS |
| Browser check | `/app` on uvicorn (scratch DB): created the SMT line case, opened D0~D8, Experience Memory retrieval refused with the server's 409 text before process context, then KNOWN with 6 matches | PASS |
| Old DB protected | root `qualityops.db` sha256 prefix `e39fac5e96ad602b` before and after; no `backend/qualityops.db` created by tests | PASS |

CI (GitHub Actions, workflow `CI`): R0-A `#31`, R0-B `#32`, R0-C `#33` succeeded. `#34` (`f714321`) failed in
`backend` (ruff RUF059) while `frontend` succeeded and `integration` was **not run** — the `needs` gate held (TC-R0-03).
`#35` (`ac5cd20`) failed in `backend` pytest: `test_audit_tables_are_append_only` and
`test_migration_backfills_the_chain_for_existing_audit_rows`. Cause (a real R0-B regression, invisible locally because
no `DATABASE_URL` was set there): `backend-ci.yml` sets `DATABASE_URL` for the whole job and the new
`migrations/env.py` let it override the URL those tests pass with `Config.set_main_option`, so their migrations ran
against the CI scratch file. Fix: `DATABASE_URL` now replaces only the `alembic.ini` default; a caller-set URL wins.
Reproduced and verified locally with `DATABASE_URL` set: the 2 tests pass, the CLI `alembic upgrade head` still
follows `DATABASE_URL`, and the full suite under the same condition: 226 passed (272 s).

`#36` (`a462edf`) **succeeded** in all three jobs (backend, frontend, integration; 11 m 37 s). R0 = **PASS**.
