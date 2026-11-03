"""XLS-IN-01..06 (spec v5.12 §28): one synthetic inspection-result form, real XLSX bytes. Preview and checks,
a person's confirmation (idempotent, versioned), evidence with locators, and reconciliation with the customer's
documents. TEST_DOUBLE providers only; formulas are never executed."""

import base64
import io
import uuid

import openpyxl

from tests.test_intake_in3 import confirm, drafted, resolve
from tests.v5_util import H

HEAD = ["품번", "LOT", "검사일", "검사 수량", "불량 수량", "단위"]


def workbook(rows, head=HEAD, formats=None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "검사결과"
    ws.append(["SYNTHETIC 검사 결과 (참조 양식 v1)"])  # a title row above the header
    ws.append(head)
    for r in rows:
        ws.append(r)
    for ref, fmt in (formats or {}).items():
        ws[ref].number_format = fmt
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def upload_xlsx(c, data, name="inspection.xlsx", user="alice"):
    r = c.post("/intakes", headers={"X-User": user, "Idempotency-Key": uuid.uuid4().hex},
               json={"files": [{"name": name, "content_base64": base64.b64encode(data).decode()}]})
    assert r.status_code == 201, r.text
    return r.json()["intake_id"], r.json()["files"][0]["file_id"]


def preview(c, iid, fid, user="alice", **params):
    r = c.get(f"/intakes/{iid}/files/{fid}/inspection", params=params, headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def body(view, iid, fid, include=None, exclude=None, mapping=None):
    rows = [x["row"] for x in view["rows"]]
    inc = rows if include is None else include
    return {"intake_id": iid, "file_id": fid, "file_sha256": view["file_sha256"], "sheet": view["sheet"],
            "header_row": view["header_row"], "mapping": mapping or view["mapping"], "include_rows": inc,
            "exclude": exclude or {}}


def codes(view, row) -> set[str]:
    return {i["code"] for x in view["rows"] if x["row"] == row for i in x["issues"]}


def case_with_customer_lot(tmp_path):
    """A case confirmed from the customer complaint: LOT L02, 12 defective boards (CUSTOMER_REPORTED)."""
    c, iid = drafted(tmp_path)
    case = confirm(c, iid, resolve(c, iid, 1)).json()["case_id"]
    return c, case


def test_preview_suggests_the_mapping_finds_the_header_and_keeps_raw_values(tmp_path):
    c, _ = case_with_customer_lot(tmp_path)
    iid, fid = upload_xlsx(c, workbook([["PCB-ECU-200", "L02", "2026-10-27", 480, 12, "보드"]]))
    v = preview(c, iid, fid)
    assert v["header_row"] == 2 and v["sheet"] == "검사결과" and v["mapping"]["lot"] == "B"
    assert v["mapping"]["defective_qty"] == "E" and v["rows"][0]["values"] == {
        "part_number": "PCB-ECU-200", "lot": "L02", "inspected_on": "2026-10-27", "inspected_qty": 480,
        "defective_qty": 12, "unit": "보드"}
    assert v["rows"][0]["cells"]["lot"]["cell"] == "B3" and v["mapping_version"]


def test_confirmation_is_idempotent_versioned_and_becomes_located_evidence(tmp_path):
    c, case = case_with_customer_lot(tmp_path)
    iid, fid = upload_xlsx(c, workbook([["P", "L02", "2026-10-27", 480, 12, "보드"],
                                        ["P", "L03", "2026-10-27", 300, 0, "보드"]]))
    v = preview(c, iid, fid)
    first = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid), headers=H("alice"))
    assert first.status_code == 201, first.text
    again = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid), headers=H("alice"))
    assert again.status_code == 200 and again.json()["import_id"] == first.json()["import_id"]  # no second import
    second = c.post(f"/cases/{case}/inspection-imports", headers=H("alice"),
                    json=body(v, iid, fid, include=[3], exclude={"4": "L03은 이번 사건 범위 아님"})).json()
    assert second["version"] == 2 and second["supersedes_id"] == first.json()["import_id"]
    assert second["denominator"] == {"included": 1, "excluded": 1}
    ev = {e["evidence_id"] for e in c.get(f"/cases/{case}/evidence", headers=H("alice")).json()}
    assert set(second["evidence_ids"]) <= ev


def test_wrong_mapping_unexplained_rows_and_blocked_rows_are_refused(tmp_path):
    c, case = case_with_customer_lot(tmp_path)
    iid, fid = upload_xlsx(c, workbook([["P", "L02", "2026-10-27", 480, None, "보드"],
                                        ["P", "L02", "2026-10-28", 10, 12, "보드"]]))
    v = preview(c, iid, fid)
    assert "MISSING" in codes(v, 3) and "DEFECTIVE_EXCEEDS_INSPECTED" in codes(v, 4)  # never 0-filled
    bad_map = {**v["mapping"], "lot": None}
    r = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid, mapping=bad_map), headers=H("alice"))
    assert r.status_code == 422 and "필수 열" in r.json()["detail"]
    r = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid, include=[3]), headers=H("alice"))
    assert r.status_code == 422 and "포함도 제외" in r.json()["detail"]  # row 4 unexplained
    r = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid), headers=H("alice"))
    assert r.status_code == 422 and "BLOCK" in r.json()["detail"]


def test_leading_zeros_dates_duplicates_units_and_uncached_formulas_are_shown_not_guessed(tmp_path):
    c, _ = case_with_customer_lot(tmp_path)
    rows = [["P", 42, "03/04/2026", 100, 1, "보드"], ["P", 42, "03/04/2026", 100, 1, "pcs"],
            ["P", "00042", "2026-10-27", 100, 1, "보드"], ["P", 7, "2026-10-27", "=D6*1", 0, "보드"],
            ["P", 9, "2026-10-27", "1,200", 3, "보드"]]
    iid, fid = upload_xlsx(c, workbook(rows, formats={"B6": "00000"}))
    v = preview(c, iid, fid)
    by = {x["row"]: x for x in v["rows"]}
    assert by[3]["values"]["lot"] == "42" and "LEADING_ZERO_UNKNOWN" in codes(v, 3)  # not restored
    assert by[5]["values"]["lot"] == "00042"  # stored as text: kept
    assert by[6]["values"]["lot"] == "00007" and "LEADING_ZERO_FROM_FORMAT" in codes(v, 6)
    assert by[3]["values"]["inspected_on"] is None and "DATE_AMBIGUOUS" in codes(v, 3)
    assert "DUPLICATE_CANDIDATE" in codes(v, 4) and len(v["rows"]) == 5  # shown, never dropped
    assert "UNIT_MIXED" in codes(v, 3)
    assert "FORMULA_NO_CACHE" in codes(v, 6)  # openpyxl saves no cached value: never computed here
    assert by[7]["values"]["inspected_qty"] == 1200 and "NUMBER_AS_TEXT" in codes(v, 7)


def test_reconciliation_compares_only_what_a_person_said_is_comparable(tmp_path):
    c, case = case_with_customer_lot(tmp_path)
    iid, fid = upload_xlsx(c, workbook([["P", "L02", "2026-10-27", 480, 11, "보드"]]))
    v = preview(c, iid, fid)
    imp = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid), headers=H("alice")).json()
    rec = c.get(f"/cases/{case}/inspection-imports/{imp['import_id']}/reconciliation", headers=H("alice")).json()
    items = {i["field"]: i for i in rec["items"]}
    assert items["lot"]["status"] == "MATCH" and items["lot"]["customer"][0]["element_id"]  # both locators
    assert items["lot"]["inspection"][0]["cells"]["lot"] == "B3"
    assert items["defective_qty"]["status"] == "NOT_COMPARABLE"  # same meaning not yet confirmed
    rec = c.get(f"/cases/{case}/inspection-imports/{imp['import_id']}/reconciliation",
                params={"comparable": "defective_qty"}, headers=H("alice")).json()
    d = next(i for i in rec["items"] if i["field"] == "defective_qty")
    assert d["status"] == "MISMATCH" and d["inspection_value"] == 11 and d["calculation_id"].startswith("CALC-")
    assert d["customer"][0]["value"] in ("12", 12)  # the customer's number stays the customer's


def test_a_broken_file_is_refused_with_a_reason_and_another_case_sees_nothing(tmp_path):
    c, case = case_with_customer_lot(tmp_path)
    broken = c.post("/intakes", headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex},
                    json={"files": [{"name": "x.xlsx", "content_base64": base64.b64encode(
                        b"PK\x03\x04" + b"\0" * 64).decode()}]})
    assert broken.status_code in (201, 422)
    if broken.status_code == 201:  # accepted as an unknown file: the inspection reader refuses it
        f = broken.json()["files"][0]
        r = c.get(f"/intakes/{broken.json()['intake_id']}/files/{f['file_id']}/inspection", headers=H("alice"))
        assert r.status_code == 422
    iid, fid = upload_xlsx(c, workbook([["P", "L02", "2026-10-27", 480, 12, "보드"]]))
    v = preview(c, iid, fid)
    imp = c.post(f"/cases/{case}/inspection-imports", json=body(v, iid, fid), headers=H("alice")).json()
    assert c.get(f"/cases/{case}/inspection-imports", headers=H("gina")).status_code in (403, 404)
    assert c.get(f"/cases/{case}/inspection-imports/{imp['import_id']}/reconciliation",
                 headers=H("gina")).status_code in (403, 404)
    assert c.get(f"/intakes/{iid}/files/{fid}/inspection", headers=H("bob")).status_code in (403, 404)


def test_a_company_form_registered_by_the_admin_is_recognized_and_versioned(tmp_path):
    c, case = case_with_customer_lot(tmp_path)
    blank = c.get("/inspection-forms", headers=H("alice")).json()
    assert blank["template"]["lot"] == [] and blank["forms"][0]["builtin"]  # blanks to fill for a real form
    form = {"name": "ACME 수입검사", "reason": "고객사 ACME 양식 등록", "required": ["lot", "inspected_qty", "defective_qty"],
            "fields": {**blank["template"], "lot": ["제조번호"], "inspected_qty": ["검사량"], "defective_qty": ["부적합수"],
                       "part_number": ["자재코드"]}}  # unit, item, value left blank: not used
    assert c.post("/inspection-forms", json=form, headers=H("alice")).status_code == 403  # admin only
    v1 = c.post("/inspection-forms", json=form, headers=H("gina"))
    assert v1.status_code == 201 and v1.json()["version"] == 1 and "unit" not in v1.json()["fields"]
    data = workbook([["PCB-ECU-200", "L02", 480, 12]], head=["자재코드", "제조번호", "검사량", "부적합수"])
    iid, fid = upload_xlsx(c, data)
    v = preview(c, iid, fid)
    assert v["form"]["name"] == "ACME 수입검사" and v["mapping"]["lot"] == "B" and v["mapping"]["defective_qty"] == "D"
    imp = c.post(f"/cases/{case}/inspection-imports", json={**body(v, iid, fid), "form": "ACME 수입검사"},
                 headers=H("alice")).json()
    assert imp["form"] == "ACME 수입검사" and imp["mapping_version"] == v["form"]["form_version"]
    v2 = c.post("/inspection-forms", json={**form, "reason": "검사일 열 추가", "fields": {**form["fields"],
                                                                                   "inspected_on": ["검사일"]}},
                headers=H("gina")).json()
    assert v2["version"] == 2 and v2["form_version"] != v["form"]["form_version"]  # the import keeps v1's id
    bad = c.post("/inspection-forms", json={**form, "required": ["inspected_qty"]}, headers=H("gina"))
    assert bad.status_code == 422  # LOT stays required: it is how rows reach a case and a reconciliation
