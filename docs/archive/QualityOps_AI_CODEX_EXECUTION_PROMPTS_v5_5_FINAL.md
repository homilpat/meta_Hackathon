# QualityOps AI — Codex / Claude Code 실행 프롬프트 v5.5 FINAL (G5~G10 · Meta LIVE · 안정화)

**현재 기준:** `homilpat/meta_Hackathon`의 2026-10-28 최신 확인 커밋 `4dbb03d5f429ce1672839c19c0da640d6f190d08`. 실제 착수 시 현재 HEAD가 더 앞서 있으면 그 구현을 기준으로 차이를 계산한다.  
**첨부:** `QualityOps_AI_FINAL_REQUIREMENTS_v5_5_FINAL.md` (필수). 원래 v3/v4/v5는 비충돌 상세 설명만 참고한다.  
**범위:** G0~G4 재구현 금지 / G1은 credentials 블로커 유지 / **PREFLIGHT + G5~G10 구현** / G9 후 P0 통합 감사 / G10 후 Meta LIVE(키 확보 시) 및 안정화. 신규 기능 확장 금지.

## MASTER — 첫 메시지 (그대로 복사)

```text
You are the implementation agent for the EXISTING repository
homilpat/meta_Hackathon. Read QualityOps_AI_FINAL_REQUIREMENTS_v5_5_FINAL.md,
docs/V5_IMPLEMENTATION_STATUS.md, docs/V5_GAP_MATRIX.md,
docs/V5_IMPLEMENTATION_PLAN.md, HACKATHON_WORK_LOG.md, README.md,
SECURITY.md, migrations, tests, and current source files.

The previously verified remote HEAD was 4dbb03d (2026-10-28 KST).
Recheck actual git HEAD, branch, remote and working tree; do not reset
history, discard user changes, force-push, or treat stale docs as code truth.

Existing and NOT to be rebuilt:
G0 audit/gap matrix, G2 WorkflowPolicy+EvidenceQuality+PCB adapter,
G3 D0 triage/urgent simulated containment/D1 team,
G4 5W2H/IS-IS NOT NCR + D3 action lifecycle/scope checking,
S0-S7 Evidence Registry/SPC/case/ML-XAI/history/audit/React.
The latest commit reported 169 pytest passed, Ruff clean, fresh migration
and UI build OK; do NOT claim those results as freshly reproduced.
G1 provider status work exists but Meta LIVE remains BLOCKED_NO_CREDENTIALS
until a legitimate key is configured. Never request, print or commit keys.

Your task: PREFLIGHT integration repair, then G5, G6, G7, G8, G9 IN ORDER.
At G8, implement Experience Memory (KNOWN/ANALOGICAL + NO_RELEVANT_HISTORY fallback),
historical verified-action priority recommendation, negative precedent
(failed/inconclusive/recurrent), and
hybrid Meta evidence-gap investigation; keep human choice, no auto-approval.
After G9, audit all integrated systems and fix only critical correctness,
authorization, audit, evidence and data-integrity defects. Write a separate
POST_G9_REFACTOR_PLAN.md for cosmetic/refactor opportunities.
After G9 and its P0 audit, CONTINUE to G10 export, final single-case E2E,
then conditional Meta LIVE verification and stabilization. Do NOT submit
to the contest automatically; prepare materials for owner review.

Important bug-risk: the old app/workflow.py fixed D2-D4 approval chain and
app/policy.py's policy gates are not yet unified. First inspect both and
make one authoritative approval decision path with a compatibility adapter.
Maintain historical document hashes/approvals and do not let formal
document order delay D0-authorized urgent action. Add disagreement tests.
Other known gap: app/factcheck.py checks cited lots/units/superseded rows,
but does NOT validate every author-calculated numeric predicate yet (G8).
Do not claim all hallucinations are blocked.

Preserve existing modules and schema. Reuse app/actions.py Action/ActionEvent
instead of creating duplicate execution stores; use app/eightd.py, policy.py,
quality.py, process.py, report.py, factcheck.py, db.py and current React UI.
Add additive Alembic migrations when necessary; support preexisting records.
Keep AI access read-only; SQL/rule/statistical checks deterministic.
SYNTHETIC/SIMULATED physical events must never be presented as real operations.
A model suggestion, a matching source ID, or SHAP are not causal proof.
Assume existing security protections must not regress (egress allowlist,
role/assignment, append-only audit/hash chain, idempotency, concurrency).

For EACH gate: inspect HEAD and define a concrete delta; write normal plus
adversarial tests; implement minimally; run Python 3.12 pytest, Ruff,
fresh Alembic upgrade and migrations/schema checks, and npm build if the UI
changes. Exercise relevant HTTP routes and UI behavior where feasible.
Maintain source/evidence/policy/template hash validation on approval.
Do NOT weaken tests, invent HTTP/model metrics or claim blocked LIVE success.
Record exact executed commands and honest outcomes in work log + status docs.
Commit and push each successful gate to the verified intended branch if
authorized by this development workflow; never force-push. On failure,
stop dependent gates and report the blocker, not a fabricated green result.
At completion provide changed files, migration names, test results,
commit SHA, push status, remaining risks and the next gate.
```

## PREFLIGHT — G5 시작 전 기존 정책/승인 불일치 최소 수정

```text
Inspect workflow.py KINDS/APPROVER/PREREQ/_based_on, policy.py
can_approve/can_execute_urgent/can_close, eightd.py, actions.py,
and all existing S6 and v5 approval tests. Identify any route where
the old chain and the active versioned WorkflowPolicy disagree.
Add one authoritative approval-gate service (or thin compatibility
adapter) for D2-D4 and make new gates consume it. Preserve historical
approvals/content hashes and exact S6 semantics when DEFAULT policy
applies; ensure urgent containment can execute after D0 before
D1/D2, without faking a D3 document approval.
Test policy-vs-old approval disagreement, stale policy version,
self-approval, legacy approved snapshot, D0 urgent execute, concurrent
approve/source-correction race, and audit hash-chain.
Do not introduce a separate BPMN engine or rewrite all workflow routes.
Deliver a small isolated commit and documentation.
```

## 진행 순서 — 각 게이트 독립 테스트·커밋·푸시

아래 G5~G9는 직전 v5 프롬프트의 실질적 구현 의도를 유지했으며, 기존 G2~G4 엔터티를 재사용한다.

## G5. D4 원인 탐색을 Hypothesis→Experiment→Decision으로 변경

```text
G5 — Extend current RCA/HYPOTHESIS while preserving its historical document
versions. Add 4M/optional 4M1E/6M branches, Fishbone structure, 5Why links,
occurrence/non-detection/systemic cause types, counter-evidence and
Experiment records with controls, sample sizes, evidence and reviewer.
Provide one *synthetic documented* experiment showing a supported cause,
and one contradictory experiment yielding REJECTED/INCONCLUSIVE.
No SHAP, retrieved precedent, statistical association or LLM claim can
alone set CONFIRMED. Only qualified human decision after eligible experiment.
Do not require exactly five why-steps; require each actual causal link to
be testable and grounded. Support multiple causes.
Tests: AI causal overclaim, missing evidence, counterevidence,
non-independent reviewer, valid confirmed cause, conflicting root causes.
Acceptance: only real/simulated documented experiment + reviewer can confirm.
```

## G6. D5 영구 시정조치 + D6 실행/효과 검증

```text
G6 — Implement D5 alternatives linked to confirmed cause IDs, feasibility,
risk/side-effects, selected action and pre-execution suitability verification.
D6 is separate: signed execution record, precommitted metric/baseline/post
windows/denominator/inspection comparability/min samples/monitoring and
approval thresholds. Deterministic SQL/statistics calculate results.
If confounding, inadequate samples, different inspection rules or missing
execution -> INCONCLUSIVE/FAILED, not EFFECTIVE. When action fails, reopen
D4/D5 with audit history intact. Allow multiple actions/causes.
Tests: unconfirmed cause, never-executed selected action, sample insufficiency,
criteria changed after results, negative outcome, valid synthetic success.
Acceptance: correct distinction between chosen action and proven effect.
```

## G7. D7 예방·문서 개정 / D8 종결

```text
G7 — Add D7 SOP/FMEA/Control Plan document revision record, effective date,
release approval, rollout/training, sister-line applicability and exceptions.
A report paragraph claiming 'updated SOP' is NOT revision evidence.
D8 close must re-evaluate G2 policy, D0-D7 required gates, EvidenceQuality,
execution/effectiveness, residual risks, customer-specific notifications,
revision freshness and signatures in one atomic decision. Record team
contribution/acknowledgement, keep immutable archive and reopen flow.
Tests: missing FMEA actual revision, untrained operator, open D6 failure,
changed evidence, unauthorized signer, valid closure, forced reopen.
Acceptance: complete synthetic D0-D8 evidence trail and failure/redo path.
```

## G8. 검증·RAG + 하이브리드 Meta 조사 + 과거 검증 조치 우선 추천

```text
G8 — Extend the existing `app/factcheck.py`, `app/report.py` and `app/ncr.py` through ONE authoritative structured-claim validation service; do not build a parallel validator with inconsistent decisions.
Represent factual claims as structured predicates (entity, source row ID,
field, timestamp, lot, measurement, unit, denominator, source version).
Verify text rendering against these predicates and recompute numbers on
server. A VALID citation with WRONG textual lot/value must BLOCK.
Build approved document registry of synthetic SOP/FMEA/previous 8D with
scope/effective date/revision/ACL. Start with metadata filter and BM25;
add vector hybrid only if retrieval evaluation demonstrates value.
Template RAG retrieves applicable template candidates; final format
conformance uses approved, versioned TemplateContract deterministic rules.
Optional NLI/LLM contradiction detection raises warnings/review tasks,
not authoritative pass. Track false BLOCKs and missing support.
Revalidate dependent document claims on source/policy/template revision;
fall back to full validation when dependency unknown.
Tests: wrong lot despite real evidence ID, stale SOP, foreign plant,
wrong percentage, source supersession, prompt injection, good claims kept.
Acceptance: SQL truth, evidence suitability, document version and template
rules are independently visible with BLOCK reason codes.

HISTORICAL ACTION REUSE (P0): inspect existing historical case retrieval and
G5/G6 D4-cause/D5-action/D6-effectiveness records before adding schema.
For every new case, retrieve scope-matched prior cases with explicit provenance
and matching/differing factors. Prefer prior actions only when their outcome
was independently verified effective and current applicability checks pass.
Do NOT treat similarity as causal proof, auto-execute a past action, or present
UNKNOWN/FAILED/RECURRENT actions as proven solutions. Show a human prompt:
'A similar prior issue was found; the verified prior response was X.
Current conditions differ at Y. Review this approach first?'
Actions: REVIEW_PRIOR_RESPONSE / INVESTIGATE_MORE / CONSIDER_ALTERNATIVE.
Record selection, actor, reason, prior action evidence and case snapshot in
append-only audit. Continue normal D4 verification, D5 authorization and D6
execution/effectiveness; selection is not approval.
Meta can compare cases, request additional READ-ONLY tools, propose next
investigation based on evidence gaps, and recommend alternatives for failed or
recurrent prior actions. FastAPI remains workflow/task/control authority.
Reuse investigator.py/tools.py/model_provider.py and historical store; no
new redundant agents, duplicate tools, hidden chain-of-thought persistence,
or fabricated similarity numbers. Allow deterministic/manual fallback offline.
EXPERIENCE REUSE (v5.4, G8 P0):
Implement a minimal Experience Memory projection over existing case/history,
approved D4 cause, D5 action, D6 effectiveness, D7 applicability, recurrence
and source revision. Keep original natural-language descriptions AND structured
process/measurement/cause/outcome attributes. Semantic natural-language
retrieval may use existing BM25/text infrastructure first, optionally an
embedding index if available and demonstrably useful; no separate vector DB
or model fine-tuning is required. Index refreshes after approved case update,
and revocation/superseded evidence invalidates recommendations. Enforce ACL,
process scope and effective revisions BEFORE ranking or any Meta egress.

Expose explicit recommendation modes:
KNOWN: verified prior remedy, only when current conditions pass applicability.
ANALOGICAL: similar symptoms/process conditions, surface differences and
positive AND negative outcomes; offer prior actions for human review,
with required applicability checks and revalidation.
NO_RELEVANT_HISTORY: no suitable precedent; show no historical remedy,
continue ordinary D0-D8 evidence-based investigation without cross-case
novel remedy synthesis. Novel-problem solution generation is POST-HACKATHON.
Never invent percentage similarity, declare causal certainty from retrieval,
or label proposed novel remedies as proven. LLM-extracted labels are PROPOSED
until independently confirmed. Each recommendation stores case/evidence IDs,
source revisions, supporting/contradicting outcomes, unknowns, selected mode,
recommended checks and human feedback. Continue to restrict model tools to
read-only retrieval, never approving or auto-executing actions.

Tests: successful verified prior action offered with condition checks;
failed/recurrent action not labeled successful; differing equipment blocks
blind reuse; unknown effect -> UNKNOWN; missing ACL -> not retrieved; stale
prior source/revoked effect -> revalidation; recommendation decision audit;
new natural-language wording finds a relevant authorized case; no direct
match -> NO_RELEVANT_HISTORY and no historical action recommendation; fabricated confidence
is absent; Meta offline retains useful deterministic/manual case selection.
Acceptance: one representative E2E case demonstrates retrieval -> grounded
recommendation -> human decision -> unchanged validation/approval gates;
one small no-match fixture verifies honest fallback without invented remedy.
```

## G9. Docs 직접 수정, AI 제안, 과거 해결책 검토, 승인 무결성

```text
G9 — Integrate structured text/claim/table editing into current React /app. Reuse existing DocumentVersion/Claim, ActionEvent and immutable ApprovalEvent; no duplicate document store.
Use existing DocumentVersion/Claim and audited mutations; approved snapshot
is immutable and edits create a new draft. Use optimistic concurrency ETag/
If-Match; simultaneous updates must 409 rather than silently overwrite.
Every edit invalidates validation; inline checks may be debounced but all
review/approval/export requires full server checks under transaction.
Bind signature to content hash + evidence snapshot + WorkflowPolicy +
TemplateContract + validation rule version. AI rewriting is a proposal
with diff, never applied until human accepts; meta offline still allows
manual editor and rule-based validation.
Never modify source measurements or action states through doc editing.
Tests: change 3.2% to 2.1%, false cause, false D3 execution, invalid
customer template, stale approve, two concurrent edits, rejected AI proposal.
Acceptance: human and AI mistakes cannot silently become approved facts.
Show KNOWN/ANALOGICAL/NO_RELEVANT_HISTORY state, matched historical incident (if present),
grounded prior action recommendation (or no recommendation when none matches),
applicability differences, failed precedents and human decision within UI;
selection never auto-approves D5 or marks D6 as executed.
```


## POST-G9 — 통합 감사 + 치명적 오류만 수정 (G10 아님)

```text
STOP feature expansion after G9. On the actual final HEAD inspect end-to-end
D0-D8 state transitions, old/new policy agreement, cause and action evidence,
D6 effectiveness, document/source/template freshness, editor concurrency,
approval snapshot identity, author/reviewer separation, egress and audit.
Run full pytest + negative tests, Ruff, fresh and upgrade-in-place Alembic,
frontend build, HTTP E2E for one success and one failure/reopen case.

Create docs/POST_G9_REFACTOR_PLAN.md with:
- P0: correctness/security/data-loss/approval bypass: fix immediately,
  re-test and commit as separate patches;
- P1: demonstrable perf/maintainability failures: rank by severity and cost;
- P2: UI polish, refactors, new frameworks: defer until after G10 decision.

Do not silently rewrite schema, drop tables, reset history or remove failing
tests. Update docs/V5_IMPLEMENTATION_STATUS.md, README.md, SECURITY.md and
HACKATHON_WORK_LOG.md with what is BUILT vs PARTIAL vs NOT DONE.
Finish by showing a concise G10 readiness report. If P0 gates pass, CONTINUE to G10 according to the following phase; if not, stop and report blockers.
```

## G10 — G9 감사 후 DOCX/PDF · 단일 사건 전체 E2E · 출품용 검증

```text
G10 — Read the v5.5 FINAL specification section 17. Continue ONLY after
post-G9 critical approval, security, and integrity regressions are green.
Reuse the approved immutable 8D snapshot and TemplateContract, NOT a
separate report data store. Generate real DOCX + PDF files with D0-D8,
5W2H, IS/IS NOT, hypotheses/experiments/causal decisions, D5/D6
verified actions, D7 updates, D8 signatures, linked evidence IDs,
policy/template versions, and a visible SYNTHETIC/SIMULATED label.

Bind exports to approval snapshot hash, document version, template version,
source revision, and export time. Compare mandatory numeric/LOT/units,
sections and statuses against the approved snapshot. Ensure draft,
revoked/superseded or stale approvals cannot be falsely exported as
CURRENT_APPROVED. Preserve any historical approved export as immutable.

Render PDF pages and inspect for clipping, overflow, broken Korean text,
empty tables, missing footnotes, broken citations, and multi-page layout.
Add regression tests for modified numeric claim, unsupported citation,
missing required section, stale template, source revision, and export race.

Run ONE fully linked SYNTHETIC PCB case through D0-D8:
D0 triage/urgent action; D1 team; D2 NCR; D3 simulated containment;
G8 prior known/analogical case with successful vs failed/recurrent
outcomes; Meta investigation via offline double when LIVE unavailable;
human reviews proposed prior remedy; D4 hypotheses/tests; D5/D6
simulated action and measurable verification; D7 updates; D8 closure;
Experience Memory becomes searchable; Docs human edit -> factcheck
block -> correction -> reapprove; export DOCX and PDF and verify.
Include ONE small NO_RELEVANT_HISTORY negative case; do not build
multiple competing QMS baselines, large benchmarks or novel solutions.

Run pytest, Ruff, fresh/upgrade Alembic, npm build, actual HTTP E2E,
export content validation, and PDF rendered inspection. Report exact
commands and results, commit and push only as authorized. If any key
end-to-end gate fails, mark PARTIAL or BLOCKED and give reproduction steps.
```

## META LIVE — 실제 연결 및 Tool Calling 검증 (G10 뒤; 자격 증명 가능하면 조기 스모크 허용)

```text
First inspect existing app/model_provider.py, app/investigator.py,
app/tools.py, existing /provider.live_status and docs/META_LIVE_LOG.md.
Do not change model interfaces based on guesses. If legitimate Meta API
credentials are present through a secure environment variable, run a
minimal genuine model request, one read-only tool selection and execution,
JSON/tool-schema validation, source reference verification, and graceful
failure tests for timeout, auth, rate limit, malformed response, egress.
Record real model ID, API route, request date, observed outcomes, latency,
usage/cost if returned. Never print, log, or commit the API key.
If credentials are absent or unavailable, DO NOT fake a live check:
record BLOCKED_NO_CREDENTIALS and keep an honest offline demo path.
Do not let Meta approve D4/D6/D8, write source DB directly, or execute
physical containment. Re-test provider contract after integration fixes.
```

## DEBUG / STABILIZE — 기능 동결 이후 실사용 흐름 안정화

```text
Freeze feature scope. Re-run end-to-end event -> case -> D0-D8 -> prior
resolution recommendation -> human decision -> evidence check -> Docs edit
-> revalidation -> audit/approval -> DOCX/PDF. Triage defects P0 (policy
bypass, ungrounded confirmed cause, data corruption, leaked secrets,
audit tampering); P1 (workflow blocked, tool-call schema failure,
invalid output, PDF errors); P2 (minor UX/performance). Prioritize P0/P1.

Run regression suites and adversarial tests: old workflow.py vs policy.py,
D0 pre-D1 urgent action, old approved snapshots, expired SOP, bad LOT,
wrong units, unverified previous remedy, recurrent precedent, NO_MATCH,
stale source, concurrent edits, self-approval, D6 false effective, D8
premature closure, provider timeout. Fix without weakening tests.
Update README, SECURITY, status, exact worklog, honest demo limitations.
Write docs/FINAL_DEMO_RUNBOOK.md with one deterministic synthetic scenario,
setup commands, expected outcomes, and fallback when Meta LIVE unavailable.
Make no new feature requests; list future work separately.
```

## 단계별 완료 보고 템플릿 (매번 에이전트에게 강제)

```text
Gate: Gx
HEAD before / after:
Current status: BUILT / PARTIAL / BLOCKED
Changed files + migration revision:
Endpoints / UI affected:
Backward compatibility check:
New positive tests:
New negative tests:
Commands actually executed + exit codes:
Meta mode: LIVE / TEST_DOUBLE / NOT_RUN (reason):
Security checks: egress / role / audit / concurrency:
Demo scenario reproduced:
Known limitations + next gate dependency:
Commit SHA (only if actually created):
Push status (only if actually pushed):
```


## 에이전트에게 보낼 짧은 시작 메시지 (전체 범위)

```text
Read the attached QualityOps_AI_FINAL_REQUIREMENTS_v5_5_FINAL.md and
QualityOps_AI_CODEX_EXECUTION_PROMPTS_v5_5_FINAL.md. Work in my existing
homilpat/meta_Hackathon repo on current HEAD, preserve all G0-G4 and S0-S7
implementations, and treat G1 LIVE as BLOCKED_NO_CREDENTIALS until verified.
First fix only the old workflow.py vs new policy.py approval-gate
inconsistency with tests; then implement G5, G6, G7, G8 and G9 in order.
At G8 prioritize validated prior responses to matched incidents with
human decision and documented current applicability; recurrence/failure
triggers additional investigation rather than blind reuse.
At each gate add negative tests, run checks, update truthful work logs,
commit and push on the correct authorized branch. After G9 run full
integration audit, fix P0 issues, write docs/POST_G9_REFACTOR_PLAN.md, and
after G9 P0 audit proceed to G10, then attempt Meta LIVE only with real
credentials and stabilize all critical paths. Do not refactor working code
without a demonstrated need.
```

## FEATURE FREEZE — 추가 요구사항 금지, 종료 조건

```text
Treat v5.5 FINAL as feature-frozen for this hackathon. Do not add complex
multi-agent frameworks, model fine-tuning, separate vector databases,
knowledge-graph engines, actual machine control, MES/ERP integration,
full competing QMS baselines, or a large evaluation benchmark.

Preserve prior G0-G4 functionality, audit and approvals. Experience Memory
means versioned case/outcome indexing + retrieval + Meta grounded analogy,
NOT automatic model weight training. During G8 ship KNOWN/ANALOGICAL
with independent checks and NO_RELEVANT_HISTORY fallback; use existing
retrieval and simple approved case fixtures. Prioritize one strong demo
showing case arrival -> precedent/negative precedent -> Meta next evidence
-> human decision -> verified action outcome -> 8D/Docs/report.

If you encounter integration regressions, authorization vulnerabilities or
false causality claims, fix them ahead of polish. After G9 + post-G9 P0 audit proceed to G10, then Meta LIVE verification
if credentials exist, then stabilization. Do not submit without owner approval.
Provider LIVE must be labeled BLOCKED_NO_CREDENTIALS until truly verified.
```

## POST-HACKATHON ROADMAP — 이번 지시에서 제외

Cross-case analogical transfer for **novel/unknown incidents**, including
newly synthesized remediation hypotheses and experiments, is explicitly
out of scope for G8/G9/G10. Do not implement, test for success, or showcase
it as an existing feature. Existing D0-D8 generic investigation still
works with no historical match. Accumulate validated outcomes now; consider
novel-problem reasoning after the hackathon with separate safety tests.
