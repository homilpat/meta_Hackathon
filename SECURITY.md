# Security model and known gaps

QualityOps AI is a hackathon prototype on SYNTHETIC data. This page states what is enforced in code (with the
test that proves it) and what an enterprise deployment would still need. Nothing here is a certification.

## Assets and threats considered

| Asset | Threat |
|---|---|
| Factory quality data (process values, inspection results, operator records) | Leak to an external model provider; leak through logs |
| Approval records (who approved which content) | Forgery, silent edits, deletion, double approval under concurrency |
| Model output in documents | Unsupported or overconfident claims; prompt injection through source records |
| Model API key and spend | Key leak; cost abuse |

## Controls implemented

| Control | How | Proof |
|---|---|---|
| Egress allowlist by data classification | Tools return rows only if every source is `SYNTHETIC` + `APPROVED_FOR_EXTERNAL`, else fail closed; the provider re-checks the exact outbound bytes for other origins/sensitivity, `CONFIDENTIAL` and secret-like strings before any network call | `test_gateway_blocks_unapproved_data_in_any_message`, `test_confidential_row_stays_out_of_prompts_logs_and_run_records`, `test_summary_fails_closed_on_restricted_rows`; `docs/evaluations/EVAL_RESULTS.md` |
| REAL data never reaches the model | Cases are `SYNTHETIC` only for investigation; the UCI reference model is aggregates only and has no case | `test_steel_reference_is_aggregates_only_and_beats_baselines` |
| Least-privilege model | Read-only, case-scoped tools; unknown tools rejected; bounded rounds/tool calls/tokens/time; no write, approve or URL access | `test_prompt_injection_in_a_source_record_cannot_act_or_pass_validation` |
| Output validation | Server recomputes every CALCULATED number, rejects unknown evidence ids, confirmed-cause / SHAP-as-cause wording and URLs; only VALIDATED runs can become drafts | S3 tests, `docs/evaluations/EVAL_RESULTS.md` (150/150 seeded bad claims rejected) |
| Prompt-injection posture | System prompt marks tool results as untrusted data; even if the model obeys an injected note, it cannot act and the claim fails validation | `test_prompt_injection_in_a_source_record_cannot_act_or_pass_validation` |
| Log minimisation | Tool results stored as SHA-256 only; secrets never returned by `/provider` | S3/S6 tests |
| Separation of duties | Role per document type, author cannot approve own document, case assignment required (403) | `test_authorization_regression_on_every_case_route`, S2/S6 tests |
| Approval integrity | Approval bound to the content hash the reviewer saw; stale/changed versions 409; ordered 8D approvals | S2/S6 tests |
| Concurrency | Every SQLite transaction takes the write lock at BEGIN, so checks and writes are atomic | `backend/scripts/concurrency_sim.py` (found 3 races, now 0), `test_concurrent_decisions_on_one_review_accept_exactly_one` |
| Append-only audit | DB triggers block UPDATE/DELETE on approvals, workflow events, comments and the chain | `test_audit_tables_are_append_only` |
| Tamper evidence | Each audit row is hash-chained in its own transaction; `GET /audit/verify` reports MODIFIED / DELETED / UNCHAINED rows and broken links, also when triggers were dropped | `test_hash_chain_detects_edits_that_bypass_the_triggers`, migration backfill test |
| Export integrity (G10) | DOCX/PDF only for an APPROVED version bound to its content hash (not replaced, not BLOCK) or a CLOSED snapshot with re-checked document hashes and an intact audit chain; the file is read back and every required snapshot field must be in it; each export is logged with the file SHA-256 | `backend/tests/test_g10_export.py` |
| Cost/abuse cap | 10 investigations per user per hour (429) | `test_investigation_quota_per_user` |
| Key handling | Key only in git-ignored `.env`; secret scan before commits | work log |

## Not implemented (required before real use)

1. **Authentication.** `X-User` is a demo header: anyone can claim any user. Needs SSO (OIDC/SAML) with MFA, sessions, and
   re-authentication at signature time (electronic-signature meaning, e.g. 21 CFR Part 11 style), plus CSRF protection once
   cookies are used.
2. **External model use for real data.** Today real data cannot use the LLM at all. Options: a contract with the provider
   (DPA, no retention/training, region), or **self-hosting an open-weight Llama model inside the plant network/VPC** behind
   the same `ModelProvider` interface, keeping the external API for approved data only.
3. **Tamper-proof storage.** The hash chain detects edits but the head hash lives in the same database. Anchor it
   externally (WORM/object-lock storage or periodic signed export) so a full rewrite of the chain is also detectable.
4. **Encryption and transport.** SQLite file is unencrypted and the server speaks HTTP. Needs TLS, encryption at rest, KMS.
5. **Egress inspection depth.** The gateway is pattern based; encodings could evade it. Production should build model
   payloads from an explicit field allowlist and add DLP.
6. **Secrets.** `.env` in plain text; use a secret manager and rotation.
7. **Rate limits** beyond the investigation quota (API-wide), audit-log retention and personal-data rules (operator and
   reviewer ids are personal data under GDPR/PIPA).
8. **Multi-tenant / site isolation** beyond case assignment.

Relevant frameworks for the target industry: TISAX (automotive supply chain), ISO/IEC 27001, IEC 62443 when connected
to OT networks, EU AI Act human-oversight and record-keeping duties.

Report a vulnerability: open a private security advisory on the repository.
