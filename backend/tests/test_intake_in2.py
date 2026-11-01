"""IN2 (spec §23.3, §24.2): the server parses, Muse proposes, the server keeps only what the source supports."""

import json

import pytest
from fastapi.testclient import TestClient

from app import docparse
from app.db import Base
from app.main import create_app
from app.model_provider import ProviderError
from tests.test_intake_in1 import DOCX_FIXTURE, PDF_FIXTURE, own_pdf, upload
from tests.v5_util import H


class Scripted:
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.seen.append({"messages": messages, "response_format": response_format})
        item = self.replies.pop(0) if self.replies else ProviderError("no scripted reply left")
        if isinstance(item, Exception):
            raise item
        return {"message": {"role": "assistant", "content": json.dumps(item)}, "usage": {}}


def f(field, value, *sources):
    return {"field": field, "value": value, "sources": [{"element_id": e, "excerpt": x} for e, x in sources]}


def extraction(pdf_id, docx_id=None):
    fields = [
        f("customer", "Hanbit Motors", ("pdf:p1:l2", "Customer: Hanbit Motors")),
        f("customer_ref", "HM-CC-2026-0417", ("pdf:p1:l3", "HM-CC-2026-0417")),
        f("part_number", "PCB-ECU-200 rev C", ("pdf:p1:l4", "PCB-ECU-200 rev C")),
        f("lot", "L02", ("pdf:p1:l12", "L02")),
        f("defective_qty", "12", ("pdf:p1:l14", "12")),
        f("qty_unit", "boards", ("pdf:p1:l15", "boards")),
        f("phenomenon", "open solder joint on U7 pin 3", ("pdf:p1:l5", "open solder joint on U7 pin 3")),
        f("reply_deadline", "Friday", ("pdf:p1:l7", "Please reply by Friday")),
        f("customer_cause_claim", "likely caused by insufficient solder paste",
          ("pdf:p1:l6", "likely caused by insufficient solder paste")),
        f("found_date", "2026-10-27", ("pdf:p1:l4", "Found: 2026-10-28")),  # a number the excerpt does not have
        f("delivery_date", "2026-10-20", ("pdf:p1:img1", "2026-10-20")),  # an image is no source for a value
        f("serial_range", "S-0201..S-0260", ("pdf:p9:l1", "S-0201..S-0260")),  # a locator that does not exist
    ]
    if docx_id:
        fields += [f("lot", "L03", ("docx:t1:r3:c1", "L03")), f("inspected_qty", "480", ("docx:t1:r3:c2", "480")),
                   f("defective_qty", "12", ("docx:t1:r3:c3", "12"))]
    return {"documents": [{"file_id": pdf_id, "classes": ["COMPLAINT"], "needs_confirmation": False}]
            + ([{"file_id": docx_id, "classes": ["SUPPLEMENT"], "needs_confirmation": False}] if docx_id else [])
            + [{"file_id": 999, "classes": ["OTHER"], "needs_confirmation": True}],
            "fields": fields,
            "links": [{"element_id": "pdf:p1:img1", "text": "U7 핀 사진, 캡션 Fig. 1과 현상 문단에 연결",
                       "related_element_ids": ["pdf:p1:l16", "pdf:p1:l5", "nope"], "ambiguous": False},
                      {"element_id": "ghost", "text": "x", "related_element_ids": [], "ambiguous": True}],
            "questions": ["LOT가 문서마다 다릅니다(L02/L03). 어느 쪽이 맞습니까?"]}


def client(tmp_path, provider):
    app = create_app(f"sqlite:///{tmp_path / 'in2.db'}", provider)
    Base.metadata.create_all(app.state.engine)
    return TestClient(app)


def analyze(c, iid, user="alice"):
    return c.post(f"/intakes/{iid}/analyze", headers=H(user))


def two_files(c):
    body = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes()), ("supp.docx", DOCX_FIXTURE.read_bytes())]).json()
    return body["intake_id"], body["files"][0]["file_id"], body["files"][1]["file_id"]


def test_every_value_is_kept_only_as_far_as_its_source_supports_it(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    iid, pdf_id, docx_id = two_files(c)
    p.replies.append(extraction(pdf_id, docx_id))
    d = analyze(c, iid).json()["draft"]
    fields = d["fields"]
    assert d["mode"] == "TEST_DOUBLE" and d["status"] == "OK" and d["prompt_version"]
    assert fields["customer_ref"]["status"] == "FOUND" and fields["customer_ref"]["sources"][0]["page"] == 1
    assert fields["lot"]["status"] == "CONFLICT" and fields["lot"]["value"] is None  # T04: shown, never merged
    assert {x["value"] for x in fields["lot"]["candidates"]} == {"L02", "L03"}
    assert fields["defective_qty"]["status"] == "FOUND" and fields["inspected_qty"]["value"] == "480"
    assert fields["reply_deadline"]["status"] == "NEEDS_CONFIRMATION"  # "Friday" needs a reference date
    assert fields["customer_cause_claim"]["kind"] == "HYPOTHESIS"  # T05: the customer's guess is not a cause
    assert fields["defective_qty"]["kind"] == "CUSTOMER_REPORTED"
    for name, why in [("found_date", "숫자 27"), ("delivery_date", "image"), ("serial_range", "없는 위치")]:
        assert fields[name]["status"] == "UNVERIFIED" and fields[name]["value"] is None
        assert why in " ".join(fields[name]["rejected"][0]["problems"]), name
    assert fields["customer_contact"]["status"] == "MISSING"
    assert [x["file_id"] for x in d["documents"]] == [pdf_id, docx_id]  # an unknown file id is dropped
    assert d["links"] == [{"element_id": "pdf:p1:img1", "text": "U7 핀 사진, 캡션 Fig. 1과 현상 문단에 연결",
                           "related_element_ids": ["pdf:p1:l16", "pdf:p1:l5"], "ambiguous": False,
                           "kind": "AI_OBSERVATION"}]
    assert [x["element_id"] for x in d["flags"]] == ["pdf:p1:l16"]  # T08: the caption's instruction is flagged
    sent = p.seen[0]
    assert sent["response_format"]["json_schema"]["name"] == "intake_extract"
    parts = sent["messages"][1]["content"]
    assert sum(x["type"] == "image_url" for x in parts) >= 3  # photos and the chart capture, as data URLs


def test_a_complaint_without_an_inspected_quantity_gets_no_rate(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    body = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes())]).json()
    p.replies.append(extraction(body["files"][0]["file_id"]))
    d = analyze(c, body["intake_id"]).json()["draft"]
    assert d["fields"]["inspected_qty"]["status"] == "MISSING"
    assert any("불량률을 계산하지 않습니다" in n for n in d["notes"])  # T03
    assert not any("rate" in k for k in d["fields"])


def test_unknown_files_never_reach_the_model(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    body = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes()), ("mine.pdf", own_pdf())]).json()
    p.replies.append(extraction(body["files"][0]["file_id"]))
    d = analyze(c, body["intake_id"]).json()["draft"]
    assert d["status"] == "PARTIAL" and [w["name"] for w in d["withheld"]] == ["mine.pdf"]
    assert "not a shipped fixture" not in json.dumps(p.seen[0]["messages"], ensure_ascii=False)
    only = upload(c, [("mine.pdf", own_pdf())]).json()
    d = analyze(c, only["intake_id"]).json()["draft"]
    assert d["mode"] == "OFFLINE" and len(p.seen) == 1  # nothing cleared for egress: no call at all


def test_no_provider_or_a_model_failure_leaves_an_empty_draft_for_manual_entry(tmp_path):
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    for path, provider, status in [(tmp_path / "a", None, "OFFLINE"),
                                   (tmp_path / "b", Scripted(ProviderError("timeout")), "FAILED")]:
        c = client(path, provider)
        iid = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes())]).json()["intake_id"]
        d = analyze(c, iid).json()["draft"]
        assert d["status"] == status and "직접 입력" in d["error"]
        assert all(v["status"] == "MISSING" for v in d["fields"].values())  # no guessed or example values


def test_a_persons_edit_is_a_new_version_with_reason_and_a_stale_base_is_refused(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    iid, pdf_id, docx_id = two_files(c)
    p.replies.append(extraction(pdf_id, docx_id))
    assert analyze(c, iid).json()["draft"]["version"] == 1
    headers = H("alice")
    body = {"base_version": 1, "changes": [
        {"field": "lot", "value": "L02", "reason": "출하 기록 확인", "element_id": "pdf:p1:l12", "excerpt": "L02"},
        {"field": "reply_deadline", "value": "2026-10-31 18:00 KST", "reason": "고객 통화로 기한 확인"}]}
    d = c.post(f"/intakes/{iid}/draft/edits", json=body, headers=headers).json()["draft"]
    assert d["version"] == 2 and d["kind"] == "USER_EDIT"
    assert d["fields"]["lot"]["status"] == "USER_SET" and d["fields"]["lot"]["edit"]["source_check"] == "원문 근거 확인"
    assert d["fields"]["reply_deadline"]["edit"]["source_check"].startswith("원문 근거 없음")
    assert d["changes"][0]["by"] == "alice" and d["changes"][0]["reason"] == "출하 기록 확인"
    assert c.post(f"/intakes/{iid}/draft/edits", json=body, headers=headers).json()["draft"]["version"] == 2  # retry
    assert c.post(f"/intakes/{iid}/draft/edits", json=body, headers=H("alice")).status_code == 409  # stale base
    assert c.get(f"/intakes/{iid}/draft", headers=H("dave")).status_code == 404  # T07
    raw = c.get(f"/intakes/{iid}/files/{pdf_id}/content", headers=H("alice")).content
    assert raw == PDF_FIXTURE.read_bytes()  # the original is never modified


def test_parser_locators_merged_cells_chart_data_duplicates_and_scans():
    els, cov, _ = docparse.parse(docparse_type(DOCX_FIXTURE), DOCX_FIXTURE.read_bytes())
    by = {e["id"]: e for e in els}
    assert by["docx:t1:r1:c1"]["span"] == 4 and by["docx:t1:r3:c2"]["text"] == "480"  # merged header row kept
    chart = by["docx:chart1"]
    assert chart["series"][0]["values"] == [2.0, 3.0, 7.0] and chart["series"][0]["total"] == 12.0
    assert chart["source"] == "CHART_CACHE" and chart["caption_id"] == "docx:p8"
    assert by["docx:img1"]["caption_id"] == "docx:p5" and by["docx:img2"]["duplicate_of"] == "docx:img1"
    assert by["docx:img1"]["sha256"] == by["docx:img2"]["sha256"] and "page" not in by["docx:img1"]  # no invented page
    assert cov["render"] == "NOT_SUPPORTED" and cov["tables"] == "OK" and cov["charts"] == "OK"
    els, cov, _ = docparse.parse("application/pdf", PDF_FIXTURE.read_bytes())
    by = {e["id"]: e for e in els}
    assert by["pdf:p1:img1"]["caption_id"] == "pdf:p1:l16" and by["pdf:p3:scan"]["status"] == "NEEDS_VISION"
    assert cov["charts"] == "IMAGE_ONLY" and cov["scan"] == "NEEDS_VISION" and cov["render"] == "OK"
    assert cov["tables"] == "PARTIAL"  # PDF tables only as text lines: said, not hidden


def docparse_type(path):
    return "application/pdf" if path.suffix == ".pdf" else "docx"


def test_render_for_layout_and_its_failure_fall_back_to_structure(tmp_path, monkeypatch):
    c = client(tmp_path, None)
    iid, pdf_id, docx_id = two_files(c)
    png = c.get(f"/intakes/{iid}/files/{pdf_id}/pages/1", headers=H("alice"))
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    assert c.get(f"/intakes/{iid}/files/{docx_id}/pages/1", headers=H("alice")).status_code == 409
    assert c.get(f"/intakes/{iid}/files/{pdf_id}/pages/9", headers=H("alice")).status_code == 404

    def broken(_data):
        raise RuntimeError("renderer crashed")
    monkeypatch.setattr(docparse, "render_document", broken)
    r = c.get(f"/intakes/{iid}/files/{pdf_id}/pages/1", headers=H("alice"))
    assert r.status_code == 422 and "구조 추출" in r.json()["detail"]
    _, cov, _ = docparse.parse("application/pdf", PDF_FIXTURE.read_bytes())
    assert cov["render"] == "FAILED" and "구조 추출" in cov["render_note"]


@pytest.mark.parametrize("who", ["dave"])
def test_parsed_images_are_only_for_the_owner(tmp_path, who):
    c = client(tmp_path, None)
    iid, pdf_id, _ = two_files(c)
    assert c.get(f"/intakes/{iid}/files/{pdf_id}/images/pdf:p1:img1", headers=H("alice")).status_code == 200
    assert c.get(f"/intakes/{iid}/files/{pdf_id}/images/pdf:p1:img1", headers=H(who)).status_code == 404
