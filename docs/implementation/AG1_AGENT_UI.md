# AG1 — Agent-First shell and UI (spec §22.2, §22.5, §22.7)

Frontend only. No backend route, model or migration changed. The `/agent/*` API arrives in AG2/AG3. Until it does, the
Agent screen shows its fallback state ("Agent 서비스에 연결할 수 없습니다"), which is the same path a real outage takes.

## What changed (`frontend/src`)

| Area | Change |
|---|---|
| `App.tsx` | Default screen is **AI Agent**. The primary menu has AI Agent, 내 할 일, 부서 할 일, 승인 대기 and 사건 · 개요. All 9 existing screens move unchanged into a collapsible **전문 도구 · 상세 화면** group (`aria-expanded`), which opens automatically when one of them is active. A case badge is added in the header. The error bar gets `role="alert"`. |
| `features/agent/Agent.tsx` | Goal composer, sent with `POST /agent/runs {case_id, goal}` and an Idempotency-Key (Enter sends; IME composition is respected). Runs are restored from `GET /agent/runs?case_id=` on every entry, user change or case change. Resume uses `POST /agent/runs/{id}/resume {token, confirm, reviewer_id}`. A ref guard allows one request at a time. The planner label comes from `/provider` and never says LIVE unless `live_status=VERIFIED`. When the API is down, the fallback links to 내 할 일, 승인 대기, D0~D8 and 문서 · 결재. |
| `features/agent/RunView.tsx` | Renders a persisted run as returned: the plan with per-item status, server-written reply lines (with step references), and one card per recorded step. Read cards: case summary/LOT table with evidence ids; SPC chart (reusing `ControlChart`); prediction + SHAP marked as model output; evidence gaps; experience mode; history; 8D stages; queue. Write cards: draft marked "승인 아님", validation result/issues, review state. Denied or failed steps show the server's error, and audit event ids link to the audit screen. Pending decisions (`confirm_scope`, `request_review` with the server's candidate reviewers, `await`) are answered only by explicit clicks. |
| `features/agent/ContextPanel.tsx` | The right-hand panel on the Agent and queue screens, read from the same routes as the detail screens: `/stages`, `/evidence-quality` counts, `/queue` mine and department, plus approval-gate locks. |
| `features/queue/Queue.tsx` | One component, three menus: `scope` = mine / department / approvals. Approvals are REVIEW and BASIS_CHECK items from the department queue. No new backend queue. |
| `index.css` | Layout from the Figma Make mock-up `agent_first design/` (not committed): sidebar group, chat, plan rows, tool cards, composer, context panel, fallback. It uses the existing tokens and the current font scale (the mock-up is 7–9 px). Adds a visible keyboard focus ring. |
| `vite.config.ts` | `/agent` added to the dev proxy list. |

The mock-up's numbers, names, evidence ids, "실시간" badges and the "META 시연 상태" label were **not** copied. Every value
on screen is bound to an API response.

## The run contract the UI expects (AG2/AG3 must serve it)

Each run has these fields:
- `run_id`, `case_id`, `user_id`, `goal`
- `planner`: `SERVER_RULES`, `LIVE` or `TEST_DOUBLE`
- `status`: `PLANNED`, `RUNNING`, `NEEDS_HUMAN`, `BLOCKED`, `FAILED` or `COMPLETED`
- `plan`: a list of `{tool, title, status, note}`
- `reply`: a list of `{text, steps, handoff?}`
- `pending`: `{action, token, …}` or null
- `steps`: a list of `{seq, tool, kind, status, http_status, result, error, audit_event_ids, duration_ms}`

This contract is pinned by `frontend/tests/Agent.test.tsx`.

## Verification (local, 2026-10-31)

| Check | Result |
|---|---|
| `npm run typecheck` | PASS |
| `npm test` | 22 passed (6 files): App 8, Agent 5, existing 9 |
| `npm run build` | PASS; bundle committed under `backend/src/app/static/web` |
| `python -m scripts.integration_smoke` (real uvicorn, scratch DB, `/app` + assets, `/ui`, G8–G10 flows) | 24/24 |

The page was not opened in a real browser in this phase. Layout and accessibility are checked through the jsdom
tests: roles, labels, `aria-expanded`, `aria-current` and progressbar values.
