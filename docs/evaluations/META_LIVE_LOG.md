# Meta LIVE log

Each row is a command actually run on this machine. No secret is ever recorded.

| Date (KST) | Command | Model | Outcome | Latency / tokens |
|---|---|---|---|---|
| 2026-10-28 | `python -m scripts.meta_smoke` | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, `LIVE NOT TESTED: MODEL_API_KEY is unset`, no network call | n/a |
| 2026-10-28 | `python -m scripts.meta_investigate_smoke` | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, no network call | n/a |
| 2026-10-29 | `python -m scripts.meta_smoke` (phase E, after G10) | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, `MODEL_API_KEY` empty in `.env` and environment, no network call | n/a |
| 2026-10-29 | `python -m scripts.meta_investigate_smoke` (phase E) | muse-spark-1.3 | **BLOCKED_NO_CREDENTIALS** — exit 2, no network call | n/a |

| 2026-10-31 | `pytest` (5 files) run before `tests/conftest.py` existed: tests read the new repo-root `.env` | muse-spark-1.3 | **Unintended, at most 1 call**: only `test_g9_docs::test_ai_proposal_is_not_applied_until_submitted_and_offline_keeps_manual_path` reached the provider (one `edit-proposals` chat with a synthetic NCR draft). The two other model-path tests stopped before any call (422 / first assertion). The key went only in the HTTPS Authorization header; a scan of the repo, all git history, the session transcript and temp files found no copy. Fixed by `tests/conftest.py`. | not recorded (temp DB) |
| 2026-10-31 | `python -m scripts.meta_smoke` (key in git-ignored `.env`) | muse-spark-1.3 | **FAILED**: exit 1, `TypeError`. Diagnosis: `finish_reason=length`, content `None`; 30 of 32 tokens went to reasoning, so the answer never started. Fixed: smoke `max_tokens` 64 → 1024; an empty/cut-off reply is now reported by name. | n/a |
| 2026-10-31 | `python -m scripts.meta_smoke` | muse-spark-1.3 | **LIVE SUCCESS**: exit 0, structured `{"status":"ok"}`, model id checked | 2418 ms · prompt 17 / completion 351 |
| 2026-10-31 | Agent-First LIVE planner (`POST /agent/runs` on a scratch DB, synthetic line case, goal "이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘.") | muse-spark-1.3 | **Tool calling works.** Run 1: COMPLETED with 10 reads, all OK; the 11th call `prepare_document` hit the agent's 10-call cap (fixed: cap = number of tools, own wording). Run 2 after the fix: the model chose 8 reads, then `prepare_document` → NCR v1 DRAFT (201) and validation WARN (201) → **NEEDS_HUMAN** `request_review`; no denied step. | run 1 25.5 s · run 2 11.7 s wall |
| 2026-10-31 | `python -m scripts.meta_investigate_smoke` | muse-spark-1.3 | **FAILED**: 4 tool calls OK, then `finish_reason=length` on the final report (provider `max_tokens` 1500). | prompt 3748 / completion 1356 |
| 2026-10-31 | same, `max_tokens` 4096 (round-by-round log) | muse-spark-1.3 | **JSON_ERROR**: round 3 report cut off at 4096 tokens (2488 reasoning). Fixed: any `finish_reason=length` is a provider failure; `max_tokens` 8192, timeout 60 s. | round 3: completion 4096 |
| 2026-10-31 | same, `max_tokens` 8192 (round-by-round log) | muse-spark-1.3 | **VALIDATED**: 3 rounds, report finished (`stop`) and passed the server validator | prompt 2487 / completion 3871 (final round) |
| 2026-10-31 | `python -m scripts.meta_investigate_smoke` | muse-spark-1.3 | **JSON_ERROR**: 3 tool calls OK; the final report did not match the report schema (`ValidationError`) and was refused (fail closed) | prompt 7539 / completion 8410 |

| 2026-10-31 | Agent **hybrid planner** (one strict-JSON plan call with the server's situation card; server runs the tools; optional summary call only for investigations): "이번 SPC 경보, 8D로 가야 할지 판정해 줘" | muse-spark-1.3 | **NEEDS_HUMAN** `offer_fill` after 4 reads, 1 model call | **4.9 s** wall |
| 2026-10-31 | same, "이번 LOT 불량 원인을 조사해 줘" | muse-spark-1.3 | **COMPLETED**: 6 reads + summary (cited ids all exist in the case; none flagged) | 24.6 s wall (plan ≈ 4–5 s, summary call ≈ 20 s) |
| 2026-10-31 | same, "이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘." | muse-spark-1.3 | **NEEDS_HUMAN** `request_review`: 8D-report note → 7 reads → NCR v1 DRAFT (201) + validation WARN (201) → summary | 28.0 s wall |

| 2026-10-31 | Probe: model list and `reasoning_effort` on the agent's real summary payload (seeded synthetic case) | muse-spark-1.3 / 1.2 / 1.1 | Models available to the key: muse-spark-1.3, 1.2, 1.1, -contributor variants, muse-voice/image, sam-3.1. Same summary task: 1.3 default 13.4 s (reasoning 3,803); **1.3 `reasoning_effort=minimal` 3.2 s (reasoning 140)**; 1.2 7.1 s; 1.1 8.2 s. Answer length and citation validity were the same in all four. | see outcome |
| 2026-10-31 | Agent hybrid planner with the summary call at `reasoning_effort=minimal` (plan call unchanged, default effort): "이번 LOT 불량 원인을 조사해 줘" | muse-spark-1.3 | **COMPLETED**: 6 reads + summary; cited ids exist in the case | **9.3 s** wall (was 24.6 s) |
| 2026-10-31 | `python -m scripts.intent_eval` (planner 4dacb0097ac4, intents only) | muse-spark-1.3 | 23/25: "승인 대기 중인 거 뭐 있어?" → STATUS (want TASKS); "8D 리포트 보여줘" → STATUS only. Fixed: TASKS definition/example in the prompt; the server's 8D-report rule now also runs after the model. | median 2.9 s, max 6.6 s per call |
| 2026-10-31 | `python -m scripts.intent_eval` (planner 0fff6496e8c5) | muse-spark-1.3 | **30/30**: tuning 25/25, **held-out 5/5** (offline keyword rules: held-out 3/5) | median 2.8 s, max 5.5 s per call |
| 2026-10-31 | Agent, router + fixed workflows, the same goal twice: "이번 LOT 불량 원인을 조사해 줘" | muse-spark-1.3 | **COMPLETED both times with the identical 8 reads** (fixed INVESTIGATE workflow); plan and summary recorded as MODEL steps | 8.7 s and 9.8 s wall (plan 2.9 / 3.4 s, summary 3.5 / 4.0 s) |
| 2026-11-01 | `python -m scripts.intake_live_check`: separate LIVE fixture `live_complaint_DS-QN-2026-0099.pdf` (2 pages: text, table as lines, photo with an instruction in its caption, blurred chart capture) → server parser → Muse extraction (strict JSON `intake_extract`, element JSON + 2 PNG data URLs, `reasoning_effort=minimal`) → server source checks | muse-spark-1.3 | **8/8**: customer_ref, LOT L05, defective qty 7, part, delivery and found dates FOUND with the right locators (`pdf:p1:l3/l12/l14/l4`); inspected qty MISSING; cause guess FOUND as HYPOTHESIS; absolute deadline not flagged; no-rate note; caption instruction flagged; image linked; 0 values rejected; classified COMPLAINT; asked for the inspected quantity and the chart values (`docs/evaluations/intake_live.json`) | 8.4 s |
| 2026-11-01 | IN0 multimodal probe: a synthetic PNG as an `image_url` data-URL part, and a synthetic one-page PDF as a `file` part (`reasoning_effort=minimal`) | muse-spark-1.3 | **both accepted**: "LOT L02 qty 12 CR-777" and "LOT L03, 7 boards, CR-888", both correct. Scanned PDF / tables / DOCX not tested | 1.9 s and 4.1 s |
| 2026-11-01 | Agent "이번 LOT 불량 원인을 조사해 줘" with the model-chosen document query and evidence-based recommendations (efe4b7d) | muse-spark-1.3 | **COMPLETED**: 3 calls (plan, search_query, summarize). Query "AOI solder paste volume low inspection disagreement FMEA control plan" → CP-SMT-001, FMEA-SMT-001, SOP-SMT-010. 5 rewritten lines, 0 issues; 3 recommendations, 0 rejected, each with case evidence and retrieved sources (HIST:H01:STENCIL_CLEAN, EXP:X01, SOP-SMT-010; H03; CP-SMT-001, FMEA-SMT-001) | **17.1 s** wall (plan 5.0 s, query 3.7 s, summarize 6.8 s) |
| 2026-10-31 | **Unintended** (a local check script run outside pytest read `.env`): agent "불량 원인 조사해 줘" with the summary as a strict-JSON rewrite of the server facts + `check_polish` | muse-spark-1.3 | **COMPLETED**: 2 calls (plan, rewrite); all 5 rewritten lines passed the number/id/length check and were shown with their facts' evidence | not timed |
Status (2026-10-31): **LIVE Meta works.** The structured smoke passed, and Agent-First LIVE tool calling went from goal to tools, a
server-checked draft, and a stop for the human. The LIVE investigation *report* validated in 1 of the 2 runs made after the token fix. The
other run's report did not fit the schema and was refused, as designed. So report-format reliability is the open item; the
tool-calling path is not. Automated tests still use only `mode = "TEST_DOUBLE"` providers, and tests can never read a real key
(`backend/tests/conftest.py`).

`GET /provider` → `live_status`: `NOT_CONFIGURED` (no key) · `TEST_DOUBLE` · `CONFIGURED_NOT_VERIFIED` (key present,
no validated LIVE run in this DB) · `VERIFIED` (at least one `model_runs` row with `mode=LIVE, status=VALIDATED`).
The UI shows "키 설정됨 (LIVE 미검증)" until `VERIFIED`.

To unblock: put `MODEL_API_KEY=...` in the git-ignored `.env`, run both smoke scripts (may incur charges), and add
the printed outcome line here.
