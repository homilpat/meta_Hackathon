"""RW (spec §25): requests, replies, item review and responsibility on existing cases and the existing Queue."""

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app.intake import FIXTURE_DIR
from app.main import create_app
from tests.test_intake_in2 import Scripted, client
from tests.v5_util import H

V1 = FIXTURE_DIR / "supplier_reply_SN-0001_v1.docx"
V2 = FIXTURE_DIR / "supplier_reply_SN-0001_v2.docx"
AUDIT = FIXTURE_DIR / "audit_evidence_AF-2026-07.pdf"
SUPPLIER = {"supplier": "Daeil Stencil (fictional)", "part_number": "STN-ECU-200", "delivery_lots": ["DL-0921"],
            "problem": "스텐실 개구부 막힘으로 미납 발생", "requested_measures": "봉쇄·원인·재발방지 8D 회신",
            "reply_due_at": "2026-11-10T18:00:00+09:00"}
AUDIT_DETAILS = {"audit_source": "고객 공정 감사 (fictional)", "reference": "AF-2026-07",
                 "finding": "SPI 측정 시스템 분석 기록 없음", "standard": "IATF 16949", "standard_version": "2016 7.1.5.1",
                 "department": "SMT 공정기술", "required_evidence": ["Gauge R&R 결과", "작업자 교육 기록"],
                 "correction_due_at": "2026-11-20T18:00:00+09:00"}


def post(c, path, body=None, user="alice", headers=None):
    return c.post(path, json=body or {}, headers=headers or H(user))


def ok(r, code=201):
    assert r.status_code == code, r.text
    return r.json()


def files(*paths):
    return [{"name": p.name, "content_base64": base64.b64encode(p.read_bytes()).decode()} for p in paths]


def origin_case(c, origin, details):
    case = ok(post(c, "/origin-cases", {"origin": origin, "details": details}))["case_id"]
    for u in ("bob", "dave", "erin"):
        ok(post(c, f"/cases/{case}/assignments", {"user_id": u}))
    return case


def request_body(kind, owner="alice", reviewer="bob", due="2026-11-10T18:00:00+09:00"):
    return {"kind": kind, "title": "협력사 8D 회신", "owner_id": owner, "reviewer_id": reviewer, "due_at": due,
            "due_tz": "KST", "external_party": {"org": "Daeil Stencil", "contact": "품질팀"},
            "items": [{"requirement": "봉쇄 조치", "required_evidence": "보류 기록 번호", "criterion": "보류 기록 존재"},
                      {"requirement": "근본 원인", "required_evidence": "검증 실험", "criterion": "재현 확인"}]}


def tasks(c, user):
    return [(i["task"], i["request_id"]) for i in c.get("/queue", params={"scope": "mine"}, headers=H(user)).json()
            if i["kind"] == "request"]


def opinion(*items):
    return {"items": [{"item_id": i, "verdict": v, "note": n,
                       "sources": [{"element_id": e, "excerpt": x} for e, x in src]} for i, v, n, src in items]}


class Says(Scripted):
    """The request-review double answers with a JSON object (not the intake extraction)."""


def test_supplier_request_reply_revision_resubmission_and_acceptance(tmp_path):
    p = Says()
    c = client(tmp_path, p)
    case = origin_case(c, "SUPPLIER_NONCONFORMITY", SUPPLIER)
    assert ok(c.get(f"/cases/{case}/profile", headers=H("alice")), 200)["origin"] == "SUPPLIER_NONCONFORMITY"
    assert post(c, f"/cases/{case}/requests", request_body("SUPPLIER_CORRECTIVE_ACTION", reviewer="alice")
                ).status_code == 422  # the owner cannot review their own replies
    r = ok(post(c, f"/cases/{case}/requests", request_body("SUPPLIER_CORRECTIVE_ACTION")))
    rid = r["request_id"]
    assert r["status"] == "DRAFT" and [i["item_id"] for i in r["items"]] == ["I1", "I2"]
    assert post(c, f"/cases/{case}/requests", request_body("SUPPLIER_CORRECTIVE_ACTION")).status_code == 409
    assert tasks(c, "alice") == [("REQUEST_OPEN", rid)]
    assert ok(post(c, f"/requests/{rid}/open"))["status"] == "OPEN"
    assert tasks(c, "alice") == [("REQUEST_REPLY", rid)]
    sub = {"files": files(V1), "submitted_by": {"org": "Daeil Stencil", "person": "K. Lee"}}
    assert post(c, f"/requests/{rid}/submissions", sub, user="dave").status_code == 403  # not the owner
    headers = H("alice")
    v1 = ok(post(c, f"/requests/{rid}/submissions", sub, headers=headers))
    assert ok(post(c, f"/requests/{rid}/submissions", sub, headers=headers)) == v1  # a retry is one version
    s1 = v1["submissions"][0]
    assert v1["status"] == "SUBMITTED" and s1["registered_by"] == "alice" and s1["submitted_by"]["org"] == "Daeil Stencil"
    assert s1["submitted_by"]["identity"] == "DOCUMENT_STATED" and s1["files"][0]["data_origin"] == "SYNTHETIC"
    assert tasks(c, "bob") == [("REQUEST_REVIEW", rid)]
    assert post(c, f"/requests/{rid}/decisions", {"submission_version": 1, "files_sha256": s1["files_sha256"],
                                                  "decision": "ACCEPTED", "reason": "x"}, user="bob").status_code == 409
    ok(post(c, f"/requests/{rid}/review-start", user="bob"))
    p.replies.append(opinion(
        ("I1", "SUPPORTED", "봉쇄했다는 문장뿐", [("docx:p2", "we have contained the affected stencils")]),
        ("I2", "SUPPORTED", "원인 언급", [("docx:p9", "nothing")])))  # an invalid source
    ai = ok(post(c, f"/requests/{rid}/ai-review", user="bob"))["reviews"][-1]
    assert ai["kind"] == "AI" and ai["mode"] == "TEST_DOUBLE" and ai["decision"] is None
    assert [x["verdict"] for x in ai["items"]] == ["SUPPORTED", "NEEDS_HUMAN"]  # no source that holds: a person looks
    assert ok(c.get(f"/requests/{rid}", headers=H("alice")), 200)["status"] == "IN_REVIEW"  # AI decided nothing
    out = ok(post(c, f"/requests/{rid}/decisions", {"submission_version": 1, "files_sha256": s1["files_sha256"],
                                                    "decision": "NEEDS_REVISION", "reason": "보류 기록 번호 없음"},
                  user="bob"))
    assert out["status"] == "NEEDS_REVISION" and tasks(c, "alice") == [("REQUEST_REPLY", rid)]
    v2 = ok(post(c, f"/requests/{rid}/submissions", {"files": files(V2), "submitted_by": {"org": "Daeil Stencil"}}))
    assert [s["version"] for s in v2["submissions"]] == [1, 2] and v2["submissions"][0]["current"] is False
    ok(post(c, f"/requests/{rid}/review-start", user="bob"))
    stale = post(c, f"/requests/{rid}/decisions", {"submission_version": 1, "files_sha256": s1["files_sha256"],
                                                   "decision": "ACCEPTED", "reason": "ok"}, user="bob")
    assert stale.status_code == 409 and "stale" in stale.json()["detail"]
    gates_before = c.get(f"/cases/{case}/gates", headers=H("alice")).json()
    s2 = v2["submissions"][1]
    done = ok(post(c, f"/requests/{rid}/decisions", {"submission_version": 2, "files_sha256": s2["files_sha256"],
                                                     "decision": "ACCEPTED", "reason": "보류 기록 HB-221 확인"},
                   user="bob"))
    assert done["status"] == "ACCEPTED" and "실행·효과 입증" in done["note"]
    assert c.get(f"/cases/{case}/gates", headers=H("alice")).json() == gates_before  # not an action, effect or closure
    assert tasks(c, "bob") == [] and tasks(c, "alice") == []
    events = [e["event"] for e in done["events"]]
    assert events == ["CREATED", "OPENED", "SUBMITTED", "REVIEW_STARTED", "AI_REVIEWED", "DECIDED", "SUBMITTED",
                      "REVIEW_STARTED", "DECIDED"]
    raw = c.get(f"/requests/{rid}/files/{s2['files'][0]['file_id']}/content", headers=H("bob"))
    assert raw.content == V2.read_bytes()  # the reviewer reads the reply; the original is unchanged


def test_a_reply_during_review_restarts_it_and_a_new_reply_never_reuses_the_old_decision(tmp_path):
    c = client(tmp_path, None)
    case = origin_case(c, "SUPPLIER_NONCONFORMITY", SUPPLIER)
    rid = ok(post(c, f"/cases/{case}/requests", request_body("SUPPLIER_CORRECTIVE_ACTION")))["request_id"]
    ok(post(c, f"/requests/{rid}/open"))
    v1 = ok(post(c, f"/requests/{rid}/submissions", {"files": files(V1), "submitted_by": {"org": "D"}}))
    ok(post(c, f"/requests/{rid}/review-start", user="bob"))
    v2 = ok(post(c, f"/requests/{rid}/submissions", {"files": files(V2), "submitted_by": {"org": "D"}}))
    assert v2["status"] == "SUBMITTED" and v2["events"][-1]["detail"]["review_restarted"] is True
    ai = ok(post(c, f"/requests/{rid}/ai-review", user="bob"))["reviews"][-1]  # no provider: a person reviews
    assert ai["mode"] == "OFFLINE" and {x["verdict"] for x in ai["items"]} == {"NEEDS_HUMAN"}
    assert post(c, f"/requests/{rid}/decisions", {"submission_version": 1, "decision": "ACCEPTED", "reason": "x",
                                                  "files_sha256": v1["submissions"][0]["files_sha256"]},
                user="bob").status_code == 409  # SUBMITTED again: the review must start on v2


def test_audit_finding_handover_acceptance_evidence_and_review(tmp_path):
    c = client(tmp_path, None)
    case = origin_case(c, "AUDIT_FINDING", AUDIT_DETAILS)
    prof = ok(c.get(f"/cases/{case}/profile", headers=H("alice")), 200)["profile"][0]["details"]
    assert prof["standard_version"] == "2016 7.1.5.1" and prof["department"] == "SMT 공정기술"
    rid = ok(post(c, f"/cases/{case}/requests", request_body("AUDIT_CORRECTIVE_EVIDENCE",
                                                             due="2026-01-01T00:00:00+09:00")))["request_id"]
    ok(post(c, f"/requests/{rid}/open"))
    assert ok(c.get(f"/requests/{rid}", headers=H("alice")), 200)["overdue"] is True
    h = ok(post(c, f"/requests/{rid}/handover", {"to_user": "dave", "reason": "SMT 공정기술 담당으로 이관"}))
    assert h["owner_id"] == "alice" and h["pending_owner_id"] == "dave"  # still alice's until dave accepts
    assert tasks(c, "dave") == [("HANDOVER_ACCEPT", rid)]
    assert post(c, f"/requests/{rid}/submissions", {"files": files(AUDIT), "submitted_by": {"org": "SMT"}},
                user="dave").status_code == 403
    assert post(c, f"/requests/{rid}/handover", {"to_user": "bob", "reason": "x"}).status_code == 409  # pending
    acc = ok(post(c, f"/requests/{rid}/handover/accept", {"reason": "수락"}, user="dave"))
    assert acc["owner_id"] == "dave" and acc["pending_owner_id"] is None
    due = ok(post(c, f"/requests/{rid}/due", {"due_at": "2026-12-20T18:00:00+09:00", "reason": "감사원 승인 연장"},
                  user="dave"))
    assert due["overdue"] is False and due["events"][-1]["detail"]["old"] == "2026-01-01T00:00:00+09:00"
    assert post(c, f"/requests/{rid}/due", {"due_at": "2026-12-20 18:00", "reason": "x"}, user="dave"
                ).status_code == 422  # a due date without an offset is ambiguous
    sub = ok(post(c, f"/requests/{rid}/submissions", {"files": files(AUDIT), "submitted_by": {"org": "SMT 공정기술"}},
                  user="dave"))
    ok(post(c, f"/requests/{rid}/review-start", user="bob"))
    out = ok(post(c, f"/requests/{rid}/decisions", {"submission_version": 1, "decision": "ACCEPTED",
                                                    "files_sha256": sub["submissions"][0]["files_sha256"],
                                                    "reason": "GRR 8.2%, 교육 기록 확인"}, user="bob"))
    trail = [(e["event"], e["from"], e["to"]) for e in out["events"]]
    assert ("HANDOVER_REQUESTED", "alice", "dave") in trail and ("HANDOVER_ACCEPTED", "alice", "dave") in trail
    closure = c.get(f"/cases/{case}/closure", headers=H("alice")).json()
    assert closure["ready"] is False  # an accepted audit reply does not close the case


def test_case_owner_handover_waits_for_acceptance_and_keeps_history(tmp_path):
    c = client(tmp_path, None)
    case = origin_case(c, "SUPPLIER_NONCONFORMITY", SUPPLIER)
    ok(post(c, f"/cases/{case}/owner/handover", {"to_user": "erin", "reason": "생산 품질 이관"}))
    resp = ok(c.get(f"/cases/{case}/responsibilities", headers=H("alice")), 200)
    assert resp["case_owner"]["user_id"] == "alice" and resp["case_owner"]["pending_handover"]["to"] == "erin"
    assert ("HANDOVER_ACCEPT", None) in [(i["task"], i.get("request_id")) for i in
                                         c.get("/queue", params={"scope": "mine"}, headers=H("erin")).json()]
    assert post(c, f"/cases/{case}/owner/handover/accept", user="dave").status_code == 403
    ok(post(c, f"/cases/{case}/owner/handover/decline", {"reason": "담당 범위 아님"}, user="erin"))
    assert ok(c.get(f"/cases/{case}/responsibilities", headers=H("alice")), 200)["case_owner"]["user_id"] == "alice"
    ok(post(c, f"/cases/{case}/owner/handover", {"to_user": "dave", "reason": "재배정"}))
    r = ok(post(c, f"/cases/{case}/owner/handover/accept", user="dave"))
    assert r["case_owner"]["user_id"] == "dave" and r["case_owner"]["pending_handover"] is None
    hist = [(e["event"], e["from"], e["to"]) for e in r["history"] if e["subject"] == "CASE_OWNER"]
    assert hist == [("ASSIGNED", None, "alice"), ("HANDOVER_REQUESTED", "alice", "erin"),
                    ("HANDOVER_DECLINED", "alice", "erin"), ("HANDOVER_REQUESTED", "alice", "dave"),
                    ("HANDOVER_ACCEPTED", "alice", "dave")]
    assert set(r["approvers"]) >= {"D0", "D4", "D8"} and "X-User" in r["identity_note"]


def test_requests_are_case_scoped_and_survive_a_reconnect(tmp_path):
    c = client(tmp_path, None)
    case = origin_case(c, "SUPPLIER_NONCONFORMITY", SUPPLIER)
    rid = ok(post(c, f"/cases/{case}/requests", request_body("SUPPLIER_CORRECTIVE_ACTION")))["request_id"]
    assert c.get(f"/requests/{rid}", headers=H("carol")).status_code == 403  # not on the case
    assert post(c, f"/cases/{case}/requests", {**request_body("INTERNAL"), "owner_id": "carol"}).status_code == 422
    before = ok(c.get(f"/requests/{rid}", headers=H("alice")), 200)
    again = TestClient(create_app(f"sqlite:///{tmp_path / 'in2.db'}"))
    assert ok(again.get(f"/requests/{rid}", headers=H("alice")), 200) == before
    assert json.dumps(before, ensure_ascii=False).count("DOCUMENT_STATED") == 0  # no reply yet


@pytest.mark.parametrize("bad", [{"supplier": "x"}, {}])
def test_origin_details_are_validated(tmp_path, bad):
    c = client(tmp_path, None)
    assert post(c, "/origin-cases", {"origin": "SUPPLIER_NONCONFORMITY", "details": bad}).status_code == 422
