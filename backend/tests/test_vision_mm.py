"""MM (spec §24): the vision tool contract is checked and recorded but answers NOT_CONFIGURED; a chart picture's
numbers never become a value; customer report, AI reading, vision result and human inspection stay apart."""

import pytest

from app import vision
from tests.test_intake_in2 import Scripted, analyze, client, extraction, f, two_files
from tests.test_intake_in3 import confirm, resolve
from tests.v5_util import H


def req(c, user="alice", **body):
    return c.post("/vision/requests", json={"analysis_type": "DEFECT_DETECTION", **body}, headers=H(user))


@pytest.fixture
def env(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    iid, pdf_id, docx_id = two_files(c)
    p.replies.append(extraction(pdf_id, docx_id))
    analyze(c, iid)
    return c, p, iid, pdf_id, docx_id


def test_a_vision_request_is_recorded_with_its_input_hashes_and_answered_not_configured(env):
    c, _, iid, pdf_id, _ = env
    status = c.get("/vision/status", headers=H("alice")).json()
    assert status["status"] == "NOT_CONFIGURED" and status["configured"] == []
    assert set(status["source_types"]) == {"CUSTOMER_REPORTED", "AI_OBSERVATION", "VISION_RESULT", "HUMAN_INSPECTION"}
    r = req(c, intake_id=iid, file_id=pdf_id, element_id="pdf:p1:img1", reported_phenomenon="고객이 균열로 보고")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["status"] == "NOT_CONFIGURED" and out["result"] is None and out["result_type"] is None
    assert out["reported_as"] == "CUSTOMER_REPORTED" and "NOT_CONFIGURED" in out["message"]
    assert len(out["image_sha256"]) == 64 and out["page"] == 1 and out["file_sha256"]
    assert c.get("/vision/requests", params={"intake_id": iid}, headers=H("alice")).json() == [out]


def test_requests_need_an_image_element_and_access(env):
    c, _, iid, pdf_id, docx_id = env
    assert req(c, intake_id=iid, file_id=pdf_id, element_id="pdf:p1:l5").status_code == 422  # text, not an image
    assert req(c, intake_id=iid, file_id=pdf_id, element_id="pdf:p9:img1").status_code == 422
    assert req(c, user="dave", intake_id=iid, file_id=pdf_id, element_id="pdf:p1:img1").status_code == 404
    assert req(c, file_id=pdf_id, element_id="pdf:p1:img1").status_code == 422  # neither intake nor case
    assert req(c, intake_id=iid, case_id="L", file_id=pdf_id, element_id="pdf:p1:img1").status_code == 422
    case = confirm(c, iid, resolve(c, iid, 1)).json()["case_id"]
    assert req(c, case_id=case, file_id=docx_id, element_id="docx:img1").json()["case_id"] == case
    assert req(c, user="dave", case_id=case, file_id=docx_id, element_id="docx:img1").status_code == 403


def test_a_connected_adapter_must_return_the_contract_for_the_same_image(env, monkeypatch):
    c, _, iid, pdf_id, _ = env
    seen = {}

    def adapter(blob, request):  # a contract check only: never a real detection, never shown as one
        seen["sha"] = __import__("hashlib").sha256(blob).hexdigest()
        return vision.VisionResult(analysis_id="t1", input_sha256=seen["sha"], model="contract-test-double",
                                   model_version="0", settings={}, coordinate_system="IMAGE_PIXELS_TOP_LEFT",
                                   preprocessing=[], regions=[], status="OK", limitations=["test double"])
    monkeypatch.setitem(vision.ADAPTERS, "SEGMENTATION", adapter)
    out = req(c, intake_id=iid, file_id=pdf_id, element_id="pdf:p1:img1", analysis_type="SEGMENTATION").json()
    assert out["status"] == "OK" and out["result_type"] == "VISION_RESULT"
    assert vision.usable(out["result"], out["image_sha256"]) and not vision.usable(out["result"], "0" * 64)

    def wrong_image(blob, request):
        return adapter(blob, request).model_copy(update={"input_sha256": "f" * 64})
    monkeypatch.setitem(vision.ADAPTERS, "MEASUREMENT", wrong_image)
    assert req(c, intake_id=iid, file_id=pdf_id, element_id="pdf:p1:img1",
               analysis_type="MEASUREMENT").status_code == 502  # a result for another image is not stored


def test_a_number_read_off_a_chart_picture_is_never_a_value_but_chart_data_is(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    iid, _, _ = two_files(c)
    p.replies.append({"documents": [], "links": [{"element_id": "pdf:p2:img1", "kind": "x",
                                                  "text": "흐린 막대 차트, 눈금 불명", "related_element_ids": ["pdf:p2:l2"],
                                                  "ambiguous": True}], "questions": [],
                      "fields": [f("defective_qty", "7", ("pdf:p2:img1", "7")),  # read off the blurred picture
                                 f("inspected_qty", "7", ("docx:chart1", "W43 7"))]})  # in the chart's own data
    d = analyze(c, iid).json()["draft"]
    assert d["fields"]["defective_qty"]["status"] == "UNVERIFIED"
    assert d["fields"]["inspected_qty"]["sources"][0]["element_id"] == "docx:chart1"
    assert d["links"][0]["kind"] == "AI_OBSERVATION" and d["links"][0]["ambiguous"] is True
    files = c.get(f"/intakes/{iid}/draft", headers=H("alice")).json()["files"]
    assert files[0]["coverage"]["charts"] == "IMAGE_ONLY" and files[1]["coverage"]["charts"] == "OK"
