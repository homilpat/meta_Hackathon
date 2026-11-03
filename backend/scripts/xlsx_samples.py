"""Synthetic unregistered inspection XLSX samples (spec v5.14 §29), each with its gold mapping written down here
before any run: the table a person would pick and the column of each required field (None: the file has none, and
the right answer is to hold the field). Used by tests, scripts/xlsx_map_eval.py and the demo fixtures.

    python -m scripts.xlsx_samples fixtures     writes the two demo files (same structure, different values) into
                                                app/fixtures/intake, where the server treats them as shipped synthetic
"""

import io
import sys

import openpyxl

from app.intake import FIXTURE_DIR

DEMO_A = "unregistered_inspection_SN-0300_A.xlsx"
DEMO_B = "unregistered_inspection_SN-0300_B.xlsx"


def book(sheets: dict[str, list[list]], merges: dict[str, list[str]] | None = None,
         text_cols: dict[str, str] | None = None) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
        for rng in (merges or {}).get(name, []):
            ws.merge_cells(rng)
        for ref, fmt in (text_cols or {}).items():
            if ref.startswith(name + "!"):
                ws[ref.split("!")[1]].number_format = fmt
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def two_row(values: list[list]) -> bytes:
    """The demo structure: a merged two-row header, Accepted and Rejected under one quantity group."""
    return book({"검사성적": [["SYNTHETIC 수입검사 성적서 (SN-0300)"],
                             ["LOT 번호", "검사일", "수량", None, None, "비고"],
                             [None, None, "검사", "합격", "불합격", None], *values]},
                {"검사성적": ["A2:A3", "B2:B3", "C2:E2", "F2:F3"]})


DEMO_VALUES_A = [["00412", "2026-10-27", 480, 470, 10, ""], ["00413", "2026-10-28", 500, 496, 4, ""]]
DEMO_VALUES_B = [["00521", "2026-11-02", 320, 311, 9, "재검사"], ["00522", "2026-11-02", 300, 300, 0, ""],
                 ["00523", "2026-11-03", 260, 255, 5, ""]]


def samples() -> list[dict]:
    """name, bytes, gold {table: header range start, lot/inspected_qty/defective_qty: column or None}."""
    rows3 = [["L-7101", 480, 470, 10], ["L-7102", 500, 495, 5]]
    out = [
        ("en_punctuated", book({"Sheet1": [["Incoming inspection"], ["Part No.", "Lot No.", "Insp. Date",
                                                                    "Qty Inspected", "Qty Defective", "UoM"],
                                          ["PN-1", "L-7101", "2026-10-27", 480, 12, "EA"],
                                          ["PN-1", "L-7102", "2026-10-28", 500, 3, "EA"]]}),
         {"table": "Sheet1!A2", "lot": "B", "inspected_qty": "D", "defective_qty": "E"}),
        ("merged_two_row", two_row(DEMO_VALUES_A),
         {"table": "검사성적!A2", "lot": "A", "inspected_qty": "C", "defective_qty": "E"}),
        ("accepted_rejected", book({"Data": [["Lot", "Inspected", "Accepted", "Rejected"], *rows3]}),
         {"table": "Data!A1", "lot": "A", "inspected_qty": "B", "defective_qty": "D"}),
        ("rejected_first", book({"Data": [["Lot", "Rejected", "Accepted", "Total"],
                                          ["L-7101", 10, 470, 480], ["L-7102", 5, 495, 500]]}),
         {"table": "Data!A1", "lot": "A", "inspected_qty": "D", "defective_qty": "B"}),
        ("multiple_tables", book({"Report": [["Summary"], ["Lot", "Pass rate"], ["L-7101", 0.98], [],
                                             ["Detail"], ["LOT", "검사 수량", "불량 수량"], ["L-7101", 480, 10],
                                             ["L-7102", 500, 5]]}),
         {"table": "Report!A6", "lot": "A", "inspected_qty": "B", "defective_qty": "C"}),
        ("two_sheets", book({"요약": [["구분", "값"], ["합계", 980]],
                             "Data": [["Lot ID", "Checked", "NG"], ["L-7101", 480, 10], ["L-7102", 500, 5]]}),
         {"table": "Data!A1", "lot": "A", "inspected_qty": "B", "defective_qty": "C"}),
        ("japanese", book({"検査": [["ロット", "検査数", "不良数", "単位"], ["L-7101", 480, 10, "個"],
                                   ["L-7102", 500, 5, "個"]]}),
         {"table": "検査!A1", "lot": "A", "inspected_qty": "B", "defective_qty": "C"}),
        ("abbreviations", book({"QC": [["LOT#", "INSP QTY", "NG QTY"], ["L-7101", 480, 10], ["L-7102", 500, 5]]}),
         {"table": "QC!A1", "lot": "A", "inspected_qty": "B", "defective_qty": "C"}),
        ("missing_defective", book({"Data": [["Lot", "Inspected", "Remarks"], ["L-7101", 480, "ok"],
                                             ["L-7102", 500, "-"]]}),
         {"table": "Data!A1", "lot": "A", "inspected_qty": "B", "defective_qty": None}),
        ("builtin_control", book({"검사결과": [["품번", "LOT", "검사일", "검사 수량", "불량 수량", "단위"],
                                              ["PN-1", "L-7101", "2026-10-27", 480, 10, "EA"]]}),
         {"table": "검사결과!A1", "lot": "B", "inspected_qty": "D", "defective_qty": "E"}),
        ("batch_leading_zero", book({"Sheet1": [["Batch", "Qty", "Defects"], ["00412", 480, 10],
                                                ["00413", 500, 5]]}),
         {"table": "Sheet1!A1", "lot": "A", "inspected_qty": "B", "defective_qty": "C"}),
        ("meta_rows", book({"Sheet1": [["Supplier", "ACME (synthetic)"], ["Report date", "2026-10-30"],
                                       ["Item code", "Lot", "Sample size", "Good", "Defective"],
                                       ["PN-1", "L-7101", 125, 122, 3], ["PN-1", "L-7102", 125, 125, 0]]}),
         {"table": "Sheet1!A3", "lot": "B", "inspected_qty": "C", "defective_qty": "E"}),
    ]
    return [{"name": n, "data": d, "gold": g} for n, d, g in out]


def fixtures() -> int:
    for name, values in ((DEMO_A, DEMO_VALUES_A), (DEMO_B, DEMO_VALUES_B)):
        (FIXTURE_DIR / name).write_bytes(two_row(values))
        print(FIXTURE_DIR / name)
    return 0


if __name__ == "__main__":
    sys.exit(fixtures() if sys.argv[1:] == ["fixtures"] else print(__doc__) or 2)
