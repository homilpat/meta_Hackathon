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

from app import audit, causes, translate, validation
from app.db import (
    ApprovalEvent,
    Closure,
    DocumentVersion,
    Evidence,
    PreventionDeployment,
    SourceEvent,
)
from app.workflow import KINDS, STEP, Actor, _doc_out, _get_doc, _latest, log, now, require_case

MIME = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf"}
FONT = "HYSMyeongJo-Medium"  # reportlab's built-in Korean CID font: Hangul renders without shipping a font file
Block = tuple  # ("h", text) | ("p", text) | ("t", header, rows, weights)


def num(v: float) -> str:
    return repr(float(v)).removesuffix(".0")


# Readers get words, not hashes (user 2026-11-05): each claim names what its evidence is ("SPI 측정 8건");
# record ids, content hashes and the audit chain stay in the system and its logs.
KO = {"OBSERVED": "관찰", "CALCULATED": "계산", "HYPOTHESIS": "가설", "PROPOSAL": "제안", "UNKNOWN": "미확인",
      "DONE": "완료", "APPROVED": "승인", "CLOSED": "종결", "APPROVE": "승인", "REJECT": "반려",
      "REQUEST_CHANGES": "수정 요청", "NO_SCOPE_IMPACT": "범위 영향 없음 확인", "IN_REVIEW": "검토 중",
      "NCR_ONLY": "NCR 단독 (D0-D3)", "FULL_8D": "전체 8D", "EMERGENCY_FULL_8D": "긴급 전체 8D",
      "INDEPENDENTLY_VERIFIED": "독립 확인 완료", "EXECUTED": "실행됨", "REQUESTED": "요청됨",
      "PLAN_APPROVED": "계획 승인", "EFFECTIVE": "효과 있음", "NOT_EFFECTIVE": "효과 없음",
      "MEETS_CRITERIA": "기준 충족", "HOLD": "보류", "EQUIPMENT_CHANGE": "설비 변경", "WARN": "경고", "PASS": "통과",
      "BLOCK": "차단"}
# status words the records keep in English inside sentences (and translations keep as written)
WORDS = {"FALSE_ALARM": "오경보", "DEFECT_CONFIRMED": "불량 확정", "NO_REPAIR": "수리 안 함", "REPAIRED": "수리 완료",
         "UNCONFIRMED": "미확정", "NOT_EXECUTED": "미실행", "CLEANING_INTERVAL_EXCEEDED": "세척 주기 초과",
         "SHIPPED": "출하됨"}
WORD = re.compile(r"\b(" + "|".join(WORDS) + r")\b")


def plain(t: str) -> str:
    return WORD.sub(lambda m: WORDS[m.group(1)], t)


def when(t: str) -> str:
    return t[:16].replace("T", " ")
SOURCE = {"aoi_inspections": "AOI 검사", "spi_measurements": "SPI 측정", "human_verifications": "사람 확인",
          "repair_dispositions": "수리 처리", "equipment_events": "설비 기록", "lots": "LOT", "panels": "패널",
          "boards": "보드", "components": "부품", "pins": "핀", "shipments": "출하", "CUSTOMER_REPORT": "고객 문서"}
DOC_KO = {"NCR": "문제 기술 (NCR)", "CONTAINMENT": "임시 조치 계획", "RCA": "원인 분석"}


def ko(v) -> str:
    return KO.get(str(v), str(v)) if v is not None else "-"


def sources(session: Session, case_id: str) -> dict[str, tuple[str, str]]:
    """evidence id -> (kind of record, original row id such as AOI-L02-P03-B4-A01)."""
    rows = session.execute(select(Evidence.evidence_id, Evidence.classification, SourceEvent.entity_type,
                                  SourceEvent.original_row_id)
                           .outerjoin(SourceEvent, SourceEvent.id == Evidence.source_event_id)
                           .where(Evidence.case_id == case_id))
    return {e: (SOURCE.get(t, t) if t else ko(k), r or "") for e, k, t, r in rows}


def evidence_words(ids: list[str], src: dict) -> str:
    """'SPI 측정 8건' or, for a few records, their row ids ('설비 기록 EQ-STN-2')."""
    if not ids:
        return "-"
    known = [src.get(e, ("근거", "")) for e in ids]
    if len(known) <= 3 and all(r for _, r in known):
        return ", ".join(f"{k} {r}" for k, r in known)
    count: dict[str, int] = {}
    for k, _ in known:
        count[k] = count.get(k, 0) + 1
    return ", ".join(f"{k} {n}건" for k, n in count.items())


def claim_rows(c: dict, src: dict) -> list[list[str]]:
    return [[c["claim_id"], ko(c["classification"]), c["text"], "" if c["value"] is None else num(c["value"]),
             c["unit"] or "", evidence_words(c["evidence_ids"], src)]]


# --- what goes in the report -------------------------------------------------------------------------------

SIGNED = ("APPROVE", "REJECT", "REQUEST_CHANGES", "NO_SCOPE_IMPACT")


def doc_section(session: Session, doc: DocumentVersion) -> tuple[list[Block], list[str]]:
    d = _doc_out(session, doc)
    src = sources(session, doc.case_id)
    v = validation.latest_run(session, doc)
    stale = validation.stale_reasons(session, v) if v else []
    checked = (f"검증 {ko(v.result)} ({v.validated_by}, {when(v.validated_at)})"
               + (" - 이후 근거가 바뀌어 다시 검증 필요" if stale else "")) if v else "검증 기록 없음"
    signed = [x for x in d["decisions"] if x["action"] in SIGNED]
    blocks = [
        ("h", (f"{STEP[doc.doc_type]} {DOC_KO.get(doc.doc_type, doc.doc_type)} - {doc.doc_type} v{doc.version} "
              f"({ko(d['status'])})")),
        ("p", f"작성 {d['author_id']} · {when(d['created_at'])} · {checked}"),
        ("t", ["번호", "구분", "내용", "값", "단위", "근거"],
         [row for c in d["claims"] for row in claim_rows(c, src)], [1, 1.2, 8, 1.4, 1.2, 3.2]),
        ("t", ["결재자", "결정", "일시"], [[x["actor_id"], ko(x["action"]), when(x["created_at"])] for x in signed],
         [2, 3, 3]),
    ]
    required = [f"{doc.doc_type} v{doc.version}", *(x["actor_id"] for x in signed if x["action"] == "APPROVE")]
    for c in d["claims"]:
        required += [c["claim_id"]]
        required += [num(c["value"])] if c["value"] is not None else []
        required += [c["unit"]] if c["unit"] else []
        # LOT numbers live in the statements; extracted PDF text only round-trips ASCII (CID font), so Hangul
        # statements are rendered but not compared (respond() also drops the ones it shows translated)
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


def appendix(session: Session, docs, src: dict) -> list[list[str]]:
    """How many records of each kind the report's claims rest on."""
    count: dict[str, int] = {}
    for e in {e for row in docs for c in _doc_out(session, row)["claims"] for e in c["evidence_ids"]}:
        k = src.get(e, ("근거", ""))[0]
        count[k] = count.get(k, 0) + 1
    return [[k, f"{n}건"] for k, n in sorted(count.items(), key=lambda x: -x[1])]


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
    shown = {k: (ko(v) if v else ("해당 없음 (NCR 단독)" if simple and k in ("D4", "D5", "D6", "D7") else "-"))
             for k, v in state.items()}
    blocks: list[Block] = [
        ("h", "요약"),
        ("p", (f"종결 {c.actor_id} · {when(c.created_at)} · 경로 {ko(s['route'])} · 종결 정책 "
              f"{s['policy']['policy_id']} v{s['policy']['version']}")),
        ("t", ["단계", "상태"], [[k, v] for k, v in shown.items()], [1, 3]),
    ]
    required = [c.actor_id, *(k for k, v in state.items() if v)]
    rows = {(d.doc_type, d.version): d for d in session.scalars(
        select(DocumentVersion).where(DocumentVersion.case_id == case_id))}
    approved = {}
    for d in s["documents"]:
        row = rows.get((d["doc_type"], d["version"]))
        if row is None or row.content_sha256 != d["content_sha256"]:
            raise HTTPException(409, f"{d['doc_type']} v{d['version']} no longer matches the closure snapshot")
        if d["status"] == "APPROVED":
            approved[d["doc_type"]] = row  # snapshot is ordered by id, so the last approved version wins
    for row in approved.values():
        b, r = doc_section(session, row)
        blocks += b
        required += r
    hyps = {h.id: h for h in causes.confirmed(session, case_id)}
    src = sources(session, case_id)
    if simple:
        blocks.append(("p", ("NCR 단독 경로: D0 판단에서 전체 8D가 필요한 불량이 없어 정책상 D0-D3만 요구되었습니다. "
                             "D4-D7(원인, 시정 조치, 효과 검증, 재발 방지)은 요구되지 않았습니다.")))
    sections = [
        ("h", "D4 확정 원인"),
        ("t", ["원인", "유형", "내용", "근거"],
         [[f"H{i}", f"{hyps[i].cause_type}/{hyps[i].category}" if i in hyps else "-",
           hyps[i].text if i in hyps else "(더 이상 확정 상태 아님)",
           evidence_words(hyps[i].evidence_ids, src) if i in hyps else ""] for i in s["confirmed_causes"]],
         [1, 2.4, 6, 3]),
        ("h", "D3 임시 조치 · D5 시정 조치"),
        ("t", ["조치", "단계", "종류", "상태"],
         [[f"ACT-{a['action_id']}", a["stage"], ko(a["type"]), ko(a["status"])] for a in s["actions"]],
         [1.4, 1, 3, 3]),
        ("h", "D6 효과 검증"),
        ("t", ["결과", "조치", "계산 결과", "판정"],
         [[f"#{x['result_id']}", f"ACT-{x['action_id']}", ko(x["computed"]), ko(x["decision"])]
          for x in s["effectiveness"]], [1, 1.4, 3, 3]),
        ("h", "D7 재발 방지"),
        ("t", ["관리 문서", "개정", "교육 이수 작업자"],
         [[p["doc_number"], f"rev {p['revision']}", ", ".join(sorted(
             {t["operator_id"] for d in session.scalars(select(PreventionDeployment).where(
                 PreventionDeployment.case_id == case_id, PreventionDeployment.doc_number == p["doc_number"],
                 PreventionDeployment.new_revision == p["revision"])) for t in d.training}))]
          for p in s["prevention"]], [3, 1.4, 4]),
    ]
    for head, table in zip(sections[::2], sections[1::2], strict=True):
        # NCR_ONLY: leave out a not-required section only when it is empty, so every recorded row is still printed
        if not simple or table[2] or head[1].startswith("D3"):
            blocks += [head, table]
    blocks += [
        ("h", "D8 종결"),
        ("p", f"결과 확인 서명: {', '.join(s['acknowledged'])}"),
        ("t", ["잔여 위험", "완화 방안", "담당"],
         [[r["risk"], r["mitigation"], r["owner"]] for r in c.residual_risks], [4, 4, 1.4]),
        ("p", f"고객 통보: {c.customer_notification_ref or '필요 없음'} · 종결 의견: {c.comment}"),
        ("p", f"감사 기록 {chain['links']}건이 내보내기 시점에 변경 없이 확인되었습니다."),
        ("h", "부록: 근거 자료"),
        ("p", "본문 각 내용의 근거가 된 원본 기록입니다. 기록별 상세는 시스템의 근거 화면에서 볼 수 있습니다."),
        ("t", ["자료", "건수"], appendix(session, approved.values(), src), [4, 1]),
    ]
    required += [f"H{i}" for i in s["confirmed_causes"]]
    required += [f"ACT-{a['action_id']}" for a in s["actions"]]
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
        canvas.drawString(15 * mm, 8 * mm, f"QualityOps AI · 합성 데이터 · {when(created)} · {author} · {d.page}쪽")

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

def make_export_router(sessions: sessionmaker, current_user: Callable[..., Actor], provider=None) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    def korean(blocks: list[Block]) -> tuple[list[Block], dict[str, str]]:
        """English record text shown in Korean: Meta translates, translate.kept() has checked every number and code
        survived; a sentence without a checked translation stays in English."""
        texts = list(dict.fromkeys(x for b in blocks for x in ([b[1]] if b[0] != "t" else [c for r in b[2] for c in r])))
        out: dict[str, str] = {}
        for _ in range(2):  # a sentence whose translation failed the check is asked once more
            todo = [t for t in texts if t not in out]
            for i in range(0, len(todo), 40):  # the screen's batch size
                out |= translate.translate(provider, todo[i:i + 40], sessions)
        return [b if b[0] != "t" else (b[0], b[1], [[plain(out.get(c, c)) for c in r] for r in b[2]], b[3])
                for b in [(b[0], plain(out.get(b[1], b[1]))) if b[0] != "t" else b for b in blocks]], out

    def respond(case_id: str, actor: Actor, fmt: str, name: str, title: str, ref: str,
                blocks: list[Block], required: list[str], doc_id: int | None = None) -> Response:
        # translated outside any write transaction: storing a new translation needs its own (SQLite: one writer)
        blocks, out = korean(blocks)
        required = [r for r in required if r not in out and plain(r) == r]  # printed in Korean instead
        created = now()
        head: list[Block] = [("p", f"사건 {case_id} · 작성 {actor.id} · {when(created)} · 합성 데이터 (실제 공장 기록 아님)")]
        data = (to_pdf if fmt == "pdf" else to_docx)(title, actor.id, created, ref, head + blocks)
        if gaps := missing_fields(data, fmt, required):
            raise HTTPException(500, f"export check failed: {len(gaps)} required fields missing from the file "
                                     f"(e.g. {gaps[:3]}); nothing exported")
        filename = f"{name}.{fmt}"
        digest = hashlib.sha256(data).hexdigest()
        with sessions.begin() as session:
            log(session, case_id, actor, "EXPORTED", f"{filename} file_sha256={digest} reference={ref} "
                f"fields_checked={len(set(required))}", doc_id)
        return Response(data, media_type=MIME[fmt], headers={
            "Content-Disposition": f'attachment; filename="{filename}"', "X-Reference-SHA256": ref,
            "X-File-SHA256": digest, "X-Fields-Checked": str(len(set(required)))})

    @router.get("/cases/{case_id}/documents/{kind:doc}/export")
    def export_document(case_id: str, kind: str, actor: Who, format: Literal["docx", "pdf"] = "pdf",
                        version: int | None = None) -> Response:
        with sessions() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind]) if version else _latest(session, case_id,
                                                                                            KINDS[kind])
            if doc is None:
                raise HTTPException(404, "Document version not found")
            require_exportable(session, doc)
            blocks, required = doc_section(session, doc)
            ref, doc_id, name = doc.content_sha256, doc.id, f"{case_id}_{doc.doc_type}_v{doc.version}"
            title = f"{doc.doc_type} v{doc.version} - 사건 {case_id} (승인)"
        return respond(case_id, actor, format, name, title, ref, blocks, required, doc_id)

    @router.get("/cases/{case_id}/report/export")
    def export_report(case_id: str, actor: Who, format: Literal["docx", "pdf"] = "pdf") -> Response:
        with sessions() as session:
            require_case(session, case_id, actor)
            c, blocks, required = case_report(session, case_id)
            simple = c.snapshot["route"] == "NCR_ONLY"  # closed early on the simple route: say so in the title
            name, title = ("NCR_closure_report", "NCR 종결 보고서") if simple else ("8D_report", "8D 보고서")
            ref = c.snapshot_sha256
        return respond(case_id, actor, format, f"{case_id}_{name}", f"{title} - 사건 {case_id} (종결)", ref, blocks,
                       required)

    return router
