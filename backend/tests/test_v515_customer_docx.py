"""DOC-OUT-01..04 (spec v5.15 §30.1): customer DOCX forms registered, mapped by a checked AI proposal a person
confirms, previewed with the case's own values, exported as draft or final, reused for another case and sent back
to review when the form changes. TEST_DOUBLE providers only."""

import base64
import io
import json
import uuid

import docx
import pytest

from app.intake import FIXTURE_DIR
from scripts.docx_samples import FORMATS_C, FORMS, GOLD_C, gold_paragraph, gold_table
from tests.test_c_e2e import success
from tests.test_intake_in1 import own_pdf, upload
from tests.v5_util import H, confirmed_cause, line_client


class Mapper:
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self):
        self.reply, self.sent = None, []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.sent.append(messages[-1]["content"])
        return {"message": {"content": json.dumps(self.reply)}, "usage": {}}


def reply(gold: dict, unresolved=(), formats=None):
    return {"slots": [{"slot_id": s, "field_id": f or "NONE", "format": (formats or {}).get(s, "AS_IS"),
                       "reason": "label"} for s, f in gold.items()], "unresolved": list(unresolved)}


def K(user="alice"):
    return {"X-User": user, "Idempotency-Key": uuid.uuid4().hex}


def register(c, fname, user="alice", status=(200, 201)):
    cust, name, _ = FORMS[fname]
    r = c.post("/customer-templates", headers=K(user), json={
        "customer": cust, "name": name, "reason": "고객 양식 수령",
        "content_base64": base64.b64encode((FIXTURE_DIR / fname).read_bytes()).decode()})
    assert r.status_code in ((status,) if isinstance(status, int) else status), r.text
    return r.json()


def propose(c, tid):
    r = c.post(f"/customer-templates/{tid}/proposals", headers=H("alice"))
    assert r.status_code == 201, r.text
    return r.json()


def confirm(c, tid, mapping, proposal_id=None, required=(), status=201, formats=None):
    r = c.post(f"/customer-templates/{tid}/mapping", headers=K(), json={
        "mapping": mapping, "required": list(required), "proposal_id": proposal_id, "reason": "원본 칸과 출처 대조",
        "formats": formats or {}})
    assert r.status_code == status, r.text
    return r.json()


def text(data: bytes) -> str:
    d = docx.Document(io.BytesIO(data))
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])


@pytest.fixture(scope="module")
def closed(tmp_path_factory):
    p = Mapper()
    c = line_client(tmp_path_factory.mktemp("v515docx"), provider=p)
    success(c)  # case L closed the legitimate way: approved NCR/containment/RCA, a confirmed occurrence cause
    confirmed_cause(c, text="AOI program did not flag low-volume joints on L02", category="METHOD",
                    cause_type="NON_DETECTION")  # and the escape cause, confirmed the legitimate way
    yield c, p
    c.app_ref.state.engine.dispose()


def test_two_customer_forms_filled_from_the_same_case_with_proposal_preview_and_final(closed):
    c, p = closed
    a = register(c, "customer_form_A_8d_table.docx")
    assert a["route"] == "NEEDS_REVIEW" and len(a["slots"]) == 8 and a["sha256"] and a["data_origin"] == "SYNTHETIC"
    assert register(c, "customer_form_A_8d_table.docx")["template_id"] == a["template_id"]  # same file, same version
    assert register(c, "customer_form_A_8d_table.docx", user="bob", status=403)

    p.reply = reply({**gold_table(), "T0.R6.C1": "d4.occurrence_cause"})  # escape slot given the occurrence cause
    out = propose(c, a["template_id"])
    sent = json.loads(p.sent[-1])
    assert "case.id" in {f["id"] for f in sent["fields"]} and "DEFAULT" not in p.sent[-1]  # no case values
    assert out["status"] == "OK" and out["proposal"]["mapping"]["T0.R6.C1"] == "d4.occurrence_cause"
    fixed = {**out["proposal"]["mapping"], "T0.R6.C1": "d4.escape_cause"}  # the person keeps the two causes apart
    m = confirm(c, a["template_id"], fixed, out["proposal_id"])
    assert m["edits"] == 1 and set(m["required"]) >= {"T0.R0.C1", "T0.R5.C1", "T0.R6.C1"}

    v = c.get(f"/cases/L/customer-templates/{a['template_id']}/preview", headers=H("alice")).json()
    by = {s["id"]: s for s in v["slots"]}
    assert by["T0.R1.C1"]["value"] == "L" and by["T0.R0.C1"]["value"] == "DEFAULT"
    assert by["T0.R5.C1"]["source"].startswith("confirmed cause") and by["T0.R6.C1"]["field"] == "d4.escape_cause"
    assert by["T0.R5.C1"]["value"] != by["T0.R6.C1"]["value"]  # occurrence and escape are different values
    assert not v["final_blocked_by"], v["final_blocked_by"]
    r = c.get(f"/cases/L/customer-templates/{a['template_id']}/export", params={"mode": "final"}, headers=H("alice"))
    assert r.status_code == 200, r.text
    assert r.headers["x-mapping-version"] == "1" and r.headers["x-case-data-version"] == v["case_data_version"]
    body = text(r.content)
    assert by["T0.R5.C1"]["value"] in body and "작성 필요" not in body

    b = register(c, "customer_form_B_reply_paragraph.docx")
    p.reply = reply(gold_paragraph(), unresolved=["P6"])  # 비고: ambiguous, left unresolved
    out = propose(c, b["template_id"])
    assert out["proposal"]["mapping"]["P6"] is None and "P6" in out["proposal"]["unresolved"]
    confirm(c, b["template_id"], out["proposal"]["mapping"], out["proposal_id"])
    r = c.get(f"/cases/L/customer-templates/{b['template_id']}/export", params={"mode": "final"}, headers=H("alice"))
    assert r.status_code == 200, r.text
    assert f"발생 원인: {by['T0.R5.C1']['value']}" in text(r.content)
    log = c.get("/cases/L/customer-exports", headers=H("alice")).json()
    assert [e["mode"] for e in log] == ["final", "final"] and all(e["file_sha256"] for e in log)


def test_reuse_for_another_case_form_change_wrong_ids_and_access(closed):
    c, _ = closed
    a = register(c, "customer_form_A_8d_table.docx")
    if a["route"] != "CONFIRMED":
        confirm(c, a["template_id"], gold_table())
    up = upload(c, [("customer.pdf", own_pdf())]).json()
    iid = up["intake_id"]
    c.post(f"/intakes/{iid}/analyze", headers=H("alice"))
    c.post(f"/intakes/{iid}/draft/edits", headers=H("alice"), json={"base_version": 1, "changes": [
        {"field": "customer", "value": "DEFAULT", "reason": "고객 확인"},
        {"field": "lot", "value": "LOT-NEW-42", "reason": "고객 확인"}]})
    r = c.post(f"/intakes/{iid}/confirm", headers=K(), json={"base_version": 2, "action": "NEW_CASE"})
    assert r.status_code in (200, 201), r.text
    new = r.json()["case_id"]
    v = c.get(f"/cases/{new}/customer-templates/{a['template_id']}/preview", headers=H("alice")).json()
    by = {s["id"]: s for s in v["slots"]}
    assert by["T0.R1.C1"]["value"] == new and by["T0.R2.C1"]["value"] == "LOT-NEW-42"  # the new case's own values
    assert by["T0.R5.C1"]["status"] == "MISSING" and by["T0.R5.C1"]["shown"] == "작성 필요"
    assert {b["code"] for b in v["final_blocked_by"]} == {"REQUIRED_MISSING"}
    draft = c.get(f"/cases/{new}/customer-templates/{a['template_id']}/export", headers=H("alice"))
    assert draft.status_code == 200 and "작성 필요" in text(draft.content) and "LOT-NEW-42" in text(draft.content)
    final = c.get(f"/cases/{new}/customer-templates/{a['template_id']}/export", params={"mode": "final"},
                  headers=H("alice"))
    assert final.status_code == 409 and "제출 필수" in final.text

    v2 = register(c, "customer_form_A_8d_table_v2.docx")  # a row added: the old mapping does not carry over
    assert v2["version"] == a["version"] + 1 and v2["route"] == "NEEDS_REVIEW" and v2["mapping"] is None
    r = c.get(f"/cases/L/customer-templates/{v2['template_id']}/export", params={"mode": "final"}, headers=H("alice"))
    assert r.status_code == 409 and "재검토" in r.text
    confirm(c, a["template_id"], {"T9.R9.C9": "case.id"}, status=422)  # not a slot of this form
    confirm(c, a["template_id"], {"T0.R0.C1": "case.secret"}, status=422)  # not an allowed field

    other = register(c, "customer_form_OTHER_8d.docx")
    assert c.get(f"/cases/L/customer-templates/{other['template_id']}/preview", headers=H("alice")).status_code == 403
    assert c.get(f"/cases/{new}/customer-templates/{a['template_id']}/preview", headers=H("dave")).status_code == 403


def test_unapproved_data_shows_in_the_draft_but_blocks_the_final(tmp_path):
    p = Mapper()
    c = line_client(tmp_path, provider=p)
    a = register(c, "customer_form_A_8d_table.docx")
    confirm(c, a["template_id"], gold_table(), required=["T0.R1.C1"])
    r = c.post("/cases/L/ncr", json={}, headers=H("alice"))  # an NCR draft: not approved
    assert r.status_code == 201, r.text
    v = c.get(f"/cases/L/customer-templates/{a['template_id']}/preview", headers=H("alice")).json()
    d2 = next(s for s in v["slots"] if s["field"] == "d2.problem")
    assert d2["status"] == "UNAPPROVED" and "DRAFT" in d2["source"]
    assert "NOT_APPROVED" in {b["code"] for b in v["final_blocked_by"]}
    r = c.get(f"/cases/L/customer-templates/{a['template_id']}/export", params={"mode": "final"}, headers=H("alice"))
    assert r.status_code == 409 and "승인되지 않은" in r.text


def test_controls_text_boxes_maybe_blanks_and_a_date_format_on_a_real_style_form(closed):
    c, p = closed
    t = register(c, "customer_form_C_controls.docx")
    kinds = {x["id"]: (x["kind"], x.get("certain", True)) for x in t["slots"]}
    assert kinds == {"T0.R0.C1": ("cell", True), "T0.R1.C1": ("cell", True), "T0.R2.C1": ("cell", True),
                     "T0.R3.C1": ("cell", False), "S0": ("control", True), "X0.P0": ("textbox", True)}
    p.reply = reply(GOLD_C, formats=FORMATS_C)
    out = propose(c, t["template_id"])
    sent = json.loads(p.sent[-1])
    assert {x["id"]: x["certain"] for x in sent["slots"]}["T0.R3.C1"] is False and "DATE_DOT" in sent["formats"]
    assert out["proposal"]["formats"]["T0.R1.C1"] == "DATE_DOT"
    confirm(c, t["template_id"], {"T0.R0.C1": "case.customer"}, formats={"T0.R0.C1": "DATE_DOT"})  # no date in it
    v = c.get(f"/cases/L/customer-templates/{t['template_id']}/preview", headers=H("alice")).json()
    assert "FORMAT_UNCONVERTIBLE" in {b["code"] for b in v["final_blocked_by"]}
    confirm(c, t["template_id"], {k: f for k, f in GOLD_C.items()}, out["proposal_id"],
            formats=out["proposal"]["formats"])
    v = c.get(f"/cases/L/customer-templates/{t['template_id']}/preview", headers=H("alice")).json()
    by = {x["id"]: x for x in v["slots"]}
    day = by["T0.R1.C1"]["value"]
    assert by["T0.R1.C1"]["shown"] == day.replace("-", ".") and by["T0.R1.C1"]["converted"]  # original kept beside
    assert by["T0.R3.C1"]["status"] == "UNMAPPED" and not v["final_blocked_by"], v["final_blocked_by"]
    r = c.get(f"/cases/L/customer-templates/{t['template_id']}/export", params={"mode": "final"}, headers=H("alice"))
    assert r.status_code == 200, r.text
    from app.customer_docx import text_of
    body = text_of(r.content)
    assert day.replace("-", ".") in body and by["S0"]["value"] in body and by["X0.P0"]["value"] in body
    assert "N/A" in body and "Click or tap here" not in body  # the unmapped maybe-blank keeps the customer's text
    confirm(c, t["template_id"], {"T0.R0.C1": "case.customer"}, formats={"T0.R0.C1": "ROMAN"}, status=422)
