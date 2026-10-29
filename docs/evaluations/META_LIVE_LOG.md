# Meta LIVE log

Each row is a command actually run on this machine. No secret is ever recorded.

| Date (KST) | Command | Model | Outcome | Latency / tokens |
|---|---|---|---|---|
| 2026-10-28 | `python -m scripts.meta_smoke` | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, `LIVE NOT TESTED: MODEL_API_KEY is unset`, no network call | n/a |
| 2026-10-28 | `python -m scripts.meta_investigate_smoke` | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, no network call | n/a |
| 2026-10-29 | `python -m scripts.meta_smoke` (phase E, after G10) | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, `MODEL_API_KEY` empty in `.env` and environment, no network call | n/a |
| 2026-10-29 | `python -m scripts.meta_investigate_smoke` (phase E) | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, no network call | n/a |

Status: LIVE Meta has **never** succeeded in this repository. All model-path tests use a provider with
`mode = "TEST_DOUBLE"`, and runs from it are stored with `mode = TEST_DOUBLE`.

`GET /provider` → `live_status`: `NOT_CONFIGURED` (no key) · `TEST_DOUBLE` · `CONFIGURED_NOT_VERIFIED` (key present,
no validated LIVE run in this DB) · `VERIFIED` (at least one `model_runs` row with `mode=LIVE, status=VALIDATED`).
The UI shows "키 설정됨 (LIVE 미검증)" until `VERIFIED`.

To unblock: put `MODEL_API_KEY=...` in the git-ignored `.env`, run both smoke scripts (may incur charges), and add
the printed outcome line here.
