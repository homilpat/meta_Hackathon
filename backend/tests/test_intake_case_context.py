"""One case per Agent conversation (user 2026-11-04): an intake remembers the case it was uploaded in."""

from tests.test_intake_in1 import b64, own_pdf
from tests.v5_util import H, line_client


def test_an_upload_keeps_its_case_and_only_a_case_the_person_may_open(tmp_path):
    c = line_client(tmp_path)
    files = [{"name": "a.pdf", "content_base64": b64(own_pdf())}]
    inside = c.post("/intakes", json={"files": files, "case_id": "L"}, headers=H("alice")).json()
    fresh = c.post("/intakes", json={"files": files}, headers=H("alice")).json()
    assert inside["case_id"] == "L" and fresh["case_id"] is None
    assert {x["intake_id"]: x["case_id"] for x in c.get("/intakes", headers=H("alice")).json()} == {
        inside["intake_id"]: "L", fresh["intake_id"]: None}
    c.post("/cases", json={"case_id": "Z"}, headers=H("bob"))  # bob's case; alice is not on it
    # refused, and as "not found": the case guard never confirms a case the person is not on
    assert c.post("/intakes", json={"files": files, "case_id": "Z"}, headers=H("alice")).status_code == 404
