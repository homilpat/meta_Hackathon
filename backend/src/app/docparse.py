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

PARSER_VERSION = "docparse-1"
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
    return parse_pdf(data) if media_type == "application/pdf" else parse_docx(data)


# --- PDF ---------------------------------------------------------------------------------------------------
def parse_pdf(data: bytes) -> tuple[list[dict], dict, dict[str, bytes]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    elements: list[dict] = []
    blobs: dict[str, bytes] = {}
    scans = 0
    for n, page in enumerate(reader.pages, 1):
        lines = [x.strip() for x in (page.extract_text() or "").splitlines() if x.strip()]
        for i, line in enumerate(lines, 1):
            elements.append({"id": f"pdf:p{n}:l{i}", "kind": "text", "page": n, "text": line})
        captions = [f"pdf:p{n}:l{i}" for i, line in enumerate(lines, 1) if CAPTION.match(line)]
        images = list(page.images)
        if not lines and images:  # no text layer: a scan, readable only through a vision path
            scans += 1
            elements.append({"id": f"pdf:p{n}:scan", "kind": "scan_page", "page": n, "text": "",
                             "status": "NEEDS_VISION"})
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
                "tables": "PARTIAL" if any(e["kind"] == "text" for e in elements) else "NONE",
                "tables_note": "PDF 표는 텍스트 줄로만 추출되며 셀 구조는 보존되지 않습니다",
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
    has_workbook = any(t.endswith((".xlsx", ".bin")) for t in rels_of(z, part).values())
    return {"title": "".join(t.text or "" for t in root.iter(w("a:t"))) or None, "series": series,
            "source": "CHART_CACHE",  # values cached in the chart part; an embedded workbook is not opened
            "workbook_present": has_workbook}


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
    coverage = {"text": "OK" if any(e["kind"] == "text" for e in elements) else "NONE",
                "tables": "OK" if counts["t"] else "NONE", "images": "OK" if counts["img"] else "NONE",
                "charts": ("OK" if all(s["values"] for c in charts for s in c["series"]) else "PARTIAL")
                if charts else "NONE", "scan": "NONE",
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
