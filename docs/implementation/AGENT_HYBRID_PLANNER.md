# Agent hybrid planner, ask-back, D0 "fill it?" and the simple NCR route (after AG5, 2026-10-31)

Why: the first Meta LIVE runs showed that the time went into **model rounds**, not server work. Server tools took about
1.8 s; the model took 10–25 s. Each round re-read large tool results and reasoned again. Intent detection itself was
cheap: the first round used 13–78 reasoning tokens, against 800–2,700 in later rounds.

## What changed

| Area | Change |
|---|---|
| Planner (`backend/src/app/agent.py`) | **One planning call.** The server sends a situation card (user, role, D0 route, 8D state, document states, closure readiness, my tasks, the tools this role may use). The model returns a strict JSON plan `{intents, tools, clarify}` (`response_format` json_schema, strict). The server executes the plan. The tool loop is gone. |
| Role-scoped tools | Only an AUTHOR is offered `prepare_document`. A tool outside the role's list is recorded as DENIED and not run. |
| Optional summary | Only for an investigation, one more call rewrites the server's numbered fact lines as natural sentences (strict JSON: text + the fact numbers each line is based on). `check_polish` shows the rewrite only if every line names facts, uses only those facts' numbers and writes no ids (wording is free; no length rule); otherwise the server lines stand alone and the reason is recorded on the `summarize` step. Evidence ids are attached by the server to every fact line and to each rewritten line (from the facts it names). The SPC fact line states the lot mean against the chart's reference lot centre line. |
| Recommendations | The same call may return up to 3 recommendations (the model's inference). `check_recommendations` shows one only if it names at least one fact backed by this case's evidence, cites only sources the server retrieved in this run (past cases, Experience Memory, controlled documents via the new `references` read: FMEA / control plan / SOP; with a model, its search terms come from a `search_query` MODEL step that reads the facts so far, falling back to a fixed query offline or on failure, and the query used is shown), cites no negative (failed-before) source, and uses only numbers from what it names. Shown with the facts' evidence ("근거") and its sources ("참고"); rejected ones are listed with the reason. Whether the basis really supports it is the human's call. Investigation reports follow the same base rule: a next check without evidence ids from the case fails validation. |
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

Before (multi-round loop): 11.7 s and 25.5 s. Planning is now about 5 s. The optional summary call dominated what remained.

**Follow-up: the summary call runs at `reasoning_effort=minimal`.**
- A probe on the real summary payload gave 13.4 s → 3.2 s, with reasoning tokens 3,803 → 140 and the same answer and citations.
- The investigation run measured LIVE in 9.3 s (was 24.6 s).
- The planning call keeps the default effort, because choosing tools is a judgement.
- `MetaProvider.chat` takes `reasoning_effort` and sends it only when given; `tests/test_meta_smoke.py` pins this.

## Router + fixed workflows (follow-up, 2026-10-31)

Why: LIVE runs of the same goal chose different tools. For a quality investigation that is not reproducible, and it is
hard to audit. In practice, regulated work keeps the procedure fixed and lets the model classify.

| Change | Detail |
|---|---|
| Model = classifier only | The plan call returns `{intents, clarify}` (strict JSON; any extra key is ignored). The tools for each intent are fixed by `server_plan`, the same plan the offline planner runs. Same intent → same tools, LIVE or offline. |
| Role | The situation card says `may_draft_documents`. A reviewer asking to draft gets the same plan as offline, and the existing route refuses the draft (403 → BLOCKED). Enforcement stays on the server. |
| Server rule after the model | `report_rule`: a request for the 8D report always adds STATUS + EXPORT, whichever planner ran. |
| Model calls are steps | `plan` and `summarize` are recorded as `kind=MODEL` steps with model, mode, `prompt_version` (`PLANNER_VERSION` / `SUMMARY_VERSION`: hashes of prompt, schema and fixed plans), reasoning effort, latency, and the result or error (502). |
| Cost cap | More than `MODEL_RUNS_PER_USER_HOUR` (30) model-planned runs per user per hour → the server rule planner takes over, with a reply line. The work is not blocked. |
| Killed process | A run left `RUNNING` by an earlier process is marked FAILED on the first agent request after a restart. |
| Golden set | `backend/scripts/intent_golden.json` (25 tuning + 5 held-out). `python -m scripts.intent_eval` runs the same `classify` the agent uses, and writes `docs/evaluations/intent_eval.json`. LIVE: tuning 25/25, held-out 5/5; offline rules: 25/25 and 3/5. The tuning sentences shaped the prompt and the rules; the held-out set is only 5 sentences. |

Tests: `test_agent_ag2.py` covers these cases:
- the model only classifies, and the server runs the fixed tools
- LIVE and offline run the same tools
- a reviewer's draft is refused by the route
- a model failure or broken JSON is recorded as an ERROR step and falls back
- the hourly cap hands over to the server planner
- a killed process's run is marked FAILED
- the offline rules match the tuning set

## Verification (local)

| Check | Result |
|---|---|
| full backend `pytest` | 293 passed |
| `ruff check .` | All checks passed |
| `scripts.integration_smoke` (real uvicorn; real `.env` present, offline honoured) | 27/27 |
| `scripts.e2e_http` | 3/3; the full-8D closure snapshot hash is unchanged (`9c378117190f7608`) |
| frontend typecheck / vitest / build | PASS / 25 passed (3 runs in a row) / bundle committed (LF) |
