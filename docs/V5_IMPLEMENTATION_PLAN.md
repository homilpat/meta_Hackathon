# v5 implementation plan (minimal dependency order)

Principles: additive only; old routes/tables/tests untouched; each gate = one migration (if any) + one module + one test file; every event table append-only and hash-chain-free unless it is an approval (approvals reuse `WorkflowEvent` logging, which is chained).

## New code layout

| Module | Gate | Contents |
|---|---|---|
| `app/policy.py` | G2 | `DEFAULT_POLICY` (JSON, hashed), pure `can_draft / can_execute_urgent / can_approve / can_close` → `Verdict(result: PASS|WARN|UNKNOWN|BLOCK, reasons)` |
| `app/quality.py` | G2 | `assess(session, case_id)` → EvidenceQualityAssessment rows from source version / data issues; `suitable(state, use)` |
| `app/process.py` | G2 | `ProcessAdapter` protocol; `PcbAdapter` (panel/board/pin/SPI/AOI → AffectedObject/Measurement views over existing rows); `DemoMachiningAdapter` contract fixture |
| `app/eightd.py` | G3–G7 | Router + logic for triage, team, actions (urgent/D3/D5/D6), hypotheses/experiments/decisions, effectiveness, prevention, closure |
| `app/factcheck.py` | G8 | Structured predicate check of claims vs DB; controlled-document registry + BM25; TemplateContract rules; ValidationRun |
| `app/docedit.py` | G9 | Draft edit (If-Match/ETag), DocumentEdit log, AI proposal diff/accept, signature binding |
| `app/export.py` | G10 | DOCX (stdlib zip+XML) from approved snapshot + export re-check |

## Additive tables (one migration per gate)

| Migration | Tables |
|---|---|
| 0010_v5_foundation (G2) | `workflow_policies`, `evidence_quality` (append-only), `process_contexts`, `affected_objects` |
| 0011_v5_d0_d1 (G3) | `triage_assessments` (append-only), `team_memberships`, `actions`, `action_events` (append-only) |
| 0012_v5_d4 (G5) | `cause_hypotheses`, `why_links`, `experiments`, `causal_decisions` (append-only) |
| 0013_v5_d5_d6 (G6) | `effectiveness_plans`, `effectiveness_results` (append-only); D5 options/selection reuse `actions` (`stage='D5'`, `cause_ids`) |
| 0014_v5_d7_d8 (G7) | `prevention_deployments`, `closures` (append-only) |
| 0015_v5_docs (G8/G9) | `controlled_documents`, `template_contracts`, `validation_runs`, `document_edits` (append-only), `signature_bindings` |

Dedup decisions: D3 containment actions, urgent actions, D5 selected actions and D6 implementations are one `actions` table with `stage` and an append-only `action_events` log (PROPOSED → PLAN_APPROVED → EXECUTED → INDEPENDENTLY_VERIFIED → RELEASED | NOT_EFFECTIVE). `ActionExecution` from the spec = an `action_events` row with `event_type=EXECUTED`. `CorrectiveAction` = `actions(stage='D5')`. `Measurement` is an adapter view, not a table.

## Gate dependencies

G0 → G1 (independent; blocked without key) → G2 (policy/quality/adapter) → G3 (needs policy, actions) → G4 (needs actions, quality) → G5 (needs quality) → G6 (needs G5 confirmed causes + actions) → G7 (needs all stage gates) → G8 (fact predicates, doc registry, templates; feeds G7 D7 and G9) → G9 (edit + signature binds policy/template/rules) → G10 (export + E2E).

## Fixtures

- **Normal**: synthetic SMT line seed 7 (`generate_line`), SPC alarm on lot L02 (worn stencil STN-2). D0 FULL_8D (shipped panels → customer risk), urgent hold of L02 unshipped panels before D1, D1 team, D2 NCR, D3 executed + independently verified (SYNTHETIC watermark), D4 hypothesis "stencil STN-2 wear" with supporting synthetic experiment → CONFIRMED by process engineer, D5 "replace stencil + cleaning interval", D6 pre-committed plan, post window meets min sample → EFFECTIVE, D7 SOP/FMEA revision effective, D8 closed.
- **Failing**: same case; contradictory experiment → INCONCLUSIVE on a second hypothesis; D6 result below acceptance → NOT_EFFECTIVE → D4/D5 reopened, failure kept in log; plus blocked attempts for every §9 counter-example.

## Verification per gate

`python -m pytest -q`, `python -m ruff check .`, `alembic upgrade head` on a fresh SQLite file, `npm run build` when `web/` changes. Commit only on all-green. No push (not authorised).
