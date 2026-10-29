"""G3: D0 triage (signal != defect), urgent containment before D1, D1 cross-functional team."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import AffectedObject
from tests.v5_util import H, evidence, line_client


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def spc_ev(c):
    return evidence(c, "L", "spi_measurements", panel_id="L02-P02", board_id="B2")


def triage(c, user="bob", **kw):
    body = {"signal_kind": "SPC_SIGNAL", "observed_defect": "SIGNAL_ONLY", "scope_lots": ["L02"],
            "route": "EMERGENCY_FULL_8D", "severity": "HIGH", "risk_flags": {"customer_impact": True},
            "rationale": "WE1 on lot L02 panel 2; shipped panels in lot", "evidence_ids": spc_ev(c), **kw}
    return c.post("/cases/L/triage", json=body, headers=H(user))


def hold(c, user="erin", targets=("L02-P09",), action_type="HOLD"):
    return c.post("/cases/L/urgent-actions", headers=H(user),
                  json={"action_type": action_type, "description": "Hold unshipped L02 panels at SMT-1 exit",
                        "targets": list(targets)})


def event(c, aid, user, event_type, note="", evidence=()):
    return c.post(f"/cases/L/actions/{aid}/events", headers=H(user),
                  json={"event_type": event_type, "note": note, "evidence": list(evidence)})


# --- D0 ---------------------------------------------------------------------------------------------------

def test_spc_signal_alone_cannot_be_triaged_as_confirmed_defect(c):
    r = triage(c, observed_defect="DEFECT_CONFIRMED")
    assert r.status_code == 422 and "not a confirmed defect" in r.json()["detail"]


def test_confirmed_defect_needs_human_verification_evidence(c):
    hv = evidence(c, "L", "human_verifications", result="DEFECT_CONFIRMED", panel_id="L02*")
    assert hv
    r = triage(c, observed_defect="DEFECT_CONFIRMED", evidence_ids=spc_ev(c) + hv[:1])
    assert r.status_code == 201
    t = r.json()
    assert t["signal_kind"] == "SPC_SIGNAL" and t["observed_defect"] == "DEFECT_CONFIRMED"  # stored apart
    assert t["risk_flags"]["shipped_in_scope"] is True  # computed from L02's shipped panels


def test_false_positive_signal_can_take_ncr_only_route(c):
    r = triage(c, scope_lots=["L03"], route="NCR_ONLY", severity="LOW", risk_flags={},
               rationale="WE4 drift in L03; every AOI fail was a false call",
               evidence_ids=evidence(c, "L", "spi_measurements", panel_id="L03-P05", board_id="B1"))
    assert r.status_code == 201 and r.json()["route"] == "NCR_ONLY"


def test_ncr_only_refused_for_possible_defect_with_shipped_exposure(c):
    r = triage(c, observed_defect="UNKNOWN", route="NCR_ONLY", risk_flags={})
    assert r.status_code == 422 and "NCR_ONLY" in r.json()["detail"]


def test_triage_role_and_inputs(c):
    assert triage(c, user="alice").status_code == 403  # D0 decision belongs to quality (REVIEWER)
    assert triage(c, evidence_ids=["EV-00000000000000000000"]).status_code == 422
    assert triage(c, scope_lots=["L99"]).status_code == 422


# --- urgent containment -----------------------------------------------------------------------------------

def test_urgent_hold_blocked_before_d0(c):
    r = hold(c)
    assert r.status_code == 403 and "D0" in r.json()["detail"]


def test_emergency_hold_allowed_after_d0_before_team_and_documents(c):
    assert triage(c).status_code == 201
    gates = c.get("/cases/L/gates", headers=H("erin")).json()
    assert gates["state"]["D1"] is None and gates["state"]["D2"] is None
    assert gates["urgent_containment"]["result"] == "PASS"
    r = hold(c, targets=["L02-P05", "L02-P06"])
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "REQUESTED" and a["execution_mode"] == "SIMULATED"
    assert [s["shipment_state"] for s in a["target_snapshot"]] == ["IN_PLANT", "IN_PLANT"]


def test_hold_cannot_target_shipped_product_and_unknown_objects(c):
    triage(c)
    r = hold(c, targets=["L02-P01"])
    assert r.status_code == 422 and "SHIPPED" in r.json()["detail"]
    assert hold(c, targets=["L02-P01"], action_type="CUSTOMER_NOTIFY_REQUEST").status_code == 201
    assert hold(c, targets=["NOPE"]).status_code == 422


def test_only_authorised_role_executes_and_verifier_must_be_independent(c):
    triage(c)
    assert hold(c, user="alice").status_code == 403
    aid = hold(c).json()["action_id"]
    assert event(c, aid, "bob", "INDEPENDENTLY_VERIFIED", evidence=["REF:count"]).status_code == 409  # not executed
    assert event(c, aid, "alice", "EXECUTED", note="held 4 boards in cage A").status_code == 403
    assert event(c, aid, "erin", "EXECUTED", note="  ").status_code == 422  # a note is required, its length is free
    assert event(c, aid, "erin", "EXECUTED", note="held panel L02-P09 in cage A").status_code == 201
    assert event(c, aid, "erin", "INDEPENDENTLY_VERIFIED", evidence=["REF:count"]).status_code == 403  # self
    assert event(c, aid, "bob", "INDEPENDENTLY_VERIFIED").status_code == 422  # no verification evidence
    r = event(c, aid, "bob", "INDEPENDENTLY_VERIFIED", evidence=["REF:cage-A count sheet"])
    assert r.status_code == 201
    assert [e["event_type"] for e in r.json()["events"]] == ["REQUESTED", "EXECUTED", "INDEPENDENTLY_VERIFIED"]
    assert all(e["synthetic"] for e in r.json()["events"])


def test_no_invented_execution_and_no_real_shipment_state_change(c):
    triage(c)
    before = _states(c)
    aid = hold(c).json()["action_id"]
    assert event(c, aid, "erin", "PLAN_APPROVED").status_code == 422  # urgent actions have no plan step here
    event(c, aid, "erin", "EXECUTED", note="held panel L02-P09 in cage A")
    assert _states(c) == before  # simulated: affected objects untouched
    actions = c.get("/cases/L/actions", headers=H("bob")).json()
    assert actions[0]["status"] == "EXECUTED" and actions[0]["execution_mode"] == "SIMULATED"
    timeline = [e["event"] for e in c.get("/cases/L/timeline", headers=H("bob")).json()]
    assert "URGENT_ACTION_REQUESTED" in timeline and "ACTION_EXECUTED" in timeline


def _states(c):
    with Session(c.app_ref.state.engine) as s:
        return sorted((o.object_id, o.shipment_state) for o in s.scalars(select(AffectedObject)))


# --- D1 team ----------------------------------------------------------------------------------------------

def assign(c, resp, user, by="alice", due=None):
    return c.post("/cases/L/team", headers=H(by),
                  json={"event": "ASSIGN", "responsibility": resp, "user_id": user, "due_at": due})


def accept(c, resp, user):
    return c.post("/cases/L/team", headers=H(user), json={"event": "ACCEPT", "responsibility": resp})


def test_team_requires_every_role_accepted(c):
    for resp, user in (("LEAD", "alice"), ("QUALITY", "bob"), ("PRODUCTION", "erin"), ("PROCESS", "frank")):
        assert assign(c, resp, user).status_code == 201
    t = c.get("/cases/L/team", headers=H("bob")).json()
    assert not t["complete"] and set(t["missing"]) == {"LEAD", "QUALITY", "PRODUCTION", "PROCESS"}
    for resp, user in (("LEAD", "alice"), ("QUALITY", "bob"), ("PRODUCTION", "erin")):
        accept(c, resp, user)
    assert c.get("/cases/L/gates", headers=H("bob")).json()["state"]["D1"] == "IN_PROGRESS"
    accept(c, "PROCESS", "frank")
    assert c.get("/cases/L/team", headers=H("bob")).json()["complete"]
    assert c.get("/cases/L/gates", headers=H("bob")).json()["state"]["D1"] == "DONE"


def test_missing_actor_wrong_role_and_alternate_assignee(c):
    assert assign(c, "PROCESS", "erin").status_code == 422  # role mismatch
    assert assign(c, "QUALITY", "bob", by="bob").status_code == 403  # only the lead role assigns
    assert accept(c, "QUALITY", "bob").status_code == 409  # nothing assigned yet
    assign(c, "QUALITY", "bob", due="2026-01-01T00:00:00+00:00")
    t = c.get("/cases/L/team", headers=H("bob")).json()
    assert t["members"]["QUALITY"]["overdue"] is True
    assert accept(c, "QUALITY", "carol").status_code == 409  # not carol's assignment
    c.post("/cases/L/team", headers=H("bob"), json={"event": "DECLINE", "responsibility": "QUALITY",
                                                    "note": "on leave"})
    assert assign(c, "QUALITY", "carol").status_code == 201  # alternate
    assert accept(c, "QUALITY", "carol").json()["members"]["QUALITY"]["status"] == "ACCEPTED"


def test_exception_is_logged_with_reason(c):
    r = c.post("/cases/L/team", headers=H("alice"), json={"event": "EXCEPTION", "responsibility": "PROCESS",
                                                          "note": " "})
    assert r.status_code == 422  # blank; any written reason is accepted
    r = c.post("/cases/L/team", headers=H("alice"),
               json={"event": "EXCEPTION", "responsibility": "PROCESS", "note": "no process engineer on night shift"})
    assert r.json()["members"]["PROCESS"]["status"] == "EXCEPTION"
    assert "TEAM_EXCEPTION" in [e["event"] for e in c.get("/cases/L/timeline", headers=H("bob")).json()]


def test_old_document_chain_unchanged_by_triage(c):
    triage(c)
    assert c.post("/cases/L/containment", json={}, headers=H("alice")).status_code == 409  # still needs NCR draft
    assert c.post("/cases/L/ncr", json={}, headers=H("alice")).status_code == 201
