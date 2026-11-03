"""AI-CFG-01/02 (spec v5.14 §29): an unregistered inspection XLSX goes rules first, then a structured AI proposal
over the server's table candidates, checked by the server; a person confirms the uncertain fields, the mapping is
saved with its structure, and the next file of the same structure reuses it (new values, same mapping). A changed
structure, a conflict, an out-of-range reply or a model failure goes back to review or manual mapping. TEST_DOUBLE
providers only."""

import json
import uuid

from app import inspection_layout as lay
from app.intake import FIXTURE_DIR
from app.model_provider import ProviderError
from scripts.xlsx_samples import DEMO_A, DEMO_B, book, samples, two_row
from tests.test_inspection_xlsx import upload_xlsx
from tests.test_intake_in2 import client
from tests.v5_util import H


class Mapper:
    """TEST_DOUBLE: replies with the given proposal (or raises) and keeps what it was sent."""
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.sent = reply, error, []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.sent.append(messages[-1]["content"])
        if self.error:
            raise ProviderError(self.error)
        return {"message": {"content": json.dumps(self.reply)}, "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


def reply(table, cols, unresolved=()):
    return {"candidate_id": table, "unresolved": list(unresolved),
            "fields": [{"field": f, "column": c, "reason": f"header of {c}"} for f, c in cols.items()]}


DEMO = {"lot": "A", "inspected_on": "B", "inspected_qty": "C", "defective_qty": "D"}  # D is 합격: wrong on purpose


def setup(tmp_path, provider):
    c = client(tmp_path, provider)
    assert c.post("/cases", json={"case_id": "X"}, headers=H("alice")).status_code == 201
    return c


def preview(c, iid, fid, **params):
    r = c.get(f"/intakes/{iid}/files/{fid}/inspection", params=params, headers=H("alice"))
    assert r.status_code == 200, r.text
    return r.json()


def propose(c, iid, fid):
    r = c.post(f"/intakes/{iid}/files/{fid}/inspection/proposals", headers=H("alice"))
    assert r.status_code == 201, r.text
    return r.json()


def save(c, iid, fid, table, mapping, confirmed=(), proposal_id=None, status=201):
    r = c.post(f"/intakes/{iid}/files/{fid}/inspection/mapping",
               headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex},
               json={"table": table, "mapping": mapping, "confirmed": list(confirmed), "proposal_id": proposal_id,
                     "reason": "원본 셀과 대조해 확인"})
    assert r.status_code == status, r.text
    return r.json()


def import_rows(c, iid, fid, v):
    body = {"intake_id": iid, "file_id": fid, "file_sha256": v["file_sha256"], "sheet": v["sheet"],
            "header_row": v["header_row"], "mapping": v["mapping"], "include_rows": [x["row"] for x in v["rows"]],
            "form": v["form"]["name"]}
    r = c.post("/cases/X/inspection-imports", json=body, headers={"X-User": "alice",
                                                                  "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201, r.text
    return r.json()


def test_unregistered_file_ai_proposal_person_confirms_and_the_next_file_reuses_the_mapping(tmp_path):
    p = Mapper(reply("T1", {**DEMO, "part_number": "NONE", "item": "NONE", "value": "NONE", "unit": "NONE"}))
    c = setup(tmp_path, p)
    iid, fid = upload_xlsx(c, (FIXTURE_DIR / DEMO_A).read_bytes(), DEMO_A)
    v = preview(c, iid, fid)
    assert v["layout"]["route"] == "NEEDS_AI" and v["layout"]["reasons"][0]["code"] == "REQUIRED_NOT_MAPPED"

    out = propose(c, iid, fid)
    sent = json.loads(p.sent[0])["candidates"][0]
    assert [x["header"] for x in sent["columns"]][2:5] == ["수량 / 검사", "수량 / 합격", "수량 / 불합격"]
    assert "00412" not in p.sent[0] and "480" not in p.sent[0]  # headers and types only, never cell values
    assert out["status"] == "OK" and out["proposal"]["mapping"]["defective_qty"] == "D"
    ask = {x["field"]: x for x in out["preview"]["layout"]["uncertain"]}
    assert "합격" in ask["defective_qty"]["why"]  # a count check alone cannot tell 합격 from 불합격
    assert ask["defective_qty"]["cells"][0] == {"cell": "D4", "raw": 470}
    assert {x["column"] for x in ask["defective_qty"]["context"]} == {"C", "D", "E"}  # side by side
    rows = out["preview"]["rows"]
    assert rows[0]["values"]["lot"] == "00412" and rows[0]["cells"]["lot"]["cell"] == "A4"  # leading zeros kept

    save(c, iid, fid, "T1", out["proposal"]["mapping"], proposal_id=out["proposal_id"], status=422)  # unconfirmed
    fixed = {**out["proposal"]["mapping"], "defective_qty": "E"}  # the person corrects 합격 -> 불합격
    form = save(c, iid, fid, "T1", fixed, proposal_id=out["proposal_id"])
    assert form["source"] == "CONFIRMED" and form["edits"] == 1 and form["mapping"]["defective_qty"] == "E"

    v1 = preview(c, iid, fid)
    assert v1["layout"]["route"] == "REUSED" and v1["form"]["name"] == form["name"]
    imp1 = import_rows(c, iid, fid, v1)
    assert imp1["denominator"]["included"] == 2

    iid2, fid2 = upload_xlsx(c, (FIXTURE_DIR / DEMO_B).read_bytes(), DEMO_B)
    v2 = preview(c, iid2, fid2)  # no AI call: the structure is the one a person confirmed
    assert v2["layout"]["route"] == "REUSED" and v2["mapping"] == v1["mapping"] and len(p.sent) == 1
    assert [x["values"]["lot"] for x in v2["rows"]] == ["00521", "00522", "00523"]  # its own values, not file A's
    assert [x["values"]["defective_qty"] for x in v2["rows"]] == [9, 0, 5]
    assert import_rows(c, iid2, fid2, v2)["denominator"]["included"] == 3


def test_a_changed_header_or_two_saved_mappings_go_back_to_review(tmp_path):
    c = setup(tmp_path, Mapper())
    iid, fid = upload_xlsx(c, two_row([["00412", "2026-10-27", 480, 470, 10, ""]]))
    form = save(c, iid, fid, "T1", {"lot": "A", "inspected_qty": "C", "defective_qty": "E"})
    changed = book({"검사성적": [["t"], ["LOT 번호", "검사일", "수량", None, None, "비고"],
                                [None, None, "검사", "합격", "NG 수량", None], ["00412", "2026-10-27", 480, 470, 10, ""]]},
                   {"검사성적": ["A2:A3", "B2:B3", "C2:E2", "F2:F3"]})
    iid2, fid2 = upload_xlsx(c, changed)
    v = preview(c, iid2, fid2)
    assert v["layout"]["route"] == "NEEDS_AI" and "STRUCTURE_CHANGED" in {x["code"] for x in v["layout"]["reasons"]}
    r = c.get(f"/intakes/{iid2}/files/{fid2}/inspection", params={"form": form["name"]}, headers=H("alice"))
    assert r.status_code == 422  # a saved mapping is never applied to another structure

    r = c.post(f"/intakes/{iid}/files/{fid}/inspection/mapping", headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex},
               json={"table": "T1", "mapping": {"lot": "A", "inspected_qty": "C", "defective_qty": "E"},
                     "name": "다른 이름", "reason": "중복 등록"})
    assert r.status_code == 201, r.text
    v = preview(c, iid, fid)
    assert v["layout"]["route"] == "NEEDS_AI" and v["layout"]["reasons"][0]["code"] == "REUSE_CONFLICT"


def test_multiple_tables_out_of_range_replies_and_model_failure(tmp_path):
    s = {x["name"]: x for x in samples()}
    p = Mapper(reply("T2", {"lot": "A", "inspected_qty": "B", "defective_qty": "Z"}))
    c = setup(tmp_path, p)
    iid, fid = upload_xlsx(c, s["multiple_tables"]["data"])
    assert preview(c, iid, fid)["layout"]["reasons"][0]["code"] == "MULTIPLE_TABLES"
    out = propose(c, iid, fid)
    assert out["proposal"]["table"] == "T2" and out["proposal"]["mapping"]["defective_qty"] is None
    assert {"OUT_OF_RANGE", "REQUIRED_NOT_MAPPED"} <= {i["code"] for i in out["issues"]}
    assert out["preview"]["sheet"] == "Report" and out["preview"]["header_row"] == 6
    assert [x["row"] for x in out["preview"]["rows"]] == [7, 8]  # the detail table only, not the summary

    p.reply = reply("T9", {"lot": "A"})
    assert propose(c, iid, fid)["status"] == "INVALID"
    p.reply = reply("T2", {"lot": "B", "inspected_qty": "B", "defective_qty": "C"})
    out = propose(c, iid, fid)
    assert out["proposal"]["mapping"]["lot"] is None and "DUPLICATE_MAPPING" in {i["code"] for i in out["issues"]}

    p.error = "timeout"
    out = propose(c, iid, fid)
    assert out["status"] == "FAILED" and out["preview"]["layout"]["table"] == "T1"  # manual mapping stays open
    form = save(c, iid, fid, "T2", {"lot": "A", "inspected_qty": "B", "defective_qty": "C"},
                proposal_id=out["proposal_id"])
    assert form["edits"] is None and preview(c, iid, fid)["layout"]["route"] == "REUSED"


def test_registered_form_needs_no_ai_and_protected_headers_go_masked(tmp_path):
    s = {x["name"]: x for x in samples()}
    p = Mapper(reply("T1", {"lot": "A", "inspected_qty": "B", "defective_qty": "D"}))
    c = setup(tmp_path, p)
    iid, fid = upload_xlsx(c, s["builtin_control"]["data"])
    assert preview(c, iid, fid)["layout"]["route"] == "FORM"
    iid, fid = upload_xlsx(c, book({"Data": [["Lot", "Inspected", "Accepted", "Rejected"], ["L-1", 10, 9, 1]]}))
    propose(c, iid, fid)  # not a shipped fixture: protected, so header words outside the allow list are masked
    assert "Accepted" not in p.sent[-1] and "Inspected" in p.sent[-1]


def test_table_candidates_find_merged_two_row_headers_and_skip_meta_rows():
    s = {x["name"]: x for x in samples()}
    t = lay.tables(s["merged_two_row"]["data"])[0]
    assert t["header_rows"] == [2, 3] and t["merged_header"] and t["columns"]["E"] == "수량 / 불합격"
    t = lay.tables(s["meta_rows"]["data"])[0]
    assert t["header_rows"] == [3]
    assert lay.structure_sha(lay.tables(two_row([["1", "d", 1, 1, 0, ""]]))[0]) == \
        lay.structure_sha(lay.tables(two_row([["9", "e", 5, 4, 1, "x"], ["8", "f", 2, 2, 0, ""]]))[0])
