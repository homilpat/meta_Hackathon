# Agent hybrid planner, ask-back, D0 "fill it?" and the simple NCR route (after AG5, 2026-10-31)

Why: the first Meta LIVE runs showed that the time went into **model rounds**, not server work. Server tools took about
1.8 s; the model took 10–25 s. Each round re-read large tool results and reasoned again. Intent detection itself was
cheap: the first round used 13–78 reasoning tokens, against 800–2,700 in later rounds.

## What changed

| Area | Change |
|---|---|
| Planner (`backend/src/app/agent.py`) | **One planning call.** The server sends a situation card (user, role, D0 route, 8D state, document states, closure readiness, my tasks, the tools this role may use). The model returns a strict JSON plan `{intents, tools, clarify}` (`response_format` json_schema, strict). The server executes the plan. The tool loop is gone. |
| Role-scoped tools | Only an AUTHOR is offered `prepare_document`. A tool outside the role's list is recorded as DENIED and not run. |
| Optional summary | Only for an investigation, one more call writes a short summary from the server's own lines, labelled PROPOSAL. Cited ids are checked against the case. |
| Ask-back | A vague goal stops with `NEEDS_HUMAN` `clarify` instead of guessing. This applies to the offline planner when no intent matches, and to the model planner when it returns a `clarify` question. The user's answer is appended to the goal and planned again (`resume {token, confirm, answer}`). |
| 8D report wording | A goal asking for the "8D 보고서/리포트" gets a first line explaining that the final report exists only at D8 closure. The run then shows status and exports, and drafts only if a draft was asked for. |
| D0 "채울까요?" | Goals about whether or how to start (판정 / 8D로 갈지 / 단순 처리 …) end with `NEEDS_HUMAN` `offer_fill`. On **yes**, `fill_triage` (kind PROPOSE) returns a D0 form filled by fixed server rules from the case's own evidence. The rules cover SPC alarm, human-confirmed defects, scope lots and shipped panels, giving a route of NCR_ONLY / FULL_8D / EMERGENCY_FULL_8D, a severity, a rationale and evidence ids. **Nothing is stored.** The person with the D0 role (policy: REVIEWER) reviews, edits and submits it to the existing `POST /cases/{id}/triage`, which re-checks every rule. If D0 is already recorded, there is no offer. |
| Simple route (NCR_ONLY) | The policy already closed NCR_ONLY cases after D0–D3. Now: (1) the agent does not prepare an RCA on that route and says the case can close after D3; (2) the closure report shows D4–D7 as `N/A (NCR_ONLY)`, leaves out empty not-required sections, and is titled **"NCR closure report"** (`{case}_NCR_closure_report`). |
| Provider | `chat(..., response_format=None)`; `tools` is omitted when empty. |
| UI (`RunView.tsx`, `Agent.tsx`) | Answer box for `clarify`, yes/no for `offer_fill`, and an editable D0 form card. Submit is enabled only for the D0 role; otherwise it shows "제출 권한: REVIEWER". New example goals. |

## Tests
- `backend/tests/test_agent_hybrid.py` (new, 5):
  - a vague goal is asked back and the answer planned (repeat answer → 409)
  - the 8D report note
  - the model planner's clarify
  - D0 offered first, filled only after yes, nothing stored; the filled form passes the server's own D0 rules when bob submits it; no second offer
  - NCR_ONLY end to end: D0 simple → D2/D3 approved → D3 action verified → closure (customer notification required because L03 has shipped panels) → "NCR closure report" with `N/A (NCR_ONLY)`; the agent offers the report link
- `backend/tests/test_agent_ag2.py`: model-planner tests rewritten for the one-call plan:
  - one strict-JSON call; the forbidden tool is never offered and is denied
  - the reviewer is never offered drafting
  - provider error or broken JSON → server plan
  - the citation flag
- `backend/tests/test_agent_ag3.py`: the model can prepare but never send.
- `frontend/tests/Agent.test.tsx`: +2 (clarify answer sent with the token; offer → filled form whose submit is disabled for a non-D0 role and never auto-submitted).

## LIVE timing (muse-spark-1.3, one run each; see `docs/evaluations/META_LIVE_LOG.md`)

| Goal | Calls | Wall |
|---|---|---|
| "8D로 가야 할지 판정해 줘" | 1 | 4.9 s |
| "불량 원인 조사해 줘" | 2 | 24.6 s (summary ≈ 20 s) |
| "조사 + 8D 보고서 초안" | 2 | 28.0 s |

Before (multi-round loop): 11.7 s and 25.5 s. Planning is now about 5 s. The optional summary call dominates what remains.

## Verification (local)

| Check | Result |
|---|---|
| full backend `pytest` | 293 passed |
| `ruff check .` | All checks passed |
| `scripts.integration_smoke` (real uvicorn; real `.env` present, offline honoured) | 27/27 |
| `scripts.e2e_http` | 3/3; the full-8D closure snapshot hash is unchanged (`9c378117190f7608`) |
| frontend typecheck / vitest / build | PASS / 25 passed (3 runs in a row) / bundle committed (LF) |
