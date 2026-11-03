"""ASK-RESUME-01..03 (spec v5.15 §30.2): LOT 0007 has 3 defective (customer-reported) and no inspected quantity,
so its defect rate is held and the server asks. A person answers 120 directly or points at the original cell
holding 120; both give 2.5 % through a server calculation id, with different source types. Invalid quantities,
scope mismatch, a changed source, permission, duplicate answers and resumes are checked. TEST_DOUBLE only."""

import json
import uuid

import pytest
from sqlalchemy import update

from app.db import IntakeFile
from app.model_provider import ProviderError
from scripts.xlsx_samples import book
from tests.test_intake_in1 import own_pdf, upload
from tests.test_intake_in2 import client
from tests.v5_util import H

SHEET = [["LOT", "검사일", "검사 수량", "불량 수량"], ["0007", "2026-10-27", 120, 3], ["0008", "2026-10-28", 200, 1],
         ["0007", "2026-11-02", 90, 1]]


class Pointer:
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self):
        self.sent = []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        if not isinstance(messages[-1]["content"], str):  # the intake analysis: leave it to the person
            raise ProviderError("not this test's call")
        self.sent.append(messages[-1]["content"])
        if response_format["json_schema"]["name"] == "input_question":  # the model writes the question
            need = json.loads(messages[-1]["content"])
            return {"message": {"content": json.dumps({"question": f"LOT {need['lot']}의 {need['missing_field']}를 "
                                                                    "숫자나 원본 셀 위치로 알려 주세요."})}, "usage": {}}
        src = json.loads(messages[-1]["content"])["sources"]
        col = next(c["id"] for s in src for t in s["tables"] for c in t["columns"] if "검사 수량" in c["header"])
        return {"message": {"content": json.dumps({"candidates": [
            {"source_id": col, "reason": "검사 수량 column"}, {"source_id": "F99:T1:Z", "reason": "made up"}]})},
            "usage": {}}


def K(user="alice"):
    return {"X-User": user, "Idempotency-Key": uuid.uuid4().hex}


@pytest.fixture
def held(tmp_path):
    p = Pointer()
    c = client(tmp_path, p)
    up = upload(c, [("complaint.pdf", own_pdf()), ("inspection.xlsx", book({"검사": SHEET}))]).json()
    iid, xlsx = up["intake_id"], up["files"][1]["file_id"]
    c.post(f"/intakes/{iid}/analyze", headers=H("alice"))
    r = c.post(f"/intakes/{iid}/draft/edits", headers=H("alice"), json={"base_version": 1, "changes": [
        {"field": "lot", "value": "0007", "reason": "고객 문서"}, {"field": "defective_qty", "value": "3",
                                                                  "reason": "고객 문서"}]})
    assert r.status_code == 201, r.text
    case = c.post(f"/intakes/{iid}/confirm", headers=K(), json={"base_version": 2, "action": "NEW_CASE"}).json()["case_id"]
    r = c.post(f"/cases/{case}/calculations/held", headers=K(), json={"lot": "0007", "period": "2026-10"})
    assert r.status_code == 201, r.text
    return c, p, case, r.json(), xlsx


def answer(c, rid, body, user="alice", key=None, status=(200, 201)):
    r = c.post(f"/input-requests/{rid}/answers", json=body, headers={"X-User": user,
                                                                       "Idempotency-Key": key or uuid.uuid4().hex})
    assert r.status_code in ((status,) if isinstance(status, int) else status), r.text
    return r.json()


def resume(c, rid, user="alice", key=None, status=(200, 201)):
    r = c.post(f"/input-requests/{rid}/resume", headers={"X-User": user, "Idempotency-Key": key or uuid.uuid4().hex})
    assert r.status_code in ((status,) if isinstance(status, int) else status), r.text
    return r.json()


def test_held_then_a_number_typed_by_the_person_gives_2_5_percent(held):
    c, _, case, req, _ = held
    assert req["status"] == "NEEDS_INPUT" and req["missing_field"] == "inspected_qty" and req["lot"] == "0007"
    assert req["held"]["have"]["defective_qty"] and "LOT 0007" in req["question"]
    rid = req["request_id"]
    again = c.post(f"/cases/{case}/calculations/held", headers=K(), json={"lot": "0007"}).json()
    assert again["request_id"] == rid  # one open request, not a second one

    for bad, why in ((0, "0 이하"), (2, "보다 작습니다"), (120.5, "정수")):
        assert why in answer(c, rid, {"kind": "USER_ENTERED", "value": bad})["rejected"]
    assert "단위" in answer(c, rid, {"kind": "USER_ENTERED", "value": 120, "unit": "kg"})["rejected"]
    answer(c, rid, {"kind": "USER_ENTERED", "value": 120}, user="bob", status=403)  # a reviewer cannot answer
    answer(c, rid, {"kind": "USER_ENTERED", "value": 120}, user="dave", status=403)  # not on the case

    a = answer(c, rid, {"kind": "USER_ENTERED", "value": 120, "unit": "EA"})
    assert a["status"] == "ANSWERED" and a["evidence_id"] == f"EV-IR{rid}"
    dup = answer(c, rid, {"kind": "USER_ENTERED", "value": 120, "unit": "EA"})
    assert dup["duplicate"] and [e["kind"] for e in dup["events"]].count("ANSWER_ACCEPTED") == 1
    answer(c, rid, {"kind": "USER_ENTERED", "value": 130}, status=409)  # a different value conflicts

    done = resume(c, rid)
    res = done["result"]
    assert done["status"] == "RESUMED" and res["rate_percent"] == 2.5
    assert res["calculation"]["calculation_id"].startswith("CALC-") and res["calculation"]["operation"] == "quotient"
    src = {i["field"]: i["source_type"] for i in res["inputs"]}
    assert src == {"defective_qty": "CUSTOMER_REPORTED", "inspected_qty": "USER_ENTERED"}
    assert resume(c, rid)["result"]["calculation"]["calculation_id"] == res["calculation"]["calculation_id"]
    ev = c.get(f"/cases/{case}/timeline", headers=H("alice")).json()
    assert [e["event"] for e in ev].count("INPUT_RESUMED") == 1


def test_the_original_cell_gives_the_same_rate_with_a_different_source_type(held):
    c, p, _, req, xlsx = held
    rid = req["request_id"]
    s = c.post(f"/input-requests/{rid}/suggestions", headers=H("alice")).json()
    assert [x["column"] for x in s["candidates"]] == ["C"] and s["candidates"][0]["sheet"] == "검사"  # made-up id dropped
    assert "120" not in p.sent[-1] and "0008" not in p.sent[-1]  # headers only, no cell values

    assert "LOT은 0008" in answer(c, rid, {"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "C3"})["rejected"]
    assert "불량 수량" in answer(c, rid, {"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "D2"})["rejected"]
    out = answer(c, rid, {"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "C4"})  # LOT 0007, November
    assert "B4의 검사일 2026-11-02은 기간 2026-10 밖" in out["rejected"]
    a = answer(c, rid, {"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "C2"})
    loc = next(e for e in a["events"] if e["kind"] == "ANSWER_ACCEPTED")["payload"]["locator"]
    assert (loc["cell"], loc["raw"], loc["row_lot"], loc["row_date"]) == ("C2", 120, "0007", "2026-10-27")
    assert len(loc["file_sha256"]) == 64
    res = resume(c, rid)["result"]
    assert res["rate_percent"] == 2.5
    assert {i["field"]: i["source_type"] for i in res["inputs"]}["inspected_qty"] == "SOURCE_CELL"


def test_a_changed_original_holds_the_resume(held):
    c, _, _, req, xlsx = held
    rid = req["request_id"]
    answer(c, rid, {"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "C2"})
    with c.app.state.engine.begin() as conn:  # originals are append-only; simulate a store replaced behind its back
        conn.exec_driver_sql("DROP TRIGGER intake_files_no_update")
        conn.execute(update(IntakeFile).where(IntakeFile.id == xlsx).values(
            content=book({"검사": [["LOT", "검사일", "검사 수량", "불량 수량"], ["0007", "2026-10-27", 100, 3]]})))
    out = resume(c, rid)
    assert out["status"] == "ANSWERED" and "원본" in out["held_reason"]
    assert "RESUME_HELD" in [e["kind"] for e in out["events"]]


def test_period_needs_a_date_on_the_row_and_must_match():
    from app.input_requests import in_period

    assert in_period("2026-10-27", "2026-10") and not in_period("2026-11-02", "2026-10")
    assert in_period("2026-10-27", "2026-10-01..2026-10-31") and not in_period("2026-11-01", "2026-10-01..2026-10-31")
    assert in_period("2026-11-15", "2026-10..2026-11") and not in_period("2026-12-01", "2026-10..2026-11")


def test_the_question_is_the_models_and_the_server_checks_it_names_the_lot_and_value():
    from app.input_requests import write_question

    class Q:
        def __init__(self, *answers):
            self.answers, self.seen = list(answers), []

        def chat(self, messages, tools, response_format=None, reasoning_effort=None):
            self.seen.append(json.loads(messages[-1]["content"]))
            return {"message": {"content": json.dumps({"question": self.answers.pop(0)})}, "usage": {}}

    need = {"lot": "0007", "missing_field": "검사 수량", "period": None}
    q = Q("검사 수량을 알려 주세요.", "LOT 0007의 검사 수량을 숫자나 원본 셀 위치로 알려 주세요.")
    assert write_question(q, need) == "LOT 0007의 검사 수량을 숫자나 원본 셀 위치로 알려 주세요."
    assert q.seen[1]["server_check"] == ["질문에 0007이(가) 없습니다"]  # what was wrong went back to the model
    assert write_question(None, need) == ""  # no model: no server-written question (the screen shows a notice)
