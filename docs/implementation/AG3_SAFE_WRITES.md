# AG3 — Allowlisted writes, human gates, pause/resume (spec §22.3, §22.4, §22.10)

The agent can now prepare the next 8D document. It never sends, approves, edits an existing version, confirms a cause,
executes an action or closes a case. Every write is an existing route handler called as the signed-in user.

## What the agent may write

| Tool | Existing route(s) | Guard |
|---|---|---|
| `prepare_document` | `POST /cases/{id}/{kind}` (draft), `POST /cases/{id}/{kind}/{v}/validate` | AUTHOR role and the claim validator are enforced by the route. The target is the first D2→D4 document that is not APPROVED. An existing DRAFT is **reused** (no second version). An IN_REVIEW or BASIS_CHANGED document makes the run wait for its owner (`await`). |
| `request_review` | `POST /cases/{id}/{kind}/{v}/request-review` | Only after the user answers the pending decision (details below). |

How `request_review` is guarded:
- The run stops with `NEEDS_HUMAN` and offers reviewer candidates picked by the server: assigned users who hold the approver role and are not the author.
- On resume, the server checks that the chosen reviewer is one of those candidates.
- It re-reads the document and refuses to send if anything moved (stale): the document is no longer DRAFT, the hash changed, or a newer version exists.
- It calls the route with a per-step Idempotency-Key.
- Then it **re-reads the document** and reports a hand-off only if the document is IN_REVIEW with that reviewer's PENDING review.

Never on the allowlist (also listed by `GET /agent/tools`): decision (approve/reject), basis-check, G9 edits, causal decisions,
action events, closure. A model naming one gets a `DENIED` step.

## Pause / resume

- **Pending decision:** `pending = {action: confirm_scope | request_review | await, token, …}` is stored on the run.
- **Resume:** `POST /agent/runs/{id}/resume {token, confirm, reviewer_id}` claims it in one transaction. A repeated or stale token gets 409, so a double click cannot create a second review.
- **`await`** re-reads the server state. It continues only when the human decision is visible there (for example, the NCR is APPROVED, so the CONTAINMENT draft comes next). Otherwise it waits again with a new token.
- **Restart:** the run and its pending decision live in the database, so a new server process can resume them.

## Tests — `backend/tests/test_agent_ag3.py` (10)

| Test | Spec |
|---|---|
| draft saved and validated, not an approval | §22.10 (1). DRAFT, audit ids, candidates `bob, carol`, no Review / ApprovalEvent. Author's queue shows SEND_FOR_REVIEW; reviewer's queue is empty. |
| confirmed review verified and handed to the reviewer's queue | §22.10 (2)(3)(4)(6), AG-T09, AG-T02. Document IN_REVIEW with bob PENDING; bob's `/queue?scope=mine` has REVIEW; the repeated answer gets 409; one Review; no approval. |
| same goal twice reuses the draft | AG-T09: one document version |
| document changed after the question is not sent | AG-T05: BLOCKED stale, no Review |
| reviewer must be a server candidate | author / wrong role / none → BLOCKED, no Review |
| server role check refuses a reviewer's draft | 403 from the route recorded as DENIED → BLOCKED |
| waits for the human decision, continues only after the server shows it | `await` stays while IN_REVIEW. After bob approves in the existing route, resume moves on to the CONTAINMENT draft with candidate `erin`. |
| pending decision survives a server restart | §22.4, §22.10 (5) |
| model planner can prepare but never send or approve | `request_review` is not offered to the model; requested anyway → DENIED |
| agent draft equals the manual draft | AG-T10: same content hash, claims and validation as the documents screen |

`tests/test_agent_ag2.py` keeps the read-only cases. Its first test now uses an investigate-only goal.

## Verification (local)

| Check | Result |
|---|---|
| `pytest tests/test_agent_ag3.py tests/test_agent_ag2.py` | 18 passed |
| full backend `pytest` | 279 passed |
| `ruff check .` | All checks passed |
| `scripts.integration_smoke` (real uvicorn) | 27/27 |
| `scripts.e2e_http` (D0→D8 success + D6 failure over HTTP) | 2/2 |

No frontend change was needed: the AG1 run view already renders `create_draft`, `validate_document`, `request_review`
steps and the `request_review` / `await` decisions.
