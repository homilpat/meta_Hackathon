"""S7 deterministic evaluation on 30 synthetic cases; writes docs/EVAL_RESULTS.md and docs/eval_s7.json.

Measured here (no model calls): revision impact precision/recall against a rule oracle, template claim
support, ClaimValidator recall on seeded bad claims, and egress-gate behaviour. The A/B/C/D comparison
(LLM settings, History OFF/ON) needs LIVE Meta runs and is reported as NOT RUN, not estimated.
Run: python -m scripts.eval_s7
"""

import json
import tempfile
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ncr
from app.db import Base, Evidence, SourceEvent
from app.main import create_app
from app.model_provider import EgressBlocked, MetaProvider
from app.synthetic import generate, spi_correction
from app.tools import SPECS, EvidenceTools, ToolError

SEEDS = range(101, 131)  # 30 held-out seeds; tests and demo use seed 7
APPROVERS = {"ncr": "bob", "containment": "erin", "rca": "frank"}
ROWS = [f"SPI-{p}-{b}-{pin}" for p in ("P01", "P02") for b in ("B01", "B02") for pin in (1, 2)]


def oracle(row: str) -> set[str]:
    """Which documents must reopen, from the domain rules (not from the graph code).

    NCR (D2) cites SPI of every AOI-FAIL board (P01/B01 false alarm, P02/B01 confirmed) and no model output.
    RCA (D4) covers only the confirmed board P02/B01, including its prediction. Containment never cites SPI.
    """
    board = row[4:11]
    out = set()
    if board in ("P01-B01", "P02-B01"):
        out.add("NCR")
    if board == "P02-B01":
        out.add("RCA")
    return out


class NoNetwork:
    def __init__(self):
        self.sent = 0

    def __call__(self, request, timeout):
        self.sent += 1
        raise OSError("eval: network disabled")


def main() -> None:
    db = Path(tempfile.mkdtemp()) / "eval.db"
    app = create_app(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)

    def call(user, method, path, body=None):
        r = c.request(method, path, json=body, headers={"X-User": user, "Idempotency-Key": uuid.uuid4().hex})
        assert r.status_code < 300, (path, r.status_code, r.text)
        return r.json()

    call("alice", "POST", "/models/train", {"seed": 11})
    tp = fp = fn = 0
    failures, cases, latencies = [], [], []
    claim_total = claim_unsupported = 0
    for seed in SEEDS:
        cid, scored = f"EVAL-{seed}", seed % 2 == 0
        call("alice", "POST", "/cases", {"case_id": cid})
        call("alice", "POST", f"/cases/{cid}/sources", generate(seed))
        for u in APPROVERS.values():
            call("alice", "POST", f"/cases/{cid}/assignments", {"user_id": u})
        if scored:
            call("alice", "POST", f"/cases/{cid}/predictions", {})
        for kind, who in APPROVERS.items():
            doc = call("alice", "POST", f"/cases/{cid}/{kind}", {})
            claim_total += len(doc["claims"])
            claim_unsupported += sum(1 for cl in doc["claims"]
                                     if cl["classification"] in ("OBSERVED", "CALCULATED", "PROPOSAL")
                                     and not cl["evidence_ids"])
            d = call("alice", "POST", f"/cases/{cid}/{kind}/1/request-review", {"reviewer_id": who})
            call(who, "POST", f"/cases/{cid}/{kind}/1/decision",
                 {"decision": "APPROVE", "content_sha256": d["content_sha256"]})
        cont_approved = True
        for version, row in enumerate(ROWS, 3):
            t0 = time.perf_counter()
            got = call("alice", "POST", f"/cases/{cid}/source-revisions",
                       {"asset": spi_correction(seed, row, 0.02, version), "reason": "eval"})
            latencies.append(time.perf_counter() - t0)
            reached = {d["doc_type"] for d in got["documents"]}
            want = oracle(row)
            tp, fp, fn = tp + len(reached & want), fp + len(reached - want), fn + len(want - reached)
            flagged = {d["doc_type"] for d in got["basis_changed"]}
            want_flag = {"CONTAINMENT"} if cont_approved and "NCR" in want else set()
            cont_approved &= not want_flag
            if reached != want or flagged != want_flag:
                failures.append({"case": cid, "row": row, "expected": sorted(want), "got": sorted(reached),
                                 "basis_changed_expected": sorted(want_flag), "basis_changed": sorted(flagged)})
        cont = call("alice", "GET", f"/cases/{cid}/containment/1")
        cases.append({"case": cid, "scored": scored, "containment_status_after_all": cont["status"]})

    # ClaimValidator recall on seeded bad claims (one mutation of each kind per case's NCR v1).
    caught = seeded = 0
    with Session(app.state.engine) as s:
        for seed in SEEDS:
            cid = f"EVAL-{seed}"
            known = set(s.scalars(select(Evidence.evidence_id).where(Evidence.case_id == cid)))
            base = call("alice", "GET", f"/cases/{cid}/ncr/1")["claims"]
            obs = next(cl for cl in base if cl["classification"] == "OBSERVED")
            calc = next(cl for cl in base if cl["value"] is not None)
            for bad in ({**obs, "evidence_ids": []}, {**calc, "evidence_ids": []},
                        {**obs, "evidence_ids": ["EV-doesnotexist"]},
                        {**obs, "classification": "PROPOSAL", "text": "Board P02/B01 was quarantined."},
                        {**obs, "classification": "HYPOTHESIS", "text": "The root cause is confirmed as paste."}):
                seeded += 1
                try:
                    ncr.validate_claims([bad], known)
                except ValueError:
                    caught += 1

        # Egress: every tool output of every case through the real gateway (network disabled), then one
        # CONFIDENTIAL row per case must be denied at the tool and blocked at the gateway.
        opener = NoNetwork()
        provider = MetaProvider("eval-not-a-key", opener=opener)
        clean_blocked = clean_payloads = denied = restricted_blocked = 0
        for seed in SEEDS:
            cid = f"EVAL-{seed}"
            tools = EvidenceTools(s, cid)
            for spec in SPECS:
                name = spec["function"]["name"]
                args = {"evidence_ids": []} if name == "get_evidence" else {"prediction_id": 0} \
                    if name == "explain_prediction" else {}
                try:
                    out = json.dumps(tools.call(name, args))
                except ToolError:
                    continue
                clean_payloads += 1
                try:
                    provider.chat([{"role": "tool", "content": out}], [])
                except EgressBlocked:
                    clean_blocked += 1
                except Exception:  # noqa: BLE001, S110 - the disabled network is the expected end of a clean payload
                    pass
            ev = s.scalars(select(SourceEvent).where(SourceEvent.case_id == cid)).first()
            ev.sensitivity = "CONFIDENTIAL"
            s.flush()
            try:
                tools.call("get_manufacturing_events", {})
            except ToolError:
                denied += 1
            try:
                provider.chat([{"role": "tool", "content": json.dumps({"sensitivity": "CONFIDENTIAL"})}], [])
            except EgressBlocked:
                restricted_blocked += 1
            s.rollback()
    c.close()
    app.state.engine.dispose()

    n = len(SEEDS)
    precision, recall = tp / (tp + fp) if tp + fp else 1.0, tp / (tp + fn) if tp + fn else 1.0
    lat = sorted(latencies)
    result = {
        "cases": n, "revisions": len(latencies), "impact": {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
                                                            "recall": recall, "failures": failures},
        "template_claims": {"total": claim_total, "unsupported": claim_unsupported},
        "validator": {"seeded_bad_claims": seeded, "rejected": caught},
        "egress": {"clean_tool_payloads": clean_payloads, "clean_blocked": clean_blocked,
                   "network_attempts_for_clean": opener.sent, "confidential_rows": n, "tool_denied": denied,
                   "gateway_blocked": restricted_blocked},
        "revision_latency_ms": {"p50": round(1000 * lat[len(lat) // 2], 1), "max": round(1000 * lat[-1], 1)},
        "containment_basis_changed": sum(x["containment_status_after_all"] == "BASIS_CHANGED" for x in cases),
    }
    Path("docs/eval_s7.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    Path("docs/EVAL_RESULTS.md").write_text(f"""# S7 evaluation results

Generated by `python -m scripts.eval_s7` on {n} held-out SYNTHETIC cases (fixture seeds {SEEDS.start}–{SEEDS.stop - 1};
tests and the demo use seed 7). No model was called. Raw output: `docs/eval_s7.json`.

**Limits of this set:** the generator varies SPI volumes per seed but keeps the same board/AOI/verification
structure, so these numbers test that the pipeline is consistent across inputs, not that it generalises to new
failure patterns. Half of the cases (even seeds) were scored by the SPI model before documents were written.
Documents are approved in 8D order (NCR D2 -> Containment D3 -> RCA D4); the API refuses any other order.

## Measured (deterministic)

| metric | result |
|---|---|
| Revision impact precision (reopened documents that the rule oracle expects) | {tp}/{tp + fp} = {precision:.3f} |
| Revision impact recall (expected documents that were reopened) | {tp}/{tp + fn} = {recall:.3f} |
| Containment plans flagged BASIS_CHANGED (content kept, not reopened) after the NCR they build on reopened | {result['containment_basis_changed']}/{n} |
| Template claims that are OBSERVED/CALCULATED/PROPOSAL without evidence | {claim_unsupported}/{claim_total} |
| ClaimValidator rejections of seeded bad claims (no evidence, fake id, executed action, confirmed cause) | {caught}/{seeded} |
| Approved-data tool payloads wrongly blocked by the egress gateway | {clean_blocked}/{clean_payloads} |
| CONFIDENTIAL rows denied at the tool layer | {denied}/{n} |
| CONFIDENTIAL payloads blocked at the gateway before any network call | {restricted_blocked}/{n} |
| Revision import + impact latency (local SQLite, {len(latencies)} imports) | p50 {result['revision_latency_ms']['p50']} ms, max {result['revision_latency_ms']['max']} ms |

Oracle: a corrected SPI row must reopen the NCR if its board had an AOI FAIL (the NCR is the D2 problem
description and cites no model output), and the RCA only for the confirmed-defect board P02/B01 (model scores
and SHAP live in the RCA). Containment never cites SPI; the first correction that reopens its NCR must flag it
BASIS_CHANGED for QA to reconfirm, and no other correction may flag it. Corrections are applied cumulatively (v3, v4, ...) within each case, so later rows also report
documents that were already REVALIDATION_REQUIRED; the metric counts the documents reached, not status flips.
Mismatches: {len(failures)} (listed in the JSON).
The oracle encodes the same template rules the code implements and was written by the same developer, so
100% here shows the graph and templates agree with the stated rules; it is not an independent audit.

## Not run

| setting | status |
|---|---|
| A: LLM one-shot report | NOT RUN — needs LIVE Meta key |
| B: ML/XAI + LLM | NOT RUN — needs LIVE Meta key |
| C: tool calling, History OFF | NOT RUN — needs LIVE Meta key |
| D: tool calling + history, History ON | NOT RUN — needs LIVE Meta key |

No citation accuracy, unsupported-claim rate, wrong-precedent avoidance or cost/latency figures exist for the
model settings. The deterministic History OFF/ON planner log is in `docs/HISTORY_COMPARISON.md`; it is not an
LLM comparison.
""", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "impact"} | {
        "impact": {k: result["impact"][k] for k in ("tp", "fp", "fn", "precision", "recall")}}))


if __name__ == "__main__":
    main()
