"""v5.5 PREFLIGHT: the S6 document approvals and the v5 gates take one decision from the active WorkflowPolicy."""

import copy

import pytest

from app.policy import DEFAULT_BODY
from app.synthetic import spi_correction
from tests.v5_util import H, evidence, line_client


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def create(c, kind):
    r = c.post(f"/cases/L/{kind}", json={}, headers=H("alice"))
    assert r.status_code == 201, r.text
    return r.json()


def request(c, kind, reviewer, version=1):
    return c.post(f"/cases/L/{kind}/{version}/request-review", json={"reviewer_id": reviewer}, headers=H("alice"))


def decide(c, kind, reviewer, sha, version=1, decision="APPROVE"):
    return c.post(f"/cases/L/{kind}/{version}/decision", headers=H(reviewer),
                  json={"decision": decision, "comment": "ok", "content_sha256": sha})


def approve(c, kind, reviewer):
    d = request(c, kind, reviewer)
    assert d.status_code == 200, d.text
    r = decide(c, kind, reviewer, d.json()["content_sha256"])
    assert r.status_code == 200, r.text
    return r.json()


def publish(c, **gates):
    body = copy.deepcopy(DEFAULT_BODY)
    for stage, gate in gates.items():
        body["approval_gates"][stage] = {**body["approval_gates"][stage], **gate}
    r = c.post("/policies", json={"policy_id": "DEFAULT", "body": body}, headers=H("bob"))
    assert r.status_code == 201, r.text
    return r.json()


def gates(c, user):
    return c.get("/cases/L/gates", headers=H(user)).json()


def test_default_policy_and_s6_chain_agree_on_rca_without_d3_actions(c):
    """Old disagreement: the v5 gate read D3 as PLAN_APPROVED (no verified actions) and blocked D4, while the S6
    route approved the RCA. Document approvals now read document states in both places."""
    create(c, "ncr")
    approve(c, "ncr", "bob")
    create(c, "containment")
    approve(c, "containment", "erin")
    create(c, "rca")
    g = gates(c, "frank")
    assert g["state"]["D3"] == "PLAN_APPROVED"  # containment itself is still not done
    assert g["approve"]["D4"]["result"] == "PASS"
    approve(c, "rca", "frank")
    assert gates(c, "frank")["state"]["D4"] == "NO_CONFIRMED_CAUSE"  # approved hypotheses, no cause decided


def test_policy_drives_the_s6_route_not_a_hardcoded_role(c):
    publish(c, D2={"approver": "PROCESS_ENGINEER"})
    create(c, "ncr")
    assert request(c, "ncr", "bob").status_code == 422  # REVIEWER no longer approves D2
    assert gates(c, "bob")["approve"]["D2"]["result"] == "BLOCK"
    approve(c, "ncr", "frank")
    assert c.get("/cases/L/stages", headers=H("alice")).json()[0]["approver_role"] == "PROCESS_ENGINEER"


def test_policy_prerequisite_blocks_s6_approval(c):
    publish(c, D2={"requires": ["D0"]})
    d = create(c, "ncr")
    assert request(c, "ncr", "bob").status_code == 200
    r = decide(c, "ncr", "bob", d["content_sha256"])
    assert r.status_code == 409 and "D0 complete" in r.json()["detail"]
    assert decide(c, "ncr", "bob", d["content_sha256"], decision="REQUEST_INFO").status_code == 200


def test_stale_policy_version_is_reevaluated_at_decision(c):
    d = create(c, "ncr")
    assert request(c, "ncr", "bob").status_code == 200
    p = publish(c, D2={"approver": "PROCESS_ENGINEER"})  # changed while the review was open
    r = decide(c, "ncr", "bob", d["content_sha256"])
    assert r.status_code == 403 and "PROCESS_ENGINEER" in r.json()["detail"]
    assert c.get("/cases/L/ncr/1", headers=H("alice")).json()["status"] == "IN_REVIEW"
    # an unchanged rule under a new version passes, and the trail says it was re-evaluated
    publish(c)
    ok = decide(c, "ncr", "bob", d["content_sha256"])
    assert ok.status_code == 200, ok.text
    detail = [e["detail"] for e in c.get("/cases/L/timeline", headers=H("alice")).json() if e["event"] == "APPROVE"]
    assert "re-evaluated" in detail[-1] and p["policy_hash"] not in detail[-1]


def test_legacy_approval_survives_a_new_policy(c):
    approved = (create(c, "ncr"), approve(c, "ncr", "bob"))[1]
    publish(c, D2={"approver": "PROCESS_ENGINEER"})
    now = c.get("/cases/L/ncr/1", headers=H("alice")).json()
    assert now["status"] == "APPROVED" and now["content_sha256"] == approved["content_sha256"]
    assert now["decisions"] == approved["decisions"]
    create(c, "containment")
    approve(c, "containment", "erin")  # D3 builds on the D2 approval made under the old policy


def test_self_approval_blocked_unless_policy_exception(c):
    publish(c, D2={"approver": "AUTHOR"})
    create(c, "ncr")
    r = request(c, "ncr", "alice")
    assert r.status_code == 422 and "self-approval" in r.json()["detail"]
    approve(c, "ncr", "dave")  # another AUTHOR is fine
    body = copy.deepcopy(DEFAULT_BODY)
    body["approval_gates"]["D3"]["approver"] = "AUTHOR"
    body["self_approval_exceptions"] = ["D3"]
    assert c.post("/policies", json={"policy_id": "DEFAULT", "body": body}, headers=H("bob")).status_code == 201
    create(c, "containment")
    approve(c, "containment", "alice")
    events = [e["event"] for e in c.get("/cases/L/timeline", headers=H("alice")).json()]
    assert "SELF_APPROVAL_EXCEPTION" in events  # each use of the exception is on the record


def test_urgent_containment_before_d1_d2_does_not_fake_d3_approval(c):
    spc = evidence(c, "L", "spi_measurements", panel_id="L02-P02", board_id="B2")
    t = c.post("/cases/L/triage", headers=H("bob"), json={
        "signal_kind": "SPC_SIGNAL", "observed_defect": "SIGNAL_ONLY", "scope_lots": ["L02"],
        "route": "EMERGENCY_FULL_8D", "severity": "HIGH", "risk_flags": {}, "rationale": "WE1 on L02 panel 2",
        "evidence_ids": spc})
    assert t.status_code == 201
    a = c.post("/cases/L/urgent-actions", headers=H("erin"), json={
        "action_type": "HOLD", "description": "Hold unshipped L02 panels", "targets": ["L02-P09"]})
    assert a.status_code == 201, a.text
    ex = c.post(f"/cases/L/actions/{a.json()['action_id']}/events", headers=H("erin"),
                json={"event_type": "EXECUTED", "note": "held at SMT-1 exit (simulated)"})
    assert ex.status_code == 201
    g = gates(c, "erin")
    assert g["state"]["D1"] is None and g["state"]["D2"] is None and g["state"]["D3"] is None
    assert g["approve"]["D3"]["result"] == "BLOCK"


def test_source_correction_during_review_blocks_the_stale_approval(c):
    d = create(c, "ncr")
    assert request(c, "ncr", "bob").status_code == 200
    rev = c.post("/cases/L/source-revisions", headers=H("alice"),
                 json={"asset": spi_correction(7, row_id="SPI-L02-P02-B2-C01-1", version=2, line=True), "reason": "re-measured"})
    assert rev.status_code == 201, rev.text
    r = decide(c, "ncr", "bob", d["content_sha256"])
    assert r.status_code in (403, 409)
    assert c.get("/cases/L/ncr/1", headers=H("alice")).json()["status"] != "APPROVED"
    assert c.get("/audit/verify", headers=H("alice")).json()["ok"] is True
