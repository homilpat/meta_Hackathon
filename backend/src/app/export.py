"""G10: an approved D2-D4 document, or the closed 8D case, exported as a real DOCX or PDF file.

Only approved content leaves the system as an approved report. A document version must be APPROVED, its last
approval must name its exact content hash, no newer version of the same type may be approved, and its latest
validation must not be BLOCK. The case report needs the latest closure to be CLOSED, renders the snapshot that
closure archived, re-checks every document hash in it and needs an intact audit chain. After writing, the file is
read back (DOCX XML / PDF text) and must contain every required value, unit, LOT, evidence id, version, approver and
hash taken from the snapshot; otherwise nothing is returned. Every export is logged with the file's SHA-256.
"""

import hashlib
import html
import io
import re
import zipfile
from collections.abc import Callable
from typing import Annotated, Literal
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import audit, causes, validation
from app.db import ApprovalEvent, Closure, DocumentVersion, PreventionDeployment
from app.workflow import KINDS, STEP, Actor, _doc_out, _get_doc, _latest, log, now, require_case

MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf"}
FONT = "HYSMyeongJo-Medium"  # reportlab's built-in Korean CID font: Hangul renders without shipping a font file
Block = tuple  # ("h", text) | ("p", text) | ("t", header, rows, weights)


def num(v: float) -> str:
    return repr(float(v)).removesuffix(".0")


def claim_rows(c: dict, per_row: int = 12) -> list[list[str]]:
    """Long evidence lists continue on extra rows: a table row taller than a page cannot be laid out in the PDF."""
    ev = c["evidence_ids"]
    chunks = [", ".join(ev[i:i + per_row]) for i in range(0, len(ev), per_row)] or [""]
    first = [c["claim_id"], c["classification"], c["text"], "" if c["value"] is None else num(c["value"]),
             c["unit"] or "", chunks[0]]
    return [first] + [["", "", "", "", "", x] for x in chunks[1:]]


# --- what goes in the report -------------------------------------------------------------------------------

def doc_section(session: Session, doc: DocumentVersion) -> tuple[list[Block], list[str]]:
    d = _doc_out(session, doc)
    v = validation.latest_run(session, doc)
    stale = validation.stale_reasons(session, v) if v else []
    checked = (f"Validation #{v.id}: {v.result} by {v.validated_by} at {v.validated_at}; "
               + (f"no longer current ({'; '.join(stale)})" if stale else "current")) if v else "Not validated"
    blocks = [
        ("h", f"{doc.doc_type} v{doc.version} ({STEP[doc.doc_type]}) - {d['status']}"),
        ("p", (f"Author {d['author_id']}; generator {d['builder']}; based on {', '.join(d['based_on']) or '-'}; "
               f"created {d['created_at']}")),
        ("p", f"Content SHA-256 {doc.content_sha256}"),
        ("p", checked),
        ("t", ["Claim", "Class", "Statement", "Value", "Unit", "Evidence"],
         [row for c in d["claims"] for row in claim_rows(c)], [1, 2, 7, 1.4, 1.2, 3]),
        ("t", ["Signed by", "Decision", "Signed content SHA-256", "At"],
         [[x["actor_id"], x["action"], x["content_sha256"], x["created_at"]] for x in d["decisions"]],
         [1.4, 1.4, 5, 3]),
    ]
    required = [f"{doc.doc_type} v{doc.version}", doc.content_sha256,
                *(x["actor_id"] for x in d["decisions"] if x["action"] == "APPROVE")]
    for c in d["claims"]:
        required += [c["claim_id"], *c["evidence_ids"]]
        required += [num(c["value"])] if c["value"] is not None else []
        required += [c["unit"]] if c["unit"] else []
        # LOT numbers live in the statements; extracted PDF text only round-trips ASCII (CID font), so Hangul
        # statements are rendered but not compared
        required += [c["text"]] if c["text"].isascii() else []
    return blocks, required


def require_exportable(session: Session, doc: DocumentVersion) -> None:
    name = f"{doc.doc_type} v{doc.version}"
    if doc.status != "APPROVED":
        raise HTTPException(409, f"{name} is {doc.status}; only an APPROVED version is exported as approved")
    last = session.scalar(select(ApprovalEvent).where(ApprovalEvent.document_version_id == doc.id,
                                                      ApprovalEvent.action == "APPROVE")
                          .order_by(ApprovalEvent.id.desc()).limit(1))
    if last is None or last.content_sha256 != doc.content_sha256:
        raise HTTPException(409, f"{name}: no approval of this exact content")
    newer = session.scalar(select(DocumentVersion.version).where(
        DocumentVersion.case_id == doc.case_id, DocumentVersion.doc_type == doc.doc_type,
        DocumentVersion.version > doc.version, DocumentVersion.status == "APPROVED").limit(1))
    if newer:
        raise HTTPException(409, f"{name} was replaced by approved v{newer}; export the current version")
    v = validation.latest_run(session, doc)
    if v is not None and v.result == "BLOCK":
        raise HTTPException(409, f"{name}: latest validation #{v.id} is BLOCK")


def case_report(session: Session, case_id: str) -> tuple[Closure, list[Block], list[str]]:
    c = session.scalar(select(Closure).where(Closure.case_id == case_id).order_by(Closure.id.desc()).limit(1))
    if c is None or c.decision != "CLOSED":
        raise HTTPException(409, f"case {case_id} is {c.decision if c else 'not closed'}; "
                                 "the 8D report is exported from a CLOSED snapshot only")
    chain = audit.verify(session)
    if not chain["ok"]:
        raise HTTPException(409, f"audit chain is broken ({len(chain['breaks'])} problems); nothing is exported")
    s = c.snapshot
    state = {**s["state"], "D8": "CLOSED"}
    simple = s["route"] == "NCR_ONLY"  # D0 chose the simple route: D4-D7 were never required
    shown = {k: (v or ("N/A (NCR_ONLY)" if simple and k in ("D4", "D5", "D6", "D7") else "-")) for k, v in state.items()}
    blocks: list[Block] = [
        ("h", "Closure"),
        ("p", (f"Closed by {c.actor_id} at {c.created_at} (closure #{c.id}); policy {s['policy']['policy_id']} "
               f"v{s['policy']['version']} ({s['policy']['policy_hash'][:16]}); route {s['route']}")),
        ("p", f"Snapshot SHA-256 {c.snapshot_sha256}"),
        ("t", ["Stage", "State"], [[k, str(v)] for k, v in shown.items()], [1, 3]),
        ("t", ["Document", "Version", "Status at closure", "Content SHA-256"],
         [[d["doc_type"], f"v{d['version']}", d["status"], d["content_sha256"]] for d in s["documents"]],
         [2, 1, 2, 6]),
    ]
    required = [c.snapshot_sha256, c.actor_id, "CLOSED", *(f"{k}{v}" for k, v in state.items() if v)]
    rows = {(d.doc_type, d.version): d for d in session.scalars(
        select(DocumentVersion).where(DocumentVersion.case_id == case_id))}
    approved = {}
    for d in s["documents"]:
        row = rows.get((d["doc_type"], d["version"]))
        if row is None or row.content_sha256 != d["content_sha256"]:
            raise HTTPException(409, f"{d['doc_type']} v{d['version']} no longer matches the closure snapshot")
        required += [f"{d['doc_type']}v{d['version']}{d['status']}{d['content_sha256']}"]
        if d["status"] == "APPROVED":
            approved[d["doc_type"]] = row  # snapshot is ordered by id, so the last approved version wins
    for row in approved.values():
        b, r = doc_section(session, row)
        blocks += b
        required += r
    hyps = {h.id: h for h in causes.confirmed(session, case_id)}
    if simple:
        blocks.append(("p", ("Route NCR_ONLY: the D0 decision found no defect needing a full 8D, so the policy "
                             "required D0-D3 only. D4-D7 (cause, corrective action, effectiveness, prevention) were "
                             "not required.")))
    sections = [
        ("h", "D4 confirmed causes"),
        ("t", ["Cause", "Type", "Statement", "Evidence"],
         [[f"H{i}", f"{hyps[i].cause_type}/{hyps[i].category}" if i in hyps else "-",
           hyps[i].text if i in hyps else "(no longer confirmed)", ", ".join(hyps[i].evidence_ids) if i in hyps
           else ""] for i in s["confirmed_causes"]], [1, 2.4, 6, 3]),
        ("h", "D3/D5 actions"),
        ("t", ["Action", "Stage", "Type", "Status"],
         [[f"ACT-{a['action_id']}", a["stage"], a["type"], a["status"]] for a in s["actions"]], [1.4, 1, 3, 3]),
        ("h", "D6 effectiveness"),
        ("t", ["Result", "Action", "Computed", "Decision"],
         [[f"#{x['result_id']}", f"ACT-{x['action_id']}", x["computed"], x["decision"]]
          for x in s["effectiveness"]], [1, 1.4, 3, 3]),
        ("h", "D7 prevention"),
        ("t", ["Controlled document", "Revision", "Trained operators"],
         [[p["doc_number"], f"rev {p['revision']}", ", ".join(sorted(
             {t["operator_id"] for d in session.scalars(select(PreventionDeployment).where(
                 PreventionDeployment.case_id == case_id, PreventionDeployment.doc_number == p["doc_number"],
                 PreventionDeployment.new_revision == p["revision"])) for t in d.training}))]
          for p in s["prevention"]], [3, 1.4, 4]),
    ]
    for head, table in zip(sections[::2], sections[1::2], strict=True):
        # NCR_ONLY: leave out a not-required section only when it is empty, so every recorded row is still printed
        if not simple or table[2] or head[1] == "D3/D5 actions":
            blocks += [head, table]
    blocks += [
        ("h", "D8 sign-off"),
        ("p", f"Acknowledged by: {', '.join(s['acknowledged'])}"),
        ("t", ["Residual risk", "Mitigation", "Owner"],
         [[r["risk"], r["mitigation"], r["owner"]] for r in c.residual_risks], [4, 4, 1.4]),
        ("p", f"Customer notification: {c.customer_notification_ref or 'not required'}. Comment: {c.comment}"),
        ("p", f"Audit chain verified at export: {chain['links']} links, head {chain['head_sha256']}"),
    ]
    required += [f"H{i}" for i in s["confirmed_causes"]]
    required += [f"ACT-{a['action_id']}{a['stage']}{a['type']}{a['status']}" for a in s["actions"]]
    required += [f"ACT-{x['action_id']}{x['computed']}{x['decision']}" for x in s["effectiveness"]]
    required += [f"{p['doc_number']}rev{p['revision']}" for p in s["prevention"]]
    required += list(s["acknowledged"])
    return c, blocks, required


# --- writers -----------------------------------------------------------------------------------------------

def clean(t: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(t))


def to_docx(title: str, author: str, created: str, ref: str, blocks: list[Block]) -> bytes:
    def para(t: str, bold: bool = False, size: int | None = None, keep: bool = False) -> str:
        ppr = "<w:pPr><w:keepNext/></w:pPr>" if keep else ""
        rpr = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "")
        return (f'<w:p>{ppr}<w:r><w:rPr>{rpr}</w:rPr>'
                f'<w:t xml:space="preserve">{escape(clean(t))}</w:t></w:r></w:p>')

    body = [para(title, True, 32)]
    for b in blocks:
        if b[0] == "h":
            body.append(para(b[1], True, 26, keep=True))
        elif b[0] == "p":
            body.append(para(b[1], size=20))
        else:
            _, header, rows, weights = b
            total = sum(weights)
            grid = "".join(f'<w:gridCol w:w="{int(9638 * w / total)}"/>' for w in weights)
            border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
                             for s in ("top", "left", "bottom", "right", "insideH", "insideV"))

            def tr(cells: list, head: bool = False) -> str:
                trpr = "<w:trPr><w:tblHeader/></w:trPr>" if head else ""
                return f"<w:tr>{trpr}" + "".join(f"<w:tc>{para(x, head, 16)}</w:tc>" for x in cells) + "</w:tr>"

            body.append(f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders>'
                        f"</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{tr(header, True)}"
                        + "".join(tr(r) for r in rows) + "</w:tbl>")
            if not rows:
                body.append(para("(none)", size=18))
            body.append(para(""))
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" '
           'w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/></w:sectPr></w:body>'
           "</w:document>")
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.'
            'openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{escape(title)}</dc:title><dc:creator>{escape(author)}</dc:creator>"
            f"<dc:description>snapshot {ref}</dc:description>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created[:19]}Z</dcterms:created></cp:coreProperties>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="'
                   'http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" '
                   'ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" '
                   'ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/'
                   'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/docProps'
                   '/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="'
                   'http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://'
                   'schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.'
                   'xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/'
                   'metadata/core-properties" Target="docProps/core.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
        z.writestr("docProps/core.xml", core)
    return out.getvalue()


def to_pdf(title: str, author: str, created: str, ref: str, blocks: list[Block]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    if FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(FONT))
    body = ParagraphStyle("b", fontName=FONT, fontSize=9, leading=12, spaceAfter=3)
    cell = ParagraphStyle("c", parent=body, fontSize=7.5, leading=9.5, spaceAfter=0)
    head = ParagraphStyle("h", parent=body, fontSize=12, leading=16, spaceBefore=8, spaceAfter=4, keepWithNext=1)

    def p(t: str, s: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(clean(t)), s)

    width = A4[0] - 30 * mm
    flow = [p(title, ParagraphStyle("t", parent=head, fontSize=15, leading=20))]
    for b in blocks:
        if b[0] in ("h", "p"):
            flow.append(p(b[1], head if b[0] == "h" else body))
            continue
        _, header, rows, weights = b
        t = Table([[p(x, cell) for x in header]] + [[p(x, cell) for x in r] for r in rows], repeatRows=1,
                  colWidths=[width * w / sum(weights) for w in weights], spaceAfter=6)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8"))]))
        flow.append(t)
        if not rows:
            flow.append(p("(none)"))

    def footer(canvas, d) -> None:
        canvas.setFont(FONT, 7)
        canvas.drawString(15 * mm, 8 * mm, f"QualityOps AI - synthetic data - snapshot {ref[:16]} - "
                                           f"generated {created[:19]} by {author} - page {d.page}")

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                      bottomMargin=15 * mm, title=title, author=author, subject=f"snapshot {ref}",
                      creator="QualityOps AI").build(flow, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def text_of(data: bytes, fmt: str) -> str:
    """Read the written file back with a parser, as a reader would get it."""
    if fmt == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode()
        return html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)))
    from pypdf import PdfReader

    return "".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def missing_fields(data: bytes, fmt: str, required: list[str]) -> list[str]:
    def squash(s: str) -> str:
        return re.sub(r"\s+", "", s)

    text = squash(text_of(data, fmt))
    return [r for r in dict.fromkeys(required) if squash(r) not in text]


# --- routes ------------------------------------------------------------------------------------------------

def make_export_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    def respond(session: Session, case_id: str, actor: Actor, fmt: str, name: str, title: str, ref: str,
                blocks: list[Block], required: list[str], doc_id: int | None = None) -> Response:
        created = now()
        head: list[Block] = [("p", (f"Case {case_id}. Generated by {actor.id} at {created}. Reference SHA-256 "
                                    f"{ref}. Synthetic data; not a real plant record."))]
        data = (to_pdf if fmt == "pdf" else to_docx)(title, actor.id, created, ref, head + blocks)
        if gaps := missing_fields(data, fmt, required + [ref]):
            raise HTTPException(500, f"export check failed: {len(gaps)} required fields missing from the file "
                                     f"(e.g. {gaps[:3]}); nothing exported")
        filename = f"{name}_{ref[:12]}.{fmt}"
        digest = hashlib.sha256(data).hexdigest()
        log(session, case_id, actor, "EXPORTED", f"{filename} file_sha256={digest} reference={ref} "
            f"fields_checked={len(set(required))}", doc_id)
        return Response(data, media_type=MIME[fmt], headers={
            "Content-Disposition": f'attachment; filename="{filename}"', "X-Reference-SHA256": ref,
            "X-File-SHA256": digest, "X-Fields-Checked": str(len(set(required)))})

    @router.get("/cases/{case_id}/documents/{kind:doc}/export")
    def export_document(case_id: str, kind: str, actor: Who, format: Literal["docx", "pdf"] = "pdf",
                        version: int | None = None) -> Response:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind]) if version else _latest(session, case_id,
                                                                                            KINDS[kind])
            if doc is None:
                raise HTTPException(404, "Document version not found")
            require_exportable(session, doc)
            blocks, required = doc_section(session, doc)
            return respond(session, case_id, actor, format, f"{case_id}_{doc.doc_type}_v{doc.version}",
                           f"{doc.doc_type} {case_id} v{doc.version} - approved", doc.content_sha256, blocks,
                           required, doc.id)

    @router.get("/cases/{case_id}/report/export")
    def export_report(case_id: str, actor: Who, format: Literal["docx", "pdf"] = "pdf") -> Response:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            c, blocks, required = case_report(session, case_id)
            simple = c.snapshot["route"] == "NCR_ONLY"  # closed early on the simple route: say so in the title
            name, title = ("NCR_closure_report", "NCR closure report") if simple else ("8D_report", "8D report")
            return respond(session, case_id, actor, format, f"{case_id}_{name}",
                           f"{title} {case_id} - CLOSED", c.snapshot_sha256, blocks, required)

    return router
