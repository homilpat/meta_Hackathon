"""Server-side document structure extraction (spec v5.8 §24.2). The parser, not the model, reads the file.

Every element has a stable locator id:
  PDF   pdf:p{page}:l{line} text line · pdf:p{page}:img{i} image · pdf:p{page}:scan (a page with no text layer)
  DOCX  docx:p{i} paragraph · docx:t{t}:r{row}:c{col} table cell (grid column; merged cells keep their span)
        docx:img{i} image (same bytes at two places = two elements, one sha) · docx:chart{i} chart with its data
No page numbers are invented for DOCX (it is not rendered). Image bytes are returned apart from the elements, so
only files cleared for egress ever send them anywhere.
"""

import hashlib
import io
import re
import zipfile
from typing import Any

from lxml import etree

PARSER_VERSION = "docparse-2"  # 2: PDF table cells rebuilt from text positions
MAX_RENDER_PAGES = 10
RENDER_SCALE = 1.0  # 72 dpi: enough to see a layout, bounded memory per page
RENDER_ERRORS = (RuntimeError, OSError, ValueError, MemoryError)  # pypdfium2.PdfiumError is a RuntimeError
CAPTION = re.compile(r"^\s*(그림|사진|표|Fig\.?|Figure|Photo|Table)\s*\d", re.IGNORECASE)
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)  # no XXE, no fetches


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def parse(media_type: str, data: bytes) -> tuple[list[dict], dict, dict[str, bytes]]:
    """(elements, coverage, image bytes by element id)."""
    if media_type == "application/pdf":
        return parse_pdf(data)
    if media_type.endswith("spreadsheetml.sheet"):
        return parse_xlsx(data)
    if media_type == "text/csv":
        return parse_csv(data)
    return parse_docx(data)


# --- spreadsheets ------------------------------------------------------------------------------------------
MAX_CELLS = 20000  # per workbook: enough for an inspection sheet, bounded memory
MAX_CSV_ROWS = 20000


def cell_text(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def sheet_cells(ws, t: int, prefix: str, budget: list[int]) -> list[dict]:
    """Non-empty cells of one sheet with their merged span; cached values only (formulas are never evaluated)."""
    spans = {(r.min_row, r.min_col): (r.max_col - r.min_col + 1, r.max_row - r.min_row + 1)
             for r in ws.merged_cells.ranges}
    out = []
    for row in ws.iter_rows():
        for c in row:
            if c.value is None or budget[0] <= 0:
                continue
            budget[0] -= 1
            span, rows = spans.get((c.row, c.column), (1, 1))
            out.append({"id": f"{prefix}{c.coordinate}", "kind": "cell", "table": t, "sheet": ws.title, "row": c.row,
                        "col": c.column, "span": span, "row_span": rows, "text": cell_text(c.value)})
    return out


def parse_xlsx(data: bytes) -> tuple[list[dict], dict, dict[str, bytes]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, keep_links=False)
    budget, elements, hidden = [MAX_CELLS], [], []
    for t, ws in enumerate(wb.worksheets, 1):
        if ws.sheet_state != "visible":
            hidden.append(ws.title)
        elements += sheet_cells(ws, t, f"xlsx:{ws.title}!", budget)
    return elements, {"text": "NONE", "tables": "OK" if elements else "NONE", "images": "NONE",
                      "charts": "NOT_PARSED" if any(ws._charts for ws in wb.worksheets) else "NONE",
                      "scan": "NONE", "render": "NOT_SUPPORTED", "sheets": [ws.title for ws in wb.worksheets],
                      "hidden_sheets": hidden, "truncated": budget[0] <= 0,
                      "tables_note": "수식은 계산하지 않고 파일에 저장된 값을 씁니다 (저장된 값이 없는 수식 칸은 비어 있음)"
                      + (f"; 숨김 시트 {', '.join(hidden)} 포함" if hidden else "")}, {}


def decode_text(data: bytes) -> tuple[str, str] | None:
    if b"\0" in data[:4096]:
        return None
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None


def sniff_csv(data: bytes) -> dict | None:
    """A delimited text table, or None. CSV has no signature: it must decode and split consistently."""
    import csv

    decoded = decode_text(data)
    if decoded is None:
        return None
    text, enc = decoded
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return None
    rows = list(csv.reader(io.StringIO(text), dialect))
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return None
    return {"rows": len(rows), "encoding": enc, "delimiter": dialect.delimiter}


def parse_csv(data: bytes) -> tuple[list[dict], dict, dict[str, bytes]]:
    import csv

    text, enc = decode_text(data)
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    elements = [{"id": f"csv:r{r}:c{c}", "kind": "cell", "table": 1, "row": r, "col": c, "span": 1,
                 "text": v.strip()}
                for r, row in enumerate(csv.reader(io.StringIO(text), dialect), 1) if r <= MAX_CSV_ROWS
                for c, v in enumerate(row, 1) if v.strip()]
    return elements, {"text": "NONE", "tables": "OK" if elements else "NONE", "images": "NONE", "charts": "NONE",
                      "scan": "NONE", "render": "NOT_SUPPORTED", "encoding": enc}, {}


# --- PDF ---------------------------------------------------------------------------------------------------
ROW_TOL, COL_TOL = 2.0, 4.0  # points: same row if baselines differ less; same column if left edges do


def chunks(page) -> list[tuple[float, float, str]]:
    """(x, y, text) of each text run on a page, in page coordinates."""
    out: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, _font, _size):
        if text.strip():
            out.append((tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5], text.strip()))
    page.extract_text(visitor_text=visit)
    return out


def tables_of(runs: list[tuple[float, float, str]]) -> list[list[list[tuple[float, str]]]]:
    """Tables rebuilt from positions: consecutive rows of two or more runs whose left edges fall on the same
    columns. A borderless or merged-cell table may still be missed or split; it then stays as text lines."""
    rows: list[list[tuple[float, float, str]]] = []
    for x, y, t in sorted(runs, key=lambda r: (-r[1], r[0])):
        if rows and abs(rows[-1][0][1] - y) < ROW_TOL:
            rows[-1].append((x, y, t))
        else:
            rows.append([(x, y, t)])
    found: list[list[list[tuple[float, str]]]] = []
    cur: list[list[tuple[float, str]]] = []
    cols: list[float] = []
    for row in rows:
        cells = sorted((x, t) for x, _, t in row)
        xs = [x for x, _ in cells]
        if len(cells) >= 2 and cur and all(any(abs(x - c) < COL_TOL for c in cols) for x in xs):
            cur.append(cells)
            continue
        if len(cur) >= 2:
            found.append(cur)
        cur, cols = ([cells], xs) if len(cells) >= 2 else ([], [])
    if len(cur) >= 2:
        found.append(cur)
    return found
def parse_pdf(data: bytes) -> tuple[list[dict], dict, dict[str, bytes]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    elements: list[dict] = []
    blobs: dict[str, bytes] = {}
    scans = tables = 0
    for n, page in enumerate(reader.pages, 1):
        lines = [x.strip() for x in (page.extract_text() or "").splitlines() if x.strip()]
        for i, line in enumerate(lines, 1):
            elements.append({"id": f"pdf:p{n}:l{i}", "kind": "text", "page": n, "text": line})
        captions = [f"pdf:p{n}:l{i}" for i, line in enumerate(lines, 1) if CAPTION.match(line)]
        for t, table in enumerate(tables_of(chunks(page)), 1):
            tables += 1
            cols = sorted({x for row in table for x, _ in row})
            for r, row in enumerate(table, 1):
                for x, text in row:
                    c = min(range(len(cols)), key=lambda k: abs(cols[k] - x)) + 1
                    elements.append({"id": f"pdf:p{n}:t{t}:r{r}:c{c}", "kind": "cell", "page": n, "table": t,
                                     "row": r, "col": c, "span": 1, "text": text, "rebuilt": True})
        images = list(page.images)
        if not lines and images:  # no text layer: a scan, readable only through a vision path
            scans += 1
            elements.append({"id": f"pdf:p{n}:scan", "kind": "scan_page", "page": n, "text": "",
                             "status": "NEEDS_VISION"})
            blobs[f"pdf:p{n}:scan"] = images[0].data  # the scan itself: only a vision path can read it
            continue
        for i, img in enumerate(images, 1):
            eid = f"pdf:p{n}:img{i}"
            blobs[eid] = img.data
            elements.append({"id": eid, "kind": "image", "page": n, "sha256": sha(img.data), "text": "",
                             # one image and one caption on a page link; anything else is left for a person
                             "caption_id": captions[0] if len(images) == 1 and len(captions) == 1 else None,
                             "caption_candidates": captions if not (len(images) == 1 and len(captions) == 1) else []})
    mark_duplicates(elements)
    coverage = {"text": "OK" if any(e["kind"] == "text" for e in elements) else "NONE",
                "tables": "RECONSTRUCTED" if tables else "PARTIAL" if any(e["kind"] == "text" for e in elements)
                else "NONE",
                "tables_note": "PDF 표는 글자 좌표로 행·열을 재구성했습니다 (선 없는 표·병합 셀은 원문과 대조 필요)"
                if tables else "PDF에서 표 구조를 찾지 못해 텍스트 줄로만 추출했습니다",
                "images": "OK" if blobs else "NONE",
                "charts": "IMAGE_ONLY" if blobs else "NONE",
                "charts_note": "PDF 안의 차트는 그림이라 원본 수치가 없습니다 (그림 수치는 공식 통계에 쓰지 않음)",
                "scan": "NEEDS_VISION" if scans else "NONE", "scan_pages": scans}
    coverage.update(render_check(data, len(reader.pages)))
    return elements, coverage, blobs


def render_check(data: bytes, pages: int) -> dict:
    """Render the pages (bounded) to confirm the layout can be shown; a failure keeps the structural path."""
    try:
        doc = render_document(data)
        n = min(pages, MAX_RENDER_PAGES)
        for k in range(n):
            doc[k].render(scale=RENDER_SCALE).close()
        doc.close()
        return {"render": "OK" if n == pages else "PARTIAL", "rendered_pages": n}
    except RENDER_ERRORS as exc:  # a renderer failure means "not rendered", never a crash
        return {"render": "FAILED", "render_error": type(exc).__name__,
                "render_note": "렌더링에 실패해 구조 추출 결과와 원문 다운로드로 확인합니다"}


def render_document(data: bytes):
    import pypdfium2

    return pypdfium2.PdfDocument(data)


def render_page_png(data: bytes, page: int) -> bytes:
    doc = render_document(data)
    try:
        img = doc[page - 1].render(scale=RENDER_SCALE).to_pil()
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    finally:
        doc.close()


# --- DOCX --------------------------------------------------------------------------------------------------
def w(tag: str) -> str:
    p, t = tag.split(":")
    return f"{{{NS[p]}}}{t}"


def text_of(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def rels_of(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = part.rsplit("/", 1)
    path = f"{folder}/_rels/{name}.rels"
    if path not in z.namelist():
        return {}
    root = etree.fromstring(z.read(path), SAFE_XML)
    return {r.get("Id"): r.get("Target") for r in root.findall("pr:Relationship", NS)
            if r.get("TargetMode") != "External"}  # external targets are never resolved


def chart_data(z: zipfile.ZipFile, part: str) -> dict:
    root = etree.fromstring(z.read(part), SAFE_XML)
    series = []
    for s in root.iter(w("c:ser")):
        def pts(node) -> list[str]:
            return [v.text or "" for v in sorted(node.iter(w("c:pt")), key=lambda p: int(p.get("idx")))
                    for v in v.findall("c:v", NS)] if node is not None else []
        name = pts(s.find("c:tx", NS))
        try:
            values = [float(v) for v in pts(s.find("c:val", NS))]
        except ValueError:
            values = []
        series.append({"name": name[0] if name else "", "categories": pts(s.find("c:cat", NS)), "values": values,
                       "total": round(sum(values), 6), "max": max(values) if values else None})
    refs = [s.find("c:val/c:numRef/c:f", NS) for s in root.iter(w("c:ser"))]
    workbook = next((t for t in rels_of(z, part).values() if t.endswith(".xlsx")), None)
    compare = compare_workbook(z, part, workbook, series, [r.text if r is not None else None for r in refs]) \
        if workbook else "NO_WORKBOOK"
    return {"title": "".join(t.text or "" for t in root.iter(w("a:t"))) or None, "series": series,
            "source": "CHART_CACHE", "workbook_present": workbook is not None, "workbook_compare": compare}


def compare_workbook(z: zipfile.ZipFile, part: str, target: str, series: list[dict], refs: list[str | None]) -> str:
    """Read each series' range from the embedded workbook (stored values, nothing evaluated) and compare it with
    the chart's cached values. MISMATCH is shown, never resolved: a person decides which one is right."""
    import posixpath

    import openpyxl

    path = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
    if path not in z.namelist():
        return "NOT_COMPARABLE"
    wb = openpyxl.load_workbook(io.BytesIO(z.read(path)), data_only=True)
    result = "MATCH"
    for s, ref in zip(series, refs, strict=False):
        m = re.fullmatch(r"'?([^'!]+)'?!\$?([A-Z]+)\$?(\d+):\$?([A-Z]+)\$?(\d+)", ref or "")
        if not m or m.group(1) not in wb.sheetnames:
            s["workbook_values"], result = None, "NOT_COMPARABLE" if result == "MATCH" else result
            continue
        cells = wb[m.group(1)][f"{m.group(2)}{m.group(3)}:{m.group(4)}{m.group(5)}"]
        vals = [c.value for row in cells for c in row]
        s["workbook_values"] = vals
        if [float(v) if isinstance(v, int | float) else None for v in vals] != s["values"]:
            result = "MISMATCH"
    return result


def parse_docx(data: bytes) -> tuple[list[dict], dict, dict[str, bytes]]:
    z = zipfile.ZipFile(io.BytesIO(data))
    body = etree.fromstring(z.read("word/document.xml"), SAFE_XML).find("w:body", NS)
    rels = rels_of(z, "word/document.xml")
    elements: list[dict] = []
    blobs: dict[str, bytes] = {}
    counts = {"p": 0, "t": 0, "img": 0, "chart": 0}
    pending: list[dict] = []  # images/charts waiting for a caption in the next paragraph

    def paragraph(p) -> None:
        counts["p"] += 1
        pid, text = f"docx:p{counts['p']}", text_of(p)
        for el in pending:
            el["caption_id"] = pid if text and CAPTION.match(text) else None
        pending.clear()
        if text:
            elements.append({"id": pid, "kind": "text", "text": text})
        for blip in p.iter(w("a:blip")):
            target = rels.get(blip.get(w("r:embed")))
            if target and f"word/{target}" in z.namelist():
                counts["img"] += 1
                eid, b = f"docx:img{counts['img']}", z.read(f"word/{target}")
                blobs[eid] = b
                el = {"id": eid, "kind": "image", "sha256": sha(b), "after": pid, "text": ""}
                elements.append(el)
                pending.append(el)
        for ch in p.iter(w("c:chart")):
            target = rels.get(ch.get(w("r:id")))
            if target and f"word/{target}" in z.namelist():
                counts["chart"] += 1
                el = {"id": f"docx:chart{counts['chart']}", "kind": "chart", "after": pid,
                      **chart_data(z, f"word/{target}")}
                el["text"] = " ".join([el["title"] or ""] + [f"{s['name']}: " + ", ".join(
                    f"{c} {v:g}" for c, v in zip(s["categories"], s["values"], strict=False)) for s in el["series"]])
                elements.append(el)
                pending.append(el)

    for node in body:
        if node.tag == w("w:p"):
            paragraph(node)
        elif node.tag == w("w:tbl"):
            counts["t"] += 1
            for r, tr in enumerate(node.findall("w:tr", NS), 1):
                col = 1
                for tc in tr.findall("w:tc", NS):
                    span_el = tc.find("w:tcPr/w:gridSpan", NS)
                    vm = tc.find("w:tcPr/w:vMerge", NS)
                    span = int(span_el.get(w("w:val"))) if span_el is not None else 1
                    elements.append({"id": f"docx:t{counts['t']}:r{r}:c{col}", "kind": "cell", "table": counts["t"],
                                     "row": r, "col": col, "span": span, "text": text_of(tc),
                                     "vmerge": None if vm is None else (vm.get(w("w:val")) or "continue")})
                    col += span
    for el in pending:
        el["caption_id"] = None
    mark_duplicates(elements)
    charts = [e for e in elements if e["kind"] == "chart"]
    mismatch = [c["id"] for c in charts if c["workbook_compare"] == "MISMATCH"]
    coverage = {"text": "OK" if any(e["kind"] == "text" for e in elements) else "NONE",
                "tables": "OK" if counts["t"] else "NONE", "images": "OK" if counts["img"] else "NONE",
                "charts": ("MISMATCH" if mismatch else "OK" if all(s["values"] for c in charts for s in c["series"])
                           else "PARTIAL") if charts else "NONE", "scan": "NONE",
                **({"charts_note": f"{', '.join(mismatch)}: 차트에 표시된 값과 내장 워크북 값이 다릅니다 "
                                   "(둘 다 표시하며 어느 쪽이 맞는지는 사람이 판단)"} if mismatch else {}),
                "render": "NOT_SUPPORTED", "render_note": "DOCX는 렌더링하지 않으며 문단·표·셀 위치로 원문을 가리킵니다"}
    return elements, coverage, blobs


def mark_duplicates(elements: list[dict]) -> None:
    first: dict[str, str] = {}
    for e in elements:
        if e["kind"] == "image":
            e["duplicate_of"] = first.setdefault(e["sha256"], e["id"]) if e["sha256"] in first else None
            first.setdefault(e["sha256"], e["id"])


def find(elements: list[dict], eid: str) -> dict | None:
    return next((e for e in elements if e["id"] == eid), None)


def public(elements: list[dict]) -> list[dict[str, Any]]:
    return elements  # elements carry no bytes; kept as a named step for callers that serialize them
