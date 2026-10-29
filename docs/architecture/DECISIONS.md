# S0 decisions — 2026-10-27 KST

1. **New repository:** create `qualityops-ai` beside the planning files. No historical source is reused and no remote repository is changed.
2. **Stage boundary:** implement S0 only. Empty Alembic baseline is deliberate; manufacturing tables and fixtures belong to S1.
3. **Meta model:** official docs list `muse-spark-1.3`, but actual account entitlement requires a successful LIVE call. The smoke script fails visibly when no key exists. `MOCK` is not used.
4. **Data:** PHME license/access/egress are unresolved. Choose a transparent synthetic fallback for S1 without creating it now.
5. **Event rules:** the [public event page](https://dev.meta.ai/events/global-hackathon) lists an Oct 26 start and Nov 4, 9 PM ET deadline. The planning files note an EST/EDT start-time ambiguity; this code was written after both interpretations. Public page text does not prove account acceptance or all private official rules. Confirm those before submission.
6. **Privacy:** `/health` takes no case data. The optional Meta smoke uses fixed synthetic text. Actual REAL/CONFIDENTIAL egress protection is future work and must not be claimed in S0.
7. **2018 source request:** PHM Society 2018 is an ion-mill equipment fault dataset, not PCB inspection evidence. Its raw access and reuse/egress permission remain unverified. It cannot replace the PCB multi-source fixture by relabeling fields; see `DATASET_ACCESS.md`.
8. **Repository:** `homilpat/meta_Hackathon` is the user-specified destination. Its existing `main` contained only an initial README commit dated 2026-10-27. Preserve that history when publishing S0.

## S1 decisions — 2026-10-27 KST

1. Build a new seeded PCB fixture with repeated board/component/pin IDs under different parents; always join on the full key and never infer a lot ID.
2. Preserve corrected SPI as source v2 beside v1, with source hashes and event/evidence IDs. A missing AOI record is a coverage issue, not PASS. AOI/human disagreement is retained without inferring a physical cause.
3. Accept only exact generator output through the S1 API. This prevents arbitrary uploaded records from gaining the `SYNTHETIC` label by assertion alone. Real-source adapters need a separate provenance policy.
4. Synthetic historical examples have `UNVERIFIED` reported outcomes. Eligibility and outcome validation belong to S5.
5. The official UCI Steel Plates Faults page states CC BY 4.0, 27 features, and seven fault classes. S1 records the row adapter interface only; it does not treat this defect-only dataset as a good-vs-bad or defect-rate benchmark.

