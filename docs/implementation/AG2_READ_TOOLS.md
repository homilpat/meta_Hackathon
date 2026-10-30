# AG2 — Server planner and read-only tool orchestration (spec §22.3, §22.4, §22.7)

The Agent now has a backend. A goal becomes a persisted run of allowlisted **read-only** tools that the server executes
as the signed-in user. There are no write tools in AG2. A goal asking for a draft only reads document state, and the
run says drafting is not on the allowlist yet. Allowlisted writes are AG3.

## Code

| File | What |
|---|---|
| `backend/src/app/agent.py` | Planner, executor and `/agent/*` routes (details below). |
| `backend/src/app/db.py`, `migrations/versions/0017_agent_runs.py` | `agent_runs` (mutable status; unique `(user_id, idem_key)`) and `agent_steps` (append-only, added to `APPEND_ONLY` with matching triggers). |
| `backend/src/app/main.py` | Registers the agent router. No existing route changed. |
| `frontend/src/features/agent/RunView.tsx` | Adds the `documents` card. |
| `backend/scripts/integration_smoke.py` | Real-HTTP agent checks: offline read-only run, restore, privacy. |

What `agent.py` contains:
- **Planner.**
  - **Offline:** keyword intents (조사·분석 / 초안·8D / 할 일 / 진행·상태) map to a fixed read plan, always starting with `case_summary` and ending with `queue`.
  - **With a provider (LIVE or TEST_DOUBLE):** the model picks tools from the allowlist. Every call is executed and recorded by the server, and the model's final text is stored as `PROPOSAL, 서버 확인 아님`. Nothing outside the allowlist is ever offered to the model. A tool it names anyway is recorded as `DENIED` and not executed.
  - **Model failure:** a `ProviderError` falls back to the offline plan.
- **Executor.** It calls the existing route handlers as the user, so `require_case`, roles, policy and audit apply unchanged. FastAPI 0.162's nested routers are walked the same way `tests/test_s6_followups.py` walks them. The tools:

  | Tool | Source |
  |---|---|
  | `case_summary`, `data_integrity`, `predictions` (+ top SHAP), `experience`, `history` | `EvidenceTools`, which applies the egress gate and role scope |
  | `spc` | `GET /cases/{id}/spc` |
  | `evidence_gaps` | `GET /cases/{id}/evidence-gaps` |
  | `stages` | `/stages` + `/gates` |
  | `documents` | latest version + latest validation per kind |
  | `queue` | `/queue` mine + department |

  Each step stores tool, args, status, HTTP status, result, error, duration and the ids of workflow events the step created.
- **Reply lines** are written by the server from recorded step results only, and each line names its step numbers.
- **Scope check (AG-T01).** A goal naming another known case, or a LOT the case does not have, stops after `case_summary` with `NEEDS_HUMAN` / `confirm_scope`. Nothing else runs on a guessed scope.
- **Resume.** `POST /agent/runs/{id}/resume {token, confirm}` claims the pending decision in one transaction. A repeated or stale token gets 409.
- **Crash handling.** A crash never leaves a run `RUNNING`: a `finally` marks it `FAILED`, and the error still surfaces as a 500.
- **Audit.** `AGENT_RUN` and `AGENT_RESUMED` go into the audited workflow log.

Routes: `GET /agent/tools`, `POST /agent/runs` (Idempotency-Key; the same key returns the same run), `GET /agent/runs?case_id=`
(caller's own runs only), `GET /agent/runs/{id}` (404 for another user), `POST /agent/runs/{id}/resume`.

## Tests — `backend/tests/test_agent_ag2.py` (8)

| Test | Spec case |
|---|---|
| offline plan runs read tools only and is grounded | AG-T07. `SERVER_RULES`, all steps READ, no document created by a draft request. Reply lines reference recorded steps; cited evidence ids exist in the case; the SPC card equals `GET /spc`; `AGENT_RUN` audited. |
| run persisted, restored, private | AG-T08, AG-T12. List and get return the same run; another user gets 404 and an empty list; the queue tool runs with the caller's own role. |
| unassigned user cannot run | permission filter: 403 not assigned, 404 unknown case, no run row |
| same Idempotency-Key, same run | AG-T09 for run creation |
| unknown LOT / other case asked back | AG-T01. Only `case_summary` ran; confirm continues; a repeated answer gets 409; another user gets 404; decline completes with nothing run. |
| model planner allowlist | AG-T06/T02 (read side). `approve_document` never offered; requested anyway → `DENIED`; no document; model text labelled PROPOSAL, not LIVE; the model receives the server's SPC result unchanged. |
| model failure falls back | AG-T07 with a provider: `ProviderError` → server plan completes; no duplicate `case_summary` |
| agent steps append-only | DB trigger refuses an UPDATE |

## Verification (local)

| Check | Result |
|---|---|
| `pytest tests/test_agent_ag2.py` | 8 passed |
| full backend `pytest` | 269 passed (261 before + 8 new) |
| `ruff check .` | All checks passed |
| fresh scratch DB `alembic upgrade head` → `0017_agent_runs`; `alembic check` | no drift |
| `scripts.integration_smoke` (real uvicorn) | 27/27, including agent offline read-only run, restore, privacy |
| frontend typecheck / 22 vitest / build | PASS |

Meta LIVE is still `BLOCKED_NO_CREDENTIALS`. Only the TEST_DOUBLE planner path is tested, and it is labelled as such.
