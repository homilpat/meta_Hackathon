"""C (post-G9 audit): one synthetic SMT case end to end, success and failure (MASTER TC-C-01 / TC-C-02).

The scenarios only talk to the API (plus the evidence-id lookup in v5_util), so `scripts/e2e_http.py` runs the same
functions against a real uvicorn process.
"""

import pytest

from tests.v5_util import CLOSE, H, acknowledge_all, line_client, ok, ready_to_close


def success(c) -> dict:
    # history first: the prior response is reviewed, which creates nothing and approves nothing
    r = ok(c.post("/cases/L/experience/retrievals", json={"q": "solder volume drift stencil"}, headers=H("alice")))
    assert r["mode"] == "KNOWN" and r["recommendations"][0]["evidence_level"] == "VERIFIED_NO_RECURRENCE"
    ok(c.post("/cases/L/experience/decisions", headers=H("alice"), json={
        "retrieval_id": r["retrieval_id"], "entry_key": r["recommendations"][0]["entry_key"],
        "decision": "REVIEW_PRIOR_RESPONSE", "reason": "compared stencil and paste conditions with L02"}))
    assert c.get("/cases/L/actions", headers=H("alice")).json() == []
    ready_to_close(c)
    # a person edits the approved D2 document: D2 is open again until the new version is approved
    v1 = ok(c.get("/cases/L/ncr/1", headers=H("alice")), 200)
    bad = c.post("/cases/L/ncr/1/edits", headers=H("alice"), json={
        "expected_sha256": v1["content_sha256"], "reason": "try a wrong count",
        "changes": [{"claim_id": "C1", "value": v1["claims"][0]["value"] + 1}]})
    assert bad.status_code == 422
    e = ok(c.post("/cases/L/ncr/1/edits", headers=H("alice"), json={
        "expected_sha256": v1["content_sha256"], "reason": "reviewer asked for clearer wording",
        "changes": [{"claim_id": "C1", "text": v1["claims"][0]["text"] + " (all lots)"}]}))
    assert e["validation"]["result"] in ("PASS", "WARN")
    acknowledge_all(c)
    blocked = c.post("/cases/L/closure", json=CLOSE, headers=H("bob"))
    assert blocked.status_code == 409 and "D2" in blocked.json()["detail"]
    ok(c.post("/cases/L/ncr/2/request-review", json={"reviewer_id": "bob"}, headers=H("alice")), 200)
    ok(c.post("/cases/L/ncr/2/decision", headers=H("bob"), json={
        "decision": "APPROVE", "comment": "edit checked", "content_sha256": e["content_sha256"]}), 200)
    # D3/D4 were approved on NCR v1: their approvers must confirm the scope still holds on v2
    for kind, approver in (("containment", "erin"), ("rca", "frank")):
        d = ok(c.get(f"/cases/L/{kind}/1", headers=H("alice")), 200)
        assert d["status"] == "BASIS_CHANGED", (kind, d["status"])
        assert c.post("/cases/L/closure", json=CLOSE, headers=H("bob")).status_code == 409
        ok(c.post(f"/cases/L/{kind}/1/basis-check", headers=H(approver), json={
            "decision": "NO_SCOPE_IMPACT", "comment": "wording change only", "content_sha256": d["content_sha256"]}),
            200)
    closed =ok(c.post("/cases/L/closure", json=CLOSE, headers=H("bob")))
    assert closed["decision"] == "CLOSED"
    # consistency: approvals name the exact content they approved; the validation of v2 is still current
    for v in (1, 2):
        d = ok(c.get(f"/cases/L/ncr/{v}", headers=H("bob")), 200)
        assert d["status"] == "APPROVED" and d["decisions"][-1]["content_sha256"] == d["content_sha256"]
    assert d["content_sha256"] != v1["content_sha256"] and v1["status"] == "APPROVED"
    val = ok(c.get("/cases/L/ncr/2/validation", headers=H("bob")), 200)
    assert val["hashes"]["document_sha256"] and not val["stale"]
    chain = c.get("/audit/verify", headers=H("bob")).json()
    assert chain["ok"] and not chain["breaks"]
    # the closed case is now a reference for the next one, never a KNOWN fix
    entries = [x for x in c.get("/experience/entries", headers=H("bob")).json() if x["source_ref"].startswith("L#")]
    assert entries and all(x["recurrence"] == "NOT_YET_OBSERVED" for x in entries)
    return closed


def failure(c) -> None:
    ready_to_close(c, effective=False)  # D6 says NOT_EFFECTIVE
    gates = c.get("/cases/L/gates", headers=H("alice")).json()["state"]
    assert gates["D6"] != "DONE" and gates["D4"] != "DONE"  # the cause it rested on is reopened
    acknowledge_all(c)
    r = c.post("/cases/L/closure", json=CLOSE, headers=H("bob"))
    assert r.status_code == 409, r.text
    # re-entry: selecting a new D5 action needs a confirmed cause again
    a = c.post("/cases/L/actions", headers=H("alice"), json={
        "stage": "D5", "action_type": "EQUIPMENT_CHANGE", "cause_ids": [1], "description": "Retry the same fix",
        "details": {"feasibility": "x", "risk_analysis": "y", "side_effects": "z"}})
    assert a.status_code in (409, 422), a.text
    assert c.get("/audit/verify", headers=H("bob")).json()["ok"] is True


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def test_success_d0_to_d8_with_history_and_document_edit(c):  # TC-C-01
    success(c)


def test_failed_effectiveness_blocks_closure_and_reenters_d4(c):  # TC-C-02
    failure(c)
