"""G2: versioned WorkflowPolicy (pure gates), EvidenceQualityAssessment, process-neutral adapters."""

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import policy, quality
from app.db import Base, EvidenceQuality
from app.main import create_app
from app.process import ADAPTERS, MachiningDemoAdapter, PcbAdapter, config_hash
from app.synthetic import generate, spi_correction
from tests.v5_util import H, line_client

B = policy.DEFAULT_BODY


# --- pure policy functions -------------------------------------------------------------------------------

def test_default_policy_matches_s6_chain_for_d2_d4():
    state = {"D2": "APPROVED", "D3": "DRAFT", "D4": None}
    assert policy.can_approve(B, "D3", "QA_PRODUCTION", "erin", "alice", state).result == "PASS"
    blocked = policy.can_approve(B, "D4", "PROCESS_ENGINEER", "frank", "alice", state)
    assert blocked.result == "BLOCK" and "D3 complete" in blocked.reasons[0]
    assert policy.can_draft(B, "D3", {"D2": None}).result == "BLOCK"
    assert policy.can_draft(B, "D3", {"D2": "DRAFT"}).result == "PASS"  # drafts may run ahead


def test_urgent_containment_allowed_after_d0_before_d1_and_d2():
    state = {"D0": "DONE", "D1": None, "D2": None}
    assert policy.can_execute_urgent(B, "QA_PRODUCTION", state, "EMERGENCY_FULL_8D").result == "PASS"


def test_urgent_containment_needs_d0_and_an_authorised_role():
    v = policy.can_execute_urgent(B, "AUTHOR", {"D0": None}, None)
    assert v.result == "BLOCK" and len(v.reasons) == 2
    assert policy.can_execute_urgent(B, "QA_PRODUCTION", {"D0": "DONE"}, "FULL_8D").result == "WARN"


def test_denied_approval_wrong_role_and_self_approval():
    v = policy.can_approve(B, "D2", "REVIEWER", "bob", "bob", {})
    assert v.result == "BLOCK" and "self-approval" in v.reasons[0]
    assert policy.can_approve(B, "D2", "AUTHOR", "alice", "dave", {}).result == "BLOCK"
    lenient = {**copy.deepcopy(B), "self_approval_exceptions": ["D2"]}
    assert policy.can_approve(lenient, "D2", "REVIEWER", "bob", "bob", {}).result == "PASS"


def test_closure_needs_route_and_every_route_stage():
    assert policy.can_close(B, {}, None).result == "BLOCK"
    done = dict.fromkeys(policy.STAGES[:-1], "APPROVED")
    assert policy.can_close(B, done, "FULL_8D").result == "PASS"
    assert policy.can_close(B, {**done, "D6": "DRAFT"}, "FULL_8D").result == "BLOCK"
    assert policy.can_close(B, {"D0": "DONE", "D1": "DONE", "D2": "APPROVED", "D3": "APPROVED"},
                            "NCR_ONLY").result == "PASS"


# --- policy storage --------------------------------------------------------------------------------------

def test_policy_versions_and_most_specific_match(tmp_path):
    c = line_client(tmp_path)
    assert c.post("/policies", json={"policy_id": "CUST-X", "body": B}, headers=H("alice")).status_code == 403
    bad = c.post("/policies", json={"policy_id": "CUST-X", "body": {"routes": {}}}, headers=H("bob"))
    assert bad.status_code == 422
    v1 = c.post("/policies", json={"policy_id": "SITE-A", "applicability": {"site": "SITE-A"}, "body": B},
                headers=H("bob")).json()
    v2 = c.post("/policies", json={"policy_id": "SITE-A", "applicability": {"site": "SITE-A"}, "body": B},
                headers=H("bob")).json()
    assert (v1["version"], v2["version"]) == (1, 2) and v1["policy_hash"] != v2["policy_hash"]
    c.post("/policies", json={"policy_id": "SITE-B", "applicability": {"site": "SITE-B"}, "body": B},
           headers=H("bob"))
    gates = c.get("/cases/L/gates", headers=H("erin")).json()
    assert gates["policy"]["policy_id"] == "SITE-A" and gates["policy"]["version"] == 2
    with Session(c.app_ref.state.engine) as s, pytest.raises(DBAPIError):
        s.execute(text("UPDATE workflow_policies SET body = '{}' WHERE policy_id = 'SITE-A'"))


def test_gates_endpoint_explains_urgent_block_before_triage(tmp_path):
    c = line_client(tmp_path)
    g = c.get("/cases/L/gates", headers=H("erin")).json()
    assert g["policy"]["policy_id"] == "DEFAULT"
    assert g["urgent_containment"]["result"] == "BLOCK"
    assert any("D0" in r for r in g["urgent_containment"]["reasons"])


# --- evidence quality ------------------------------------------------------------------------------------

@pytest.fixture
def s1(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'q.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": "C1"}, headers=H("alice"))
    c.post("/cases/C1/sources", json=generate(7), headers=H("alice"))
    for u in ("bob", "frank"):
        c.post("/cases/C1/assignments", json={"user_id": u}, headers=H("alice"))
    c.app_ref = app
    yield c
    app.state.engine.dispose()


def test_superseded_and_conflicted_evidence_from_existing_flags(s1):
    q = s1.get("/cases/C1/evidence-quality", headers=H("bob")).json()
    states = {i["evidence_id"]: i for i in q["items"]}
    sup = [i for i in states.values() if i["quality_state"] == "SUPERSEDED"]
    assert sup and all(i["checks"]["source_version"] < i["checks"]["latest_version"] for i in sup)
    conf = [i for i in states.values() if i["quality_state"] == "CONFLICTED"]
    assert conf and all("INSPECTION_DISAGREEMENT" in i["checks"]["issues"] for i in conf)
    valid = [i for i in states.values() if i["quality_state"] == "VALID"]
    assert valid and all(i["checks"]["calibration"] == "NOT_IN_SOURCE" for i in valid)
    assert sum(q["counts"].values()) == len(states)


def test_new_source_revision_supersedes_the_old_row_and_is_versioned(s1):
    before = s1.get("/cases/C1/evidence-quality", headers=H("bob")).json()["counts"]
    r = s1.post("/cases/C1/source-revisions", headers=H("alice"),
                json={"asset": spi_correction(7), "reason": "SPI re-measurement"})
    assert r.status_code == 201
    after = s1.get("/cases/C1/evidence-quality", headers=H("bob")).json()["counts"]
    assert after["SUPERSEDED"] == before["SUPERSEDED"] + 1
    with Session(s1.app_ref.state.engine) as s:
        old = [e for e in r.json()["changed_evidence"] if s.scalar(
            select(EvidenceQuality.quality_state).where(EvidenceQuality.evidence_id == e)
            .order_by(EvidenceQuality.version.desc()).limit(1)) == "SUPERSEDED"]
        assert old, "superseded row must get a new assessment version"
        rows = s.scalars(select(EvidenceQuality).where(EvidenceQuality.evidence_id == old[0])).all()
        assert [x.quality_state for x in rows] == ["VALID", "SUPERSEDED"]


def test_root_cause_use_blocks_anything_but_valid():
    assert quality.suitable("VALID", "ROOT_CAUSE") == "PASS"
    for s in ("SUSPECT", "CONFLICTED", "SUPERSEDED", "UNVERIFIED"):
        assert quality.suitable(s, "ROOT_CAUSE") == "BLOCK"
        assert quality.suitable(s, "EFFECTIVENESS") == "BLOCK"
    assert quality.suitable("SUSPECT", "OBSERVATION") == "WARN"
    assert quality.suitable("SUPERSEDED", "OBSERVATION") == "BLOCK"


def test_manual_assessment_can_downgrade_but_not_launder_superseded(s1):
    items = s1.get("/cases/C1/evidence-quality", headers=H("bob")).json()["items"]
    valid = next(i["evidence_id"] for i in items if i["quality_state"] == "VALID")
    sup = next(i["evidence_id"] for i in items if i["quality_state"] == "SUPERSEDED")
    body = {"evidence_id": valid, "quality_state": "SUSPECT", "reason": "gauge drift reported"}
    assert s1.post("/cases/C1/evidence-quality", headers=H("alice"), json=body).status_code == 403
    r = s1.post("/cases/C1/evidence-quality", headers=H("frank"), json=body)
    assert r.status_code == 201 and r.json()["quality_state"] == "SUSPECT"
    r = s1.post("/cases/C1/evidence-quality", headers=H("frank"),
                json={"evidence_id": sup, "quality_state": "VALID", "reason": "looks fine to me"})
    assert r.json()["quality_state"] == "SUPERSEDED"  # a fact the rules established cannot be overridden
    assert s1.post("/cases/C1/evidence-quality", headers=H("frank"),
                   json={"evidence_id": "EV-nope", "quality_state": "VALID", "reason": "xxxxx"}).status_code == 404
    events = [e["event"] for e in s1.get("/cases/C1/timeline", headers=H("bob")).json()]
    assert events.count("EVIDENCE_QUALITY") == 2


def test_effective_state_rules():
    assert quality.effective("UNVERIFIED", None) == "UNVERIFIED"
    assert quality.effective("UNVERIFIED", "VALID") == "VALID"  # a named person verified it
    assert quality.effective("CONFLICTED", "VALID") == "CONFLICTED"
    assert quality.effective("VALID", "SUSPECT") == "SUSPECT"


# --- process-neutral adapters ----------------------------------------------------------------------------

def _contract(adapter, session, case_id):
    ctx = adapter.context(session, case_id)
    objs = adapter.affected_objects(session, case_id)
    meas = adapter.measurements(session, case_id)
    assert set(ctx) == {"process_type", "adapter_version", "operation", "equipment", "recipe"}
    assert objs and all(set(o) == {"object_type", "object_id", "parent_id", "location", "shipment_state",
                                   "identity_source"} for o in objs)
    assert meas and all(set(m) == {"object_id", "characteristic", "value", "unit", "evidence_id", "measured_at",
                                   "source_version"} and isinstance(m["value"], float) for m in meas)
    assert {o["shipment_state"] for o in objs} <= {"IN_PLANT", "SHIPPED", "UNKNOWN"}
    return ctx, objs, meas


def test_pcb_adapter_maps_line_case_without_moving_source_rows(tmp_path):
    c = line_client(tmp_path)
    with Session(c.app_ref.state.engine) as s:
        ctx, objs, meas = _contract(PcbAdapter(), s, "L")
    assert ctx["equipment"] == ["STN-1", "STN-2", "STN-3"]
    assert {o["object_id"] for o in objs if o["object_type"] == "LOT"} == {"L01", "L02", "L03"}
    assert sum(o["shipment_state"] == "SHIPPED" for o in objs) == 12  # first third of each lot
    assert len(meas) == 1152 and {m["unit"] for m in meas} == {"mm3"}
    pc = c.get("/cases/L/process-context", headers=H("bob")).json()
    assert pc["process_type"] == "PCB_SMT" and pc["config_hash"] == config_hash(ctx, objs)
    assert c.post("/cases/L/process-context", json={"site": "X"}, headers=H("alice")).status_code == 409


def test_second_process_fixture_runs_through_unchanged_core(tmp_path):
    c = line_client(tmp_path, process=False)
    with Session(c.app_ref.state.engine) as s:
        _contract(MachiningDemoAdapter(), s, "L")
    r = c.post("/cases/L/process-context", json={"site": "SITE-M", "process_type": "MACHINING_DEMO"},
               headers=H("alice"))
    assert r.status_code == 201 and {o["object_type"] for o in r.json()["objects"]} == {"LOT", "PART"}
    c.post("/policies", json={"policy_id": "MACH", "applicability": {"process_type": "MACHINING_DEMO"},
                              "body": B}, headers=H("bob"))
    assert c.get("/cases/L/gates", headers=H("erin")).json()["policy"]["policy_id"] == "MACH"
    assert set(ADAPTERS) == {"PCB_SMT", "MACHINING_DEMO"}
    assert c.post("/cases/L/process-context", json={"site": "S", "process_type": "WELDING"},
                  headers=H("alice")).status_code == 422
