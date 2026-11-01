"""IN3 (spec §23.2, §23.4): only a person's confirmation makes or links a case; D0, Queue and D2 are reused."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Closure, DocumentVersion, QualityCase, SourceEvent
from tests.test_intake_in1 import DOCX_FIXTURE, PDF_FIXTURE, upload
from tests.test_intake_in2 import Scripted, analyze, client, extraction, two_files
from tests.v5_util import H, line_client


def confirm(c, iid, base, user="alice", headers=None, **extra):
    return c.post(f"/intakes/{iid}/confirm", json={"base_version": base, "action": "NEW_CASE", **extra},
                  headers=headers or H(user))


def resolve(c, iid, base):
    return c.post(f"/intakes/{iid}/draft/edits", json={"base_version": base, "changes": [
        {"field": "lot", "value": "L02", "reason": "고객 통화로 출하 LOT 확인", "element_id": "pdf:p1:l12",
         "excerpt": "L02"},
        {"field": "reply_deadline", "value": "2026-10-31 18:00 KST", "reason": "금요일 = 2026-10-31로 확인"}]},
        headers=H("alice")).json()["draft"]["version"]


def drafted(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    iid, pdf_id, docx_id = two_files(c)
    p.replies.append(extraction(pdf_id, docx_id))
    assert analyze(c, iid).json()["draft"]["version"] == 1
    return c, iid


def cases(c) -> int:
    with Session(c.app.state.engine) as s:
        return s.scalar(select(func.count()).select_from(QualityCase))


def test_a_case_needs_a_resolved_confirmed_draft_and_a_retry_makes_one_case(tmp_path):
    c, iid = drafted(tmp_path)
    r = confirm(c, iid, 1)
    assert r.status_code == 409 and "lot" in r.json()["detail"] and "reply_deadline" in r.json()["detail"]
    assert cases(c) == 0  # T01: analysis, upload and a refused confirm make no case
    v = resolve(c, iid, 1)
    assert confirm(c, iid, 1).status_code == 409 and cases(c) == 0  # stale: the person confirmed an old version
    headers = H("alice")
    first = confirm(c, iid, v, headers=headers)
    assert first.status_code == 201, first.text
    assert confirm(c, iid, v, headers=headers).json() == first.json()  # T06: the same click again
    assert confirm(c, iid, v).status_code == 409 and cases(c) == 1  # a second confirm: already linked
    view = first.json()
    assert view["case_id"] == f"CC-{iid}" and view["origin"] == "CUSTOMER_COMPLAINT" and view["channel"] == "CHAT_UPLOAD"
    assert view["owner_id"] == "alice" and view["d0"] == "PENDING" and view["data_origin"] == "SYNTHETIC"
    assert view["internal_data"]["linked"] is False and "복사하지 않습니다" in view["internal_data"]["note"]
    assert c.get(f"/cases/{view['case_id']}/intakes", headers=H("alice")).json() == view  # T10: re-read
    assert any(x["case_id"] == view["case_id"] for x in c.get("/cases", headers=H("alice")).json())


def test_confirmed_values_become_customer_reported_evidence_and_nothing_internal_is_copied(tmp_path):
    c, iid = drafted(tmp_path)
    case = confirm(c, iid, resolve(c, iid, 1)).json()["case_id"]
    ev = {e["evidence_id"]: e for e in c.get(f"/cases/{case}/evidence", headers=H("alice")).json()}
    assert set(confirm_ids := c.get(f"/cases/{case}/intakes", headers=H("alice")).json()["intakes"][0]
               ["evidence_ids"]) == set(ev)
    assert len(confirm_ids) >= 8
    with Session(c.app.state.engine) as s:  # T12: no SPI / AOI / shipment row was created or copied
        kinds = set(s.scalars(select(SourceEvent.entity_type).where(SourceEvent.case_id == case)))
        assert kinds == {"CUSTOMER_REPORT"}
    assert c.get(f"/cases/{case}/spc", headers=H("alice")).status_code == 404
    raw = [e for e in ev.values()]
    assert raw, "evidence listed"


def test_the_new_case_enters_d0_through_the_existing_queue_and_triage(tmp_path):
    c, iid = drafted(tmp_path)
    case = confirm(c, iid, resolve(c, iid, 1)).json()["case_id"]
    mine = c.get("/queue", params={"scope": "mine"}, headers=H("alice")).json()
    assert [(i["case_id"], i["task"]) for i in mine] == [(case, "D0_UNASSIGNED")]  # unassigned: said, with a path
    assert c.post(f"/cases/{case}/assignments", json={"user_id": "bob"}, headers=H("alice")).status_code == 201
    bob = c.get("/queue", params={"scope": "mine"}, headers=H("bob")).json()
    assert [(i["case_id"], i["task"], i["owner"]) for i in bob] == [(case, "D0_TRIAGE", "bob")]
    ids = c.get(f"/cases/{case}/intakes", headers=H("alice")).json()["intakes"][0]["evidence_ids"]
    t = c.post(f"/cases/{case}/triage", json={
        "signal_kind": "CUSTOMER_COMPLAINT", "observed_defect": "UNKNOWN", "route": "FULL_8D", "severity": "HIGH",
        "scope_lots": [], "risk_flags": {"customer_impact": True}, "rationale": "고객 보고 12건, 내부 확인 전",
        "evidence_ids": ids[:3]}, headers=H("bob"))
    assert t.status_code == 201, t.text  # T13: the existing D0 route, policy and evidence check
    assert c.get("/queue", params={"scope": "mine"}, headers=H("bob")).json() == []
    confirmed = c.post(f"/cases/{case}/triage", json={
        "signal_kind": "CUSTOMER_COMPLAINT", "observed_defect": "DEFECT_CONFIRMED", "route": "FULL_8D",
        "severity": "HIGH", "scope_lots": [], "risk_flags": {}, "rationale": "고객이 불량이라고 함",
        "evidence_ids": ids[:3]}, headers=H("bob"))
    assert confirmed.status_code == 422  # a customer's report is not a confirmed defect


def test_others_cannot_confirm_or_link_into_cases_they_cannot_see(tmp_path):
    c, iid = drafted(tmp_path)
    v = resolve(c, iid, 1)
    assert confirm(c, iid, v, user="dave").status_code == 404  # T07: not dave's intake
    assert confirm(c, iid, v, user="bob").status_code == 403  # reviewers do not create cases
    other = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())], user="dave").json()["intake_id"]
    c.post(f"/intakes/{other}/analyze", headers=H("dave"))
    r = c.post(f"/intakes/{other}/confirm", json={"base_version": 1, "action": "LINK_EXISTING",
                                                   "case_id": "NOPE"}, headers=H("dave"))
    assert r.status_code == 404 and cases(c) == 0


def test_linking_to_an_existing_case_adds_evidence_and_never_reopens_or_touches_approved_work(tmp_path):
    c = line_client(tmp_path)  # case L with internal line data; alice is assigned
    assert c.post("/cases/L/ncr", json={}, headers=H("alice")).status_code == 201
    iid = upload(c, [("supp.docx", DOCX_FIXTURE.read_bytes())]).json()["intake_id"]
    c.post(f"/intakes/{iid}/analyze", headers=H("alice"))  # no provider: an empty draft, linked as is
    with Session(c.app_ref.state.engine) as s:
        before = [(d.doc_type, d.version, d.status) for d in s.scalars(select(DocumentVersion))]
    r = c.post(f"/intakes/{iid}/confirm", json={"base_version": 1, "action": "LINK_EXISTING", "case_id": "L"},
               headers=H("alice"))
    assert r.status_code == 201 and r.json()["internal_data"]["linked"] is True
    with Session(c.app_ref.state.engine) as s:
        assert [(d.doc_type, d.version, d.status) for d in s.scalars(select(DocumentVersion))] == before
        s.add(Closure(case_id="L", decision="CLOSED", snapshot={}, snapshot_sha256="0" * 64, residual_risks=[],
                      customer_notification_ref=None, comment="test", actor_id="alice", policy_hash="x",
                      created_at="2026-11-01T00:00:00+00:00"))
        s.commit()
    later = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())]).json()["intake_id"]
    c.post(f"/intakes/{later}/analyze", headers=H("alice"))
    r = c.post(f"/intakes/{later}/confirm", json={"base_version": 1, "action": "LINK_EXISTING", "case_id": "L"},
               headers=H("alice"))
    assert r.status_code == 409 and "재개하지 않습니다" in r.json()["detail"]  # T14


def test_a_new_case_needs_at_least_one_confirmed_value(tmp_path):
    c = client(tmp_path, None)  # OFFLINE: nothing extracted
    iid = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())]).json()["intake_id"]
    c.post(f"/intakes/{iid}/analyze", headers=H("alice"))
    r = confirm(c, iid, 1)
    assert r.status_code == 409 and "확인된 값" in r.json()["detail"] and cases(c) == 0


def test_duplicate_candidates_are_shown_never_merged(tmp_path):
    c, iid = drafted(tmp_path)
    confirm(c, iid, resolve(c, iid, 1))
    again = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes())]).json()["intake_id"]
    dup = c.get(f"/intakes/{again}/duplicates", headers=H("alice")).json()
    assert dup == [{"intake_id": iid, "same_file": True, "same_customer_ref": False, "case_id": f"CC-{iid}"}]
    assert c.get(f"/intakes/{again}/duplicates", headers=H("dave")).status_code == 404


def test_the_agent_runs_on_a_case_with_customer_data_only(tmp_path):
    c, iid = drafted(tmp_path)
    case = confirm(c, iid, resolve(c, iid, 1)).json()["case_id"]
    for goal in ("진행 상태 알려줘", "불량 원인 조사해 줘"):
        out = c.post("/agent/runs", json={"case_id": case, "goal": goal},
                     headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex})
        assert out.status_code in (200, 201), out.text
        assert out.json()["status"] in ("COMPLETED", "BLOCKED", "NEEDS_HUMAN"), out.json()
