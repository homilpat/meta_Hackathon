"""v5.8 end-to-end scenarios (spec §23-25), run here with TestClient and by scripts/e2e_http.py over real HTTP.

Each takes a client whose server has no model key, so intake is entered by a person (OFFLINE draft) and request
reviews are human: the path that must keep working when the model is down.
"""

from tests.test_intake_in1 import DOCX_FIXTURE, PDF_FIXTURE
from tests.test_requests_rw import AUDIT, AUDIT_DETAILS, SUPPLIER, V1, V2, files, request_body
from tests.v5_util import H


def ok(r, code=201):
    assert r.status_code == code, r.text
    return r.json()


def intake_scenario(c) -> dict:
    up = ok(c.post("/intakes", json={"files": files(PDF_FIXTURE, DOCX_FIXTURE)}, headers=H("alice")))
    iid = up["intake_id"]
    assert [f["data_origin"] for f in up["files"]] == ["SYNTHETIC", "SYNTHETIC"]
    d = ok(c.post(f"/intakes/{iid}/analyze", headers=H("alice")))["draft"]
    assert d["mode"] == "OFFLINE" and all(v["status"] == "MISSING" for v in d["fields"].values())
    entered = [("customer_ref", "HM-CC-2026-0417", "pdf:p1:l3"), ("lot", "L02", "pdf:p1:l12"),
               ("defective_qty", "12", "pdf:p1:l14"), ("part_number", "PCB-ECU-200 rev C", "pdf:p1:l4"),
               ("phenomenon", "open solder joint on U7 pin 3", "pdf:p1:l5")]
    d = ok(c.post(f"/intakes/{iid}/draft/edits", json={"base_version": 1, "changes": [
        {"field": k, "value": v, "reason": "원문 보고 직접 입력", "element_id": e, "excerpt": v} for k, v, e in entered]},
        headers=H("alice")))["draft"]
    assert all(d["fields"][k]["edit"]["source_check"] == "원문 근거 확인" for k, _, _ in entered)
    assert c.get("/cases", headers=H("alice")).json() == [x for x in c.get("/cases", headers=H("alice")).json()
                                                          if not x["case_id"].startswith("CC-")]  # none before confirm
    headers = H("alice")
    view = ok(c.post(f"/intakes/{iid}/confirm", json={"base_version": 2, "action": "NEW_CASE"}, headers=headers))
    assert ok(c.post(f"/intakes/{iid}/confirm", json={"base_version": 2, "action": "NEW_CASE"},
                     headers=headers)) == view
    case = view["case_id"]
    assert view["d0"] == "PENDING" and view["internal_data"]["linked"] is False
    ok(c.post(f"/cases/{case}/assignments", json={"user_id": "bob"}, headers=H("alice")))
    assert [i["task"] for i in c.get("/queue", params={"scope": "mine"}, headers=H("bob")).json()] == ["D0_TRIAGE"]
    ok(c.post(f"/cases/{case}/triage", json={
        "signal_kind": "CUSTOMER_COMPLAINT", "observed_defect": "UNKNOWN", "route": "FULL_8D", "severity": "HIGH",
        "scope_lots": [], "risk_flags": {"customer_impact": True}, "rationale": "고객 보고 12건, 내부 확인 전",
        "evidence_ids": view["intakes"][0]["evidence_ids"][:2]}, headers=H("bob")))
    assert c.get("/queue", params={"scope": "mine"}, headers=H("bob")).json() == []
    assert ok(c.get(f"/cases/{case}/intakes", headers=H("alice")), 200)["d0"] == "DONE"
    return {"case_id": case}


def origin(c, kind, details) -> str:
    case = ok(c.post("/origin-cases", json={"origin": kind, "details": details}, headers=H("alice")))["case_id"]
    for u in ("bob", "dave"):
        ok(c.post(f"/cases/{case}/assignments", json={"user_id": u}, headers=H("alice")))
    return case


def decide(c, rid, sub, decision, reason, user="bob"):
    return c.post(f"/requests/{rid}/decisions", json={"submission_version": sub["version"], "decision": decision,
                                                      "files_sha256": sub["files_sha256"], "reason": reason},
                  headers=H(user))


def supplier_scenario(c) -> dict:
    case = origin(c, "SUPPLIER_NONCONFORMITY", SUPPLIER)
    rid = ok(c.post(f"/cases/{case}/requests", json=request_body("SUPPLIER_CORRECTIVE_ACTION"),
                    headers=H("alice")))["request_id"]
    ok(c.post(f"/requests/{rid}/open", headers=H("alice")))
    s1 = ok(c.post(f"/requests/{rid}/submissions", json={"files": files(V1), "submitted_by": {"org": "Daeil"}},
                   headers=H("alice")))["submissions"][-1]
    ok(c.post(f"/requests/{rid}/review-start", headers=H("bob")))
    assert ok(decide(c, rid, s1, "NEEDS_REVISION", "보류 기록 번호 없음"))["status"] == "NEEDS_REVISION"
    s2 = ok(c.post(f"/requests/{rid}/submissions", json={"files": files(V2), "submitted_by": {"org": "Daeil"}},
                   headers=H("alice")))["submissions"][-1]
    ok(c.post(f"/requests/{rid}/review-start", headers=H("bob")))
    assert decide(c, rid, s1, "ACCEPTED", "옛 버전").status_code == 409  # stale
    gates = c.get(f"/cases/{case}/gates", headers=H("alice")).json()
    assert ok(decide(c, rid, s2, "ACCEPTED", "HB-221 확인"))["status"] == "ACCEPTED"
    assert c.get(f"/cases/{case}/gates", headers=H("alice")).json() == gates
    return {"case_id": case}


def audit_scenario(c) -> dict:
    case = origin(c, "AUDIT_FINDING", AUDIT_DETAILS)
    rid = ok(c.post(f"/cases/{case}/requests", json=request_body("AUDIT_CORRECTIVE_EVIDENCE"),
                    headers=H("alice")))["request_id"]
    ok(c.post(f"/requests/{rid}/open", headers=H("alice")))
    ok(c.post(f"/requests/{rid}/handover", json={"to_user": "dave", "reason": "공정기술 담당"}, headers=H("alice")))
    assert [i["task"] for i in c.get("/queue", params={"scope": "mine"}, headers=H("dave")).json()] == ["HANDOVER_ACCEPT"]
    assert ok(c.post(f"/requests/{rid}/handover/accept", json={}, headers=H("dave")))["owner_id"] == "dave"
    sub = ok(c.post(f"/requests/{rid}/submissions", json={"files": files(AUDIT), "submitted_by": {"org": "SMT"}},
                    headers=H("dave")))["submissions"][-1]
    ok(c.post(f"/requests/{rid}/review-start", headers=H("bob")))
    assert ok(decide(c, rid, sub, "ACCEPTED", "GRR 8.2%"))["status"] == "ACCEPTED"
    assert c.get(f"/cases/{case}/closure", headers=H("alice")).json()["ready"] is False
    return {"case_id": case}


def test_v58_scenarios_in_process(tmp_path):
    from tests.test_intake_in2 import client

    for k, scenario in enumerate((intake_scenario, supplier_scenario, audit_scenario)):
        (tmp_path / str(k)).mkdir()
        scenario(client(tmp_path / str(k), None))
