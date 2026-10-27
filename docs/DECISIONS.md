# S0 decisions — 2026-10-27 KST

1. **New repository:** create `qualityops-ai` beside the planning files. No historical source is reused and no remote repository is changed.
2. **Stage boundary:** implement S0 only. Empty Alembic baseline is deliberate; manufacturing tables and fixtures belong to S1.
3. **Meta model:** official docs list `muse-spark-1.3`, but actual account entitlement requires a successful LIVE call. The smoke script fails visibly when no key exists. `MOCK` is not used.
4. **Data:** PHME license/access/egress are unresolved. Choose a transparent synthetic fallback for S1 without creating it now.
5. **Event rules:** the [public event page](https://dev.meta.ai/events/global-hackathon) lists an Oct 26 start and Nov 4, 9 PM ET deadline. The planning files note an EST/EDT start-time ambiguity; this code was written after both interpretations. Public page text does not prove account acceptance or all private official rules. Confirm those before submission.
6. **Privacy:** `/health` takes no case data. The optional Meta smoke uses fixed synthetic text. Actual REAL/CONFIDENTIAL egress protection is future work and must not be claimed in S0.
7. **2018 source request:** PHM Society 2018 is an ion-mill equipment fault dataset, not PCB inspection evidence. Its raw access and reuse/egress permission remain unverified. It cannot replace the PCB multi-source fixture by relabeling fields; see `DATASET_ACCESS.md`.
8. **Repository:** `homilpat/meta_Hackathon` is the user-specified destination. Its existing `main` contained only an initial README commit dated 2026-10-27. Preserve that history when publishing S0.

