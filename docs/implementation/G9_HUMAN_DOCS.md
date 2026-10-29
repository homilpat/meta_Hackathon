# G9 — Human Docs workspace

MASTER §4. Code: `backend/src/app/docedit.py`, approval guard in `workflow.decide`, UI
`frontend/src/features/documents/DocEditor.tsx`. Tests: `backend/tests/test_g9_docs.py` (5),
`frontend/tests/DocEditor.test.tsx` (2), G9 steps in `backend/scripts/integration_smoke.py`.

## Contract

| API | Behaviour |
|---|---|
| `POST /cases/{c}/{ncr\|containment\|rca}/{v}/edits` (AUTHOR, `Idempotency-Key`) | body `expected_sha256`, `reason` (5–500 chars), `changes` (claim text / value / unit / classification / evidence_ids), `add`, `remove`, `ai_proposal`. `v` must be the latest version and its hash must match, else **409**. The edited claim set goes through the same `factcheck.check_claims` as creation (422 on BLOCK). Creates version `v+1` (`builder = HUMAN_EDIT:<TYPE> v<v>`), supersedes a pending DRAFT / IN_REVIEW / INFO_REQUESTED base (its pending review can no longer be decided), leaves an APPROVED base untouched, logs `DRAFT_EDITED` (actor, reason, changed claims), runs a `ValidationRun` and returns doc + `diff` + `validation` |
| `GET …/{v}/diff?against=n` | per-claim ADDED / REMOVED / CHANGED with before/after fields (default against `v-1`) |
| `POST …/{v}/edit-proposals` (AUTHOR) | no key → **503 "AI OFFLINE"**; with a provider, returns proposed changes for existing claims only, `applied: false`; logs `AI_EDIT_PROPOSED`; nothing stored. Acceptance = the person submits it to `/edits` (`ai_proposal: true`), which re-validates |
| approval of a `HUMAN_EDIT` version | `decision APPROVE` additionally needs the latest `ValidationRun` of that version to exist, be non-stale (document / evidence / policy / template / rules hashes) and not BLOCK, else **409**. WARN is approvable (existing policy) |

No new tables and no migration: versions, claims, validation runs, approvals and the workflow log are the existing
ones, so there is no second approval source. Template-built and model-built versions keep their previous approval
rules unchanged (their tests are untouched).

## Scope limits (honest)

- Editable documents are the stored D2/D3/D4 documents (NCR / CONTAINMENT / RCA). D5–D8 records (actions,
  effectiveness, revisions, closure) are already their own append-only approval sources; they are shown on the
  D0~D8 screen and are not re-rendered as an editable document, to avoid a duplicate approval path.
- The AI proposal path is tested with the `TEST_DOUBLE` provider only; Meta LIVE is not verified (no key).
