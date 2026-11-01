"""Held-out documents for comparing how documents reach the model (never used to tune the selector or prompts).

H1  60-page PDF with bookmarks and a contents page; values in sections, worded differently ("Claim No.",
    "Samples / NG count", "Respond no later than").
H2  Korean DOCX with heading styles; values in prose and a table ("클레임 번호", "시료 수 / 부적합 수",
    "회신 요청일 2026년 12월 3일").
H3  40-page PDF with no contents and no headings; values inside running sentences.
Each comes with the truth: field -> text the value must contain.
"""

import io

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

NOISE = ["The team reviewed handling instructions for the warehouse staff.",
         "Training sessions were scheduled for the next maintenance window.",
         "This section repeats the general terms of the supply agreement.",
         "Packaging should follow the regional transport guidelines.",
         "Questions about invoicing go to the finance contact listed separately."]


def h1() -> tuple[bytes, dict]:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    sections = {3: "1. Claim overview", 22: "2. Failure description", 41: "3. Incoming inspection results",
                57: "4. Requested actions"}
    c.drawString(50, 800, "SYNTHETIC HOLDOUT H1 - Supplier quality claim file")
    c.drawString(50, 770, "Contents")
    for k, (pg, title) in enumerate(sections.items()):
        c.drawString(70, 740 - 20 * k, f"{title} ........ {pg}")
    c.showPage()
    for p in range(2, 61):
        if p in sections:
            c.drawString(50, 800, sections[p])
            c.bookmarkPage(f"s{p}")
            c.addOutlineEntry(sections[p], f"s{p}", level=0)
        for k in range(20):
            c.drawString(50, 770 - 25 * k, f"{NOISE[(p + k) % len(NOISE)]} [{p}.{k}]")
        if p == 3:
            c.drawString(50, 230, "Claim No.: ZK-77-1032 raised by Orion Drives (fictional)")
        if p == 22:
            c.drawString(50, 230, "Observed failure: cold solder joint on connector J2, intermittent contact")
        if p == 41:
            for r, row in enumerate([["Lot No.", "Samples", "NG count"], ["B-4471", "320", "11"]]):
                for k, cell in enumerate(row):
                    c.drawString(55 + k * 150, 230 - r * 20, cell)
        if p == 57:
            c.drawString(50, 230, "Respond no later than 2026-12-05 with containment and root cause.")
        c.showPage()
    c.save()
    return buf.getvalue(), {"customer_ref": "ZK-77-1032", "phenomenon": "cold solder", "lot": "B-4471",
                            "inspected_qty": "320", "defective_qty": "11", "reply_deadline": "2026-12-05"}


def h2() -> tuple[bytes, dict]:
    doc = Document()
    doc.add_paragraph("SYNTHETIC HOLDOUT H2 - 고객 품질 이의 제기서")
    for title, body in [("1. 개요", ["본 문서는 납품 제품에 대한 품질 이의를 정리한 것입니다.",
                                     "관련 클레임 번호는 KR-CL-0921이며 담당 부서는 구매품질팀입니다."]),
                        ("2. 일반 사항", ["포장과 운송 조건은 기존 계약을 따릅니다."] * 6),
                        ("3. 부적합 내용", ["커넥터 핀이 휘어 삽입 불량이 발생했습니다(핀 휨)."]),
                        ("4. 검사 결과", []),
                        ("5. 요청 사항", ["회신 요청일은 2026년 12월 3일이며 원인과 대책을 포함해 주십시오."])]:
        doc.add_heading(title, level=1)
        for line in body:
            doc.add_paragraph(line)
        if title.startswith("4."):
            t = doc.add_table(rows=2, cols=3)
            for k, v in enumerate(["로트", "시료 수", "부적합 수"]):
                t.cell(0, k).text = v
            for k, v in enumerate(["KL-0915", "250", "9"]):
                t.cell(1, k).text = v
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), {"customer_ref": "KR-CL-0921", "phenomenon": "핀 휨", "lot": "KL-0915",
                            "inspected_qty": "250", "defective_qty": "9", "reply_deadline": "2026년 12월 3일"}


def h3() -> tuple[bytes, dict]:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for p in range(1, 41):
        for k in range(22):
            c.drawString(50, 790 - 25 * k, f"{NOISE[(p * 3 + k) % len(NOISE)]} ({p}/{k})")
        if p == 1:
            c.drawString(50, 230, "SYNTHETIC HOLDOUT H3 - correspondence log, no index")
        if p == 14:
            c.drawString(50, 230, "During our checks we found 7 of 180 units from batch M-2209 with a cracked capacitor C5.")
        if p == 27:
            c.drawString(50, 230, "For tracking, our internal case is QA/2026/0388.")
        if p == 39:
            c.drawString(50, 230, "We expect your written answer by November 28, 2026.")
        c.showPage()
    c.save()
    return buf.getvalue(), {"customer_ref": "QA/2026/0388", "phenomenon": "cracked capacitor", "lot": "M-2209",
                            "inspected_qty": "180", "defective_qty": "7", "reply_deadline": "November 28"}


DOCS = {"H1": ("application/pdf", h1), "H2": ("docx", h2), "H3": ("application/pdf", h3)}
