"""XLSX / CSV intake and DOCX chart workbooks (spec §23-24): cells with locators, stored values only, nothing run."""

import io
import zipfile

from app import docparse
from app.intake import FIXTURE_DIR
from tests.test_intake_in1 import upload
from tests.test_intake_in2 import Scripted, analyze, client, f
from tests.v5_util import H

XLSX = FIXTURE_DIR / "inspection_results_HM-CC-2026-0417.xlsx"
CSV = FIXTURE_DIR / "shipments_HM-CC-2026-0417.csv"
MISMATCH = FIXTURE_DIR / "chart_workbook_mismatch.docx"


def test_spreadsheets_are_cells_with_locators_merged_spans_and_hidden_sheets(tmp_path):
    c = client(tmp_path, None)
    files = upload(c, [("r.xlsx", XLSX.read_bytes()), ("s.csv", CSV.read_bytes())]).json()["files"]
    assert [x["media_type"] for x in files] == ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                               "text/csv"]
    assert [x["data_origin"] for x in files] == ["SYNTHETIC", "SYNTHETIC"]
    els, cov, _ = docparse.parse(files[0]["media_type"], XLSX.read_bytes())
    by = {e["id"]: e for e in els}
    assert by["xlsx:Sheet1!A1"]["span"] == 4 and by["xlsx:Sheet1!B3"]["text"] == "480"
    assert "xlsx:Sheet1!B4" not in by  # a formula with no stored value is not computed here
    assert cov["hidden_sheets"] == ["내부메모"] and "xlsx:내부메모!B1" in by  # hidden, but read and said
    els, cov, _ = docparse.parse("text/csv", CSV.read_bytes())
    by = {e["id"]: e for e in els}
    assert by["csv:r2:c4"]["text"] == "SH-5521" and cov["encoding"] == "utf-8-sig"


def test_a_value_from_a_spreadsheet_cell_is_a_checked_source(tmp_path):
    p = Scripted()
    c = client(tmp_path, p)
    iid = upload(c, [("r.xlsx", XLSX.read_bytes())]).json()["intake_id"]
    p.replies.append({"documents": [], "links": [], "questions": [], "transcriptions": [],
                      "fields": [f("inspected_qty", "480", ("xlsx:Sheet1!B3", "480")),
                                 f("defective_qty", "13", ("xlsx:Sheet1!C3", "12"))]})
    d = analyze(c, iid).json()["draft"]
    assert d["fields"]["inspected_qty"]["status"] == "FOUND"
    assert d["fields"]["inspected_qty"]["sources"][0]["element_id"] == "xlsx:Sheet1!B3"
    assert d["fields"]["defective_qty"]["status"] == "UNVERIFIED"  # 13 is not what the cell says


def test_a_chart_that_disagrees_with_its_workbook_shows_both(tmp_path):
    els, cov, _ = docparse.parse("docx", MISMATCH.read_bytes())
    chart = next(e for e in els if e["kind"] == "chart")
    assert chart["workbook_compare"] == "MISMATCH" and cov["charts"] == "MISMATCH" and "사람이 판단" in cov["charts_note"]
    assert chart["series"][0]["values"] == [2.0, 3.0, 7.0] and chart["series"][0]["workbook_values"] == [2, 3, 8]
    plain = next(e for e in docparse.parse("docx", (FIXTURE_DIR / "supplement_HM-CC-2026-0417.docx").read_bytes())[0]
                 if e["kind"] == "chart")
    assert plain["workbook_compare"] == "NO_WORKBOOK"


def test_unsafe_or_unknown_spreadsheets_are_refused_with_a_way_forward(tmp_path):
    c = client(tmp_path, None)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(XLSX.read_bytes())) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for i in src.infolist():
            dst.writestr(i.filename, src.read(i.filename))
        dst.writestr("xl/vbaProject.bin", b"\0")
    cp949 = "출하일,LOT,수량\n2026-10-20,L02,60\n".encode("cp949")
    cases = {"m.xlsm": (out.getvalue(), 415), "old.xls": (b"\xd0\xcf\x11\xe0" + b"\0" * 64, 422),
             "notes.txt": ("그냥 메모입니다 구분자 없음".encode(), 415)}
    for name, (data, code) in cases.items():
        r = upload(c, [(name, data)])
        assert r.status_code == code, (name, r.text)
        assert "직접 입력" in r.json()["detail"]
    ok = upload(c, [("legacy.csv", cp949)])
    assert ok.status_code == 201 and ok.json()["files"][0]["checks"]["encoding"] == "cp949"
    assert ok.json()["files"][0]["data_origin"] == "UNKNOWN"
    assert c.get("/intakes", headers=H("alice")).json()[0]["files"][0]["name"] == "legacy.csv"
