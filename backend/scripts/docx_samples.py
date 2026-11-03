"""Synthetic customer DOCX forms (spec v5.15 §30.1) and the gold mapping of each, written before any run. Used by
tests, scripts/v515_demo.py and the screen demo.

    python -m scripts.docx_samples fixtures     writes the forms into app/fixtures/intake (treated as shipped synthetic)
"""

import io
import sys

import docx

from app.intake import FIXTURE_DIR

TABLE_ROWS = [("Customer", "case.customer"), ("Case No.", "case.id"), ("LOT", "case.lot"),
              ("D2 Problem Description", "d2.problem"), ("D3 Containment Action", "d3.containment"),
              ("D4 Root Cause", "d4.occurrence_cause"), ("Escape Point (why not detected)", "d4.escape_cause"),
              ("Approved by", "d4.approved_by")]
PARAGRAPHS = [("고객사", "case.customer"), ("사건 번호", "case.id"), ("발생 원인", "d4.occurrence_cause"),
              ("유출 원인", "d4.escape_cause"), ("봉쇄 조치", "d3.containment"), ("비고", None)]


def table_form(rows=TABLE_ROWS, title="SYNTHETIC 8D Report (customer form A)") -> bytes:
    d = docx.Document()
    d.add_heading(title, 1)
    t = d.add_table(rows=len(rows), cols=2)
    for i, (label, _) in enumerate(rows):
        t.cell(i, 0).text = label
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def paragraph_form() -> bytes:
    d = docx.Document()
    d.add_heading("SYNTHETIC 품질 회신서 (고객 양식 B)", 1)
    for label, _ in PARAGRAPHS:
        d.add_paragraph(f"{label}: ____")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


FORMS = {  # file name -> (customer, form name, bytes builder)
    "customer_form_A_8d_table.docx": ("DEFAULT", "8D 회신서 A", lambda: table_form()),
    "customer_form_A_8d_table_v2.docx": ("DEFAULT", "8D 회신서 A", lambda: table_form(
        [*TABLE_ROWS[:6], ("Corrective Action", None), *TABLE_ROWS[6:]])),
    "customer_form_B_reply_paragraph.docx": ("DEFAULT", "품질 회신서 B", paragraph_form),
    "customer_form_OTHER_8d.docx": ("OTHER-CO", "8D Report", lambda: table_form(title="SYNTHETIC OTHER-CO 8D")),
}


def gold_table() -> dict:
    return {f"T0.R{i}.C1": f for i, (_, f) in enumerate(TABLE_ROWS)}


def gold_paragraph() -> dict:
    return {f"P{i + 1}": f for i, (_, f) in enumerate(PARAGRAPHS)}  # P0 is the heading


def fixtures() -> int:
    for name, (_, _, build) in FORMS.items():
        (FIXTURE_DIR / name).write_bytes(build())
        print(FIXTURE_DIR / name)
    return 0


if __name__ == "__main__":
    sys.exit(fixtures() if sys.argv[1:] == ["fixtures"] else print(__doc__) or 2)
