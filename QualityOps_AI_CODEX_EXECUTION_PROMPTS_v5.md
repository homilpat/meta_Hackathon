# QualityOps AI — Codex/Claude Code 실행 프롬프트 v5

**사용법:** 프로젝트 루트에 `QualityOps_AI_FINAL_REQUIREMENTS_v5.md`를 먼저 놓고, 아래 **MASTER**를 에이전트에 첫 메시지로 전달한다. 에이전트가 현재 HEAD를 확인하고 `G0` 감사표를 만들면, 아래 G1~G10을 **순서대로 한 단계씩** 전달한다. 서로 의존하는 마이그레이션·테스트는 단계 안에서 함께 구현한다. 에이전트가 이미 구현된 내용으로 판단하면 근거 파일/테스트를 보여주고 그 기능은 건너뛴다.

## MASTER: 첫 메시지 — 기존 코드를 보존하는 구현 에이전트

```text
You are the senior software engineer and quality-domain systems architect
for the EXISTING GitHub repository homilpat/meta_Hackathon.

PRIMARY INPUT: QualityOps_AI_FINAL_REQUIREMENTS_v5.md.
Also read existing specs v3/v4 if available, README.md, SECURITY.md,
HACKATHON_WORK_LOG.md, THIRD_PARTY_NOTICES.md, docs/EVAL_RESULTS.md,
pyproject.toml, migrations, app/db.py, app/workflow.py, app/report.py,
app/ncr.py, app/impact.py, app/history.py, app/investigator.py,
app/model_provider.py, app/tools.py, app/main.py, web/src/App.tsx and tests.
Check the ACTUAL current Git HEAD, branch, uncommitted changes, test state,
route registry and migration history before planning ANY code modification.
The spec's last observed commit aafbba37 is context, not a pinned target.

Goal: evolve existing QualityOps AI into an evidence-governed, manufacturing-
agnostic D0-to-D8 incident/8D platform WITHOUT replacing working S0–S7.
Maintain truthful states:
  SIGNAL != DEFECT
  PROPOSED != APPROVED != EXECUTED != VERIFIED
  HYPOTHESIS != TESTED != CONFIRMED
  SELECTED_ACTION != IMPLEMENTED_ACTION != EFFECTIVE_ACTION
  CITED_EVIDENCE != SUPPORTED_CLAIM
  SOURCE_DB_MATCH != PHYSICAL_GROUND_TRUTH.

Mandatory architectural corrections:
1. Versioned WorkflowPolicy: draft, emergency execution, approve and closure
   decisions are distinct; no rigid D2->D3->D4 chain that delays containment.
2. EvidenceQualityAssessment: provenance, freshness, conflicts and suitability
   for root-cause/effectiveness evidence.
3. Structured Hypothesis -> Experiment -> CausalDecision with counterevidence.
4. Task-aware AI routing: use deterministic SQL/statistics/validation for math,
   LLM only for language/hypothesis proposals, always read-only tools.
5. Process-neutral Case/Measurement/AffectedObject contracts; keep PCB adapter.

Hard constraints:
- Keep existing API semantics or add compatible v2 fields/endpoints and migration.
- Preserve content-hash approvals, append-only audit, role separation,
  concurrency/idempotency tests, source version impact and egress fail-closed.
- Do not fabricate physical action evidence, inspected quality results, human
  approvals, customer templates, historical revisions or Meta LIVE success.
- All manufacturing data are SYNTHETIC; label simulation explicitly.
- Never run real outbound model calls with confidential/unknown data.
- Never print or commit API keys. Never rewrite git history or force push.
- Do not transform document prose editing into real source-data changes.
- Existing docs may be stale. Code, migrations and passing tests are ground truth.
- No large new frameworks unless justified by a failing requirement.
- After each gate, add negative tests and run: python -m pytest -q,
  python -m ruff check ., alembic upgrade head; run npm build if UI touched.
  Do not claim commands passed unless executed; record logs and blockers.
- If dependencies unavailable, report exact blocker and continue only on safe
  unrelated tasks; never fake tests or mark LIVE when using a test double.
- At gate completion summarize changed files, before/after behavior, tests
  and failures, security implications, migration/rollback, demo steps,
  remaining limitations, and exact commit SHA if committed.
- Create a small focused commit per gate only if checks pass; push to the
  existing intended remote branch ONLY if explicitly authorized in the user's
  development workflow. Do not overwrite unrelated changes.

Workflow: perform gate G0 first. Do not attempt G1–G10 until G0 deliverables
and the minimal dependency plan are in place. Avoid scope expansion.
```

## G0. 현재 HEAD 코드 감사 + 호환성 설계 (구현 전 필수)

```text
G0 ONLY — Audit and design, no feature implementation.
1. Show git status, branch, HEAD, remote, test results, route map, Alembic heads.
2. Map FR-01..FR-29 to actual source file/function/endpoint/test. Mark
   BUILT, PARTIAL, MISSING and attach evidence. Never copy stale README status.
3. Specifically inspect `workflow.PREREQ`, `KINDS`, `APPROVER`, `STEP`,
   `DocumentVersion`/`DocumentClaim`, `report.validate_report`, `_expected`,
   source correction / impact graph, egress, role checks and frontend Docs UI.
4. Design additive migrations for Policy, EvidenceQuality, D0/D1, D4
   Hypothesis/Experiment, D5/D6 action/effect, D7/D8, TemplateContract,
   ValidationRun and DocumentEdit, minimizing duplicate entities.
5. Produce docs/V5_GAP_MATRIX.md and docs/V5_IMPLEMENTATION_PLAN.md.
6. Rank dependencies and choose one synthetic normal case and one failing
   case as test fixtures. Validate tests still pass. Do not change S0–S7 code.
Acceptance: every requirement is tracked and risks are explicit.
```

## G1. 환경·Meta LIVE 연결 검증 (키 없으면 미구현 블로커로 기록)

```text
G1 — Preserve existing Meta model provider and smoke scripts.
Run `python -m scripts.meta_smoke` and
`python -m scripts.meta_investigate_smoke` only when a key is configured
locally and access is authorized; calls may charge credits.
Never request or echo the secret. If key/entitlement is absent, record
BLOCKED_NO_CREDENTIALS or exact sanitized provider error and keep manual
workflows usable. Differentiate LIVE vs TEST_DOUBLE in logs and UI.
Validate tool round limits, Pydantic report and ClaimValidator after LIVE.
Record model ID, date, outcome and measured latency/tokens when available.
No mock fallback represented as LIVE. Add failures/retry tests without
changing existing egress protections.
Acceptance: actual success OR a precise, truthful blocker, tests green.
```

## G2. 기반 구조 개선: WorkflowPolicy + EvidenceQuality + 중립 Core

```text
G2 — Design additive DB migrations for versioned WorkflowPolicy,
EvidenceQualityAssessment and minimal process-neutral ProcessContext,
AffectedObject and Measurement adapter interfaces.
Implement pure policy functions can_draft, can_execute_urgent, can_approve,
can_close, returning PASS/WARN/UNKNOWN/BLOCK and human explanation.
Replace direct reliance on hard-coded chain ONLY at new decision entrypoints,
keeping old endpoints backwards compatible. For existing D2/D3/D4,
provide default policy equivalent to current permission semantics except
allow authorized urgent containment before formal documentation.
Populate EvidenceQuality from existing provenance/revision/data-quality flags;
mark unclear status UNVERIFIED, never silently VALID. Build compatibility
adapter for PCB panel/board/pin/SPI/AOI without moving raw source data.
Tests: source conflict/superseded; emergency before D1; denied approval;
old API/approval/audit/impact regression; second trivial process fixture.
Acceptance: policy/quality decisions are auditable and old API intact.
```

## G3. D0 위험 평가 / 긴급 격리 / D1 다부서 팀

```text
G3 — On top of G2 policy, implement case intake and D0 triage:
SPC_SIGNAL -> TRIAGE -> NCR_ONLY | FULL_8D | EMERGENCY_FULL_8D.
Allow emergency hold/request/confirmation events ahead of D1/D2 document
approval for high risk; NEVER change real shipment state in synthetic demo.
Record affected lots/shipments, actors, timestamps, rationale, evidence and
separate executable authority. Track D1 lead and required cross-functional
roles, acceptance, deadlines, missing skills and alternate assignee.
Integrate into existing React /app without rebuilding its navigation.
Tests: false positive signal, emergency action early, missing actor,
self-approval, no invented containment execution.
Acceptance: normal triage and safe emergency path are demonstrable.
```

## G4. 기존 D2/D3를 실제 업무 의미로 개선

```text
G4 — Extend existing NCR(D2) rather than writing another NCR generator.
Add structured 5W2H, IS/IS-NOT, detection/lot/time/source denominator,
known-vs-unknown scope, effective source revision, confidence/status.
Add D3 containment actions with distinct PROPOSED, PLAN_APPROVED, EXECUTED,
INDEPENDENTLY_VERIFIED and RELEASED/NOT_EFFECTIVE outcomes. Use synthetic
execution events with visible watermark; no real inventory/ERP mutation.
Bind target scope to exact lot/board/shipment source rows; preserve
historical evidence and existing stage-review UI behavior.
Tests: valid evidence ID but wrong lot/text; units, stale measurements;
plan-without-execution; verifier is same person when independence required.
Acceptance: draft does not imply physical action; existing D2/D3 tests green.
```

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

## G8. 보고서↔DB 역검증 / 문서 검색 / 양식 RAG

```text
G8 — Harden `app/report.py` ClaimValidator instead of replacing it.
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
```

## G9. Docs 직접 수정, AI 제안, 승인 무결성

```text
G9 — Integrate structured text/claim/table editing into current React /app.
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
```

## G10. 출력 / QA / 해커톤 데모

```text
G10 — From the approved canonical document snapshot, export original
customer-configurable 8D DOCX and PDF. Confirm permissions for any external
template and do not redistribute unlicensed forms. Validate exported fields,
tables, source refs, revision, sign-offs and synthetic watermark match the
approved snapshot; fail export on missing required content.
Run complete E2E normal D0-D8, emergency containment before full D1,
Docs tampered numeric claim BLOCK, unverified cause BLOCK, ineffective D6
reopens, revised SPI evidence invalidates only affected work, forbidden
external payload blocked, Meta LIVE only if genuinely verified.
Run pytest, Ruff, Alembic upgrade/head, UI build, API HTTP checks;
record commands, timings, failures, screenshots/video evidence as available.
Evaluate separate deterministic baseline vs genuine LIVE model results;
collect unsupported-claim false negatives/false positives, latency, costs,
review minutes, retrieval and document errors WITHOUT inventing data.
Update README.md, SECURITY.md, HACKATHON_WORK_LOG.md, docs/EVAL_RESULTS.md,
source/licence notices. Produce docs/V5_IMPLEMENTATION_STATUS.md and
3-minute demo script showing what was built vs still planned.
Acceptance: end-to-end truthful demo with measurable outcomes and safe
remaining known gaps.
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

## 개발 시작용 단일 짧은 명령 프롬프트

**에이전트 채팅에 아래와 MASTER + 최종 명세서를 함께 넣으면 된다.**

```text
The repo is homilpat/meta_Hackathon. Adopt the attached v5 final requirements
as the authoritative target. Start G0 on current HEAD; do not rebuild or
rewrite prior history. Inventory existing code/tests/routes/migrations first.
Create the gap matrix and minimal dependency plan, then implement gates
G1-G10 one at a time with regression/negative tests, atomic approvals,
realistic action-vs-document distinction, auditable evidence, and honest
LIVE-vs-mock reporting. At each gate stop and report evidence, commit status,
next step and blockers. Preserve all existing S0-S7 behavior. Do not invent
manufacturing outcomes, working integrations or measured performance.
```
