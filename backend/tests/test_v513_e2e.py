"""v5.13 integrated scenario (spec §22-28), run here with TestClient and by scripts/e2e_http.py over real HTTP.

Real bytes in: the synthetic complaint PDF and supplement DOCX, then an inspection XLSX. A person enters and confirms
the draft (no model key on the server), maps and confirms the XLSX rows, reconciles them with the complaint, asks the
agent a partly supported request, drafts, reviews and approves the NCR, exports it as DOCX and PDF, and every
step is re-read from the API: responsibilities, Queue and timeline agree. The investigation loop needs a model and is
covered in-process (tests/test_repair_loop.py); over HTTP without a key it is NOT_RUN by design.
"""

import base64

from tests.test_inspection_xlsx import workbook
from tests.test_v58_e2e import intake_scenario, ok
from tests.v5_util import H


def integrated_scenario(c) -> dict:
    case = intake_scenario(c)["case_id"]  # PDF+DOCX -> manual draft -> confirm -> D0 by bob (re-read inside)
    for u in ("erin", "frank"):
        ok(c.post(f"/cases/{case}/assignments", json={"user_id": u}, headers=H("alice")))

    # inspection XLSX: real bytes, one row blocked, a person excludes it with a reason
    data = workbook([["PCB-ECU-200 rev C", "L02", "2026-10-27", 480, 12, "보드"],
                     ["PCB-ECU-200 rev C", "L02", "2026-10-28", 10, 12, "보드"]])
    up = ok(c.post("/intakes", json={"files": [{"name": "inspection.xlsx",
                                                 "content_base64": base64.b64encode(data).decode()}]},
                   headers=H("alice")))
    iid, fid = up["intake_id"], up["files"][0]["file_id"]
    v = ok(c.get(f"/intakes/{iid}/files/{fid}/inspection", headers=H("alice")), 200)
    assert v["mapping"]["lot"] == "B" and any(i["level"] == "BLOCK" for i in v["rows"][1]["issues"])
    body = {"intake_id": iid, "file_id": fid, "file_sha256": v["file_sha256"], "sheet": v["sheet"],
            "header_row": v["header_row"], "mapping": v["mapping"], "include_rows": [3],
            "exclude": {"4": "불량>검사 수량: 원본 확인 요청"}}
    imp = ok(c.post(f"/cases/{case}/inspection-imports", json=body, headers=H("alice")))
    assert ok(c.post(f"/cases/{case}/inspection-imports", json=body, headers=H("alice")), 200)["import_id"] == \
        imp["import_id"]  # the same confirmation again is the same import
    rec = ok(c.get(f"/cases/{case}/inspection-imports/{imp['import_id']}/reconciliation",
                   params={"comparable": "defective_qty"}, headers=H("alice")), 200)
    status = {i["field"]: i for i in rec["items"]}
    assert status["lot"]["status"] == "MATCH" and status["defective_qty"]["status"] == "MATCH"
    assert status["defective_qty"]["calculation_id"].startswith("CALC-")  # the server summed the rows

    # the agent: a partly supported request runs only its supported part; a person's decision is refused
    asked = ok(c.post("/agent/runs", json={"case_id": case, "goal": "진행 상태 알려주고 고객에게 메일 보내줘"},
                      headers=H("alice")))
    assert asked["status"] == "NEEDS_HUMAN" and asked["pending"]["action"] == "confirm_partial"
    done = ok(c.post(f"/agent/runs/{asked['run_id']}/resume", json={"token": asked["pending"]["token"],
                                                                     "confirm": True}, headers=H("alice")), 200)
    assert done["status"] == "PARTIAL" and all(s["kind"] == "READ" for s in done["steps"])
    human = ok(c.post("/agent/runs", json={"case_id": case, "goal": "NCR 승인해줘"}, headers=H("alice")))
    assert human["status"] == "BLOCKED" and human["request"]["class"] == "HUMAN_ONLY" and not human["steps"]

    # NCR: draft -> validate -> review -> a person's approval -> approved export only
    ncr = ok(c.post(f"/cases/{case}/ncr", json={}, headers=H("alice")))
    ok(c.post(f"/cases/{case}/ncr/{ncr['version']}/validate", headers=H("alice")))
    assert c.get(f"/cases/{case}/documents/ncr/export", params={"format": "docx", "version": ncr["version"]},
                 headers=H("bob")).status_code == 409  # not approved: no export
    ok(c.post(f"/cases/{case}/ncr/{ncr['version']}/request-review", json={"reviewer_id": "bob"},
              headers=H("alice")), 200)
    d = ok(c.get(f"/cases/{case}/ncr/{ncr['version']}", headers=H("bob")), 200)
    ok(c.post(f"/cases/{case}/ncr/{ncr['version']}/decision", headers=H("bob"), json={
        "decision": "APPROVE", "comment": "고객 보고와 검사 결과 대조 확인", "content_sha256": d["content_sha256"]}), 200)
    files = {}
    for fmt in ("docx", "pdf"):
        r = c.get(f"/cases/{case}/documents/ncr/export", params={"format": fmt, "version": ncr["version"]},
                  headers=H("bob"))
        assert r.status_code == 200 and r.headers["x-reference-sha256"], r.text
        files[fmt] = len(r.content)

    # re-read: the responsibility view, Queue and timeline say the same thing
    resp = ok(c.get(f"/cases/{case}/responsibilities", headers=H("alice")), 200)
    dec = next(x for x in resp["decisions"] if x["doc_type"] == "NCR")
    signed = dec["decisions"][-1]
    assert (signed["by"], signed["role"], signed["action"], signed["on_current_content"]) == \
        ("bob", "REVIEWER", "APPROVE", True)
    assert dec["status"] == "APPROVED" and dec["audit_event_ids"]
    assert not [i for i in c.get("/queue", params={"scope": "mine"}, headers=H("bob")).json()
                if i["case_id"] == case and i.get("kind") == "ncr"]  # nothing left for bob on the NCR
    events = [e["event"] for e in ok(c.get(f"/cases/{case}/timeline", headers=H("alice")), 200)]
    assert "INSPECTION_IMPORTED" in events and "AGENT_RUN" in events
    return {"case_id": case, "import_id": imp["import_id"], "exports": files}


def test_v513_integrated_scenario_in_process(tmp_path):
    from tests.test_intake_in2 import client

    out = integrated_scenario(client(tmp_path, None))
    assert out["exports"]["docx"] > 0 and out["exports"]["pdf"] > 0
