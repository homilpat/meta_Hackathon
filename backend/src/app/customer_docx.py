"""Customer DOCX forms filled with case data (spec v5.15 §30.1, DOC-OUT-01..04).

A person registers a customer's blank DOCX form. The server finds the places a value can go (an empty table cell
right of its label, a "Label: ____" paragraph, a {{placeholder}}) and gives each a slot id. A confirmed mapping for
the same slot structure is reused; otherwise Meta proposes slot -> case field id as JSON (slots and field
definitions only, never case values), checked by the server, and a person confirms it. The preview fills the
case's own current values with their source, version and approval; a missing value shows as 작성 필요 in a draft
and blocks the final file when the slot is required, as does any value that is not approved. Every export records
the form version, mapping version, case data version, file hash and the approvals it used.
"""

import hashlib
import io
import json
import re

import docx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fields import FreeText

NEEDS = "작성 필요"
PLACEHOLDER = re.compile(r"_{3,}|\{\{[^}]*\}\}|\[\s*(작성|입력|fill|enter)[^\]]*\]", re.IGNORECASE)
LABELED = re.compile(r"^(?P<label>[^:：]{1,80})[:：]\s*(?P<rest>.*)$")


# --- slots -----------------------------------------------------------------------------------------------------
def _blank(text: str) -> bool:
    t = text.strip()
    return not t or bool(PLACEHOLDER.fullmatch(t))


# text that may be a blank or may be a real answer ("-", "TBD", "N/A"): a slot with certain=False, which the AI
# proposal maps to a field or to NONE and a person confirms (it is never filled unless mapped)
MAYBE = re.compile(r"^(-|–|—|\.|tbd|t\.b\.d\.?|n/?a|해당\s*없음|미정|추후\s*기재|\(\s*\))$", re.IGNORECASE)
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _texts(el) -> str:
    return "".join(t.text or "" for t in el.iter(f"{W}t"))


def _sdt_slots(d) -> list[dict]:
    """Content controls (w:sdt), anywhere: a control showing its placeholder or holding a blank is a slot, labeled by
    its alias or tag, else by the text around it."""
    out = []
    for k, sdt in enumerate(d.element.body.iter(f"{W}sdt")):
        pr = sdt.find(f"{W}sdtPr")
        content = sdt.find(f"{W}sdtContent")
        if pr is None or content is None:
            continue
        shown = _texts(content).strip()
        placeholder = pr.find(f"{W}showingPlcHdr") is not None
        if not (placeholder or _blank(shown) or MAYBE.fullmatch(shown)):
            continue
        alias = next((e.get(f"{W}val") for e in (pr.find(f"{W}alias"), pr.find(f"{W}tag")) if e is not None
                      and e.get(f"{W}val")), "")
        around = _texts(sdt.getparent()).replace(shown, "").strip().rstrip(":：").strip() if not alias else ""
        if label := (alias or around)[:80]:
            out.append({"id": f"S{k}", "kind": "control", "label": label, "context": "",
                        **({} if placeholder or _blank(shown) else {"certain": False})})
    return out


def _textbox_slots(d) -> list[dict]:
    """Paragraphs inside text boxes (w:txbxContent), read like body paragraphs. Word writes a text box twice
    (mc:Choice and a VML mc:Fallback); the fallback copy is skipped."""
    out = []
    boxes = [b for b in d.element.body.iter(f"{W}txbxContent")
             if not any(a.tag.endswith("}Fallback") for a in b.iterancestors())]
    for k, box in enumerate(boxes):
        for n, par in enumerate(box.iter(f"{W}p")):
            t = _texts(par).strip()
            m = LABELED.match(t)
            if m and (_blank(m.group("rest")) or MAYBE.fullmatch(m.group("rest").strip())):
                out.append({"id": f"X{k}.P{n}", "kind": "textbox", "label": m.group("label").strip(), "context": "",
                            **({} if _blank(m.group("rest")) else {"certain": False})})
    return out


def slots(data: bytes) -> list[dict]:
    """Fillable places, in document order: T<table>.R<row>.C<col> for an empty cell after a label cell in its row
    (or under a header cell), P<paragraph> for a labeled blank or a placeholder paragraph, S<n> for a content
    control, X<box>.P<n> for a paragraph in a text box. A "-"/TBD/N/A answer is a slot with certain=False."""
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 (any broken file: say why and stop)
        raise HTTPException(422, f"DOCX를 읽을 수 없습니다 ({type(exc).__name__})") from None
    out, heading = [], ""
    for i, p in enumerate(d.paragraphs):
        t = p.text.strip()
        if not t:
            continue
        m = LABELED.match(t)
        if m and (_blank(m.group("rest")) or MAYBE.fullmatch(m.group("rest").strip())):
            out.append({"id": f"P{i}", "kind": "paragraph", "label": m.group("label").strip(), "context": heading,
                        **({} if _blank(m.group("rest")) else {"certain": False})})
        elif PLACEHOLDER.search(t):
            out.append({"id": f"P{i}", "kind": "paragraph", "label": PLACEHOLDER.sub("…", t), "context": heading})
        else:
            heading = t[:80]
    for ti, table in enumerate(d.tables):
        rows = table.rows
        header = [c.text.strip() for c in rows[0].cells] if rows else []
        for ri, row in enumerate(rows):
            seen = set()
            cells = row.cells
            for ci, cell in enumerate(cells):
                if cell._tc in seen:
                    continue  # a merged cell repeats in row.cells
                seen.add(cell._tc)
                maybe = bool(MAYBE.fullmatch(cell.text.strip()))
                if not (_blank(cell.text) or maybe):
                    continue
                left = next((cells[k].text.strip() for k in range(ci - 1, -1, -1)
                             if cells[k]._tc is not cell._tc and cells[k].text.strip()), "")
                above = header[ci] if ri > 0 and ci < len(header) else ""
                label = left if left and not _blank(left) and not MAYBE.fullmatch(left) else above
                if label:
                    out.append({"id": f"T{ti}.R{ri}.C{ci}", "kind": "cell", "label": label,
                                "context": above if label == left and above != left else "",
                                **({"certain": False} if maybe else {})})
    return out + _sdt_slots(d) + _textbox_slots(d)


def structure_sha(sl: list[dict]) -> str:
    return hashlib.sha256(json.dumps([[s["id"], s["label"], s["context"]] for s in sl],
                                     ensure_ascii=False).encode()).hexdigest()


# --- case fields: the only things a slot may show --------------------------------------------------------------
FIELDS = {  # id -> (label, meaning). Occurrence and escape causes are different fields, never one "cause".
    "case.id": ("사건 번호", "the case id"),
    "case.customer": ("고객사", "the customer of the case"),
    "case.part_number": ("품번", "part number the person confirmed at intake"),
    "case.lot": ("LOT", "LOT number(s) of the case"),
    "case.phenomenon": ("불량 현상", "the defect phenomenon the customer reported"),
    "d2.problem": ("D2 문제 기술", "statements of the approved NCR (problem description)"),
    "d3.containment": ("D3 봉쇄 조치", "statements of the approved containment document"),
    "d4.occurrence_cause": ("D4 발생 원인", "confirmed root cause of occurrence (why it was made)"),
    "d4.escape_cause": ("D4 유출 원인", "confirmed cause of non-detection (why it escaped / was not detected)"),
    "d4.systemic_cause": ("D4 시스템 원인", "confirmed systemic cause"),
    "d4.rca_summary": ("D4 원인 분석 문서", "statements of the approved RCA document"),
    "d2.approved_by": ("D2 승인자", "who approved the NCR, and when"),
    "d3.approved_by": ("D3 승인자", "who approved the containment, and when"),
    "d4.approved_by": ("D4 승인자", "who approved the RCA, and when"),
    "d2.approved_on": ("D2 승인일", "date the NCR was approved (a date only)"),
    "d3.approved_on": ("D3 승인일", "date the containment was approved (a date only)"),
    "d4.approved_on": ("D4 승인일", "date the RCA was approved (a date only)"),
    "case.closure": ("종결 상태", "D8 closure decision and date"),
}
# how a value is written into a slot: the AI picks one id from the label's own hint, the server converts (dates
# inside the value; ISO in the case data), a person confirms; a value the format cannot take blocks the final file
FORMATS = {"AS_IS": None, "DATE_ISO": "%Y-%m-%d", "DATE_DOT": "%Y.%m.%d", "DATE_SLASH_US": "%m/%d/%Y",
           "DATE_SLASH_EU": "%d/%m/%Y", "DATE_KO": "%Y년 %m월 %d일"}
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def apply_format(value, fmt: str) -> tuple[str, bool]:
    """(text, converted): AS_IS keeps the value; a date format rewrites every ISO date in it, and a value with none
    cannot take that format."""
    from datetime import date

    text = str(value)
    if not FORMATS.get(fmt):
        return text, True
    if not ISO_DATE.search(text):
        return text, False
    return ISO_DATE.sub(lambda m: date.fromisoformat(m.group(0)).strftime(FORMATS[fmt]), text), True


SUBMISSION = ("case.id", "case.customer", "d2.problem", "d3.containment", "d4.occurrence_cause", "d4.escape_cause")


def customer_of(session: Session, case_id: str) -> str | None:
    from app.db import IntakeCaseLink, IntakeExtraction, ProcessContext

    pc = session.scalar(select(ProcessContext).where(ProcessContext.case_id == case_id))
    if pc:
        return pc.customer
    for link in session.scalars(select(IntakeCaseLink).where(IntakeCaseLink.case_id == case_id)):
        x = session.scalar(select(IntakeExtraction).where(IntakeExtraction.intake_id == link.intake_id,
                                                          IntakeExtraction.version == link.extraction_version))
        v = ((x.draft or {}).get("fields", {}).get("customer") or {}).get("value") if x else None
        if v:
            return v
    return None


def case_values(session: Session, case_id: str) -> dict[str, dict]:
    """field id -> {value, source, version, approved}; None value = the case has nothing for it yet."""
    from app import causes
    from app.db import (
        ApprovalEvent,
        Closure,
        DocumentClaim,
        DocumentVersion,
        IntakeCaseLink,
        IntakeExtraction,
        QualityCase,
        SourceEvent,
    )

    case = session.get(QualityCase, case_id)
    out: dict[str, dict] = {k: {"value": None, "source": None, "version": None, "approved": False} for k in FIELDS}

    def put(k, value, source, version, approved):
        out[k] = {"value": value, "source": source, "version": version, "approved": approved}

    put("case.id", case.id, "case", case.created_at, True)
    if cust := customer_of(session, case_id):
        put("case.customer", cust, "case context / confirmed intake", None, True)
    for link in session.scalars(select(IntakeCaseLink).where(IntakeCaseLink.case_id == case_id)
                                .order_by(IntakeCaseLink.id)):
        x = session.scalar(select(IntakeExtraction).where(IntakeExtraction.intake_id == link.intake_id,
                                                          IntakeExtraction.version == link.extraction_version))
        for k, name in (("case.part_number", "part_number"), ("case.lot", "lot"), ("case.phenomenon", "phenomenon")):
            v = ((x.draft or {}).get("fields", {}).get(name) or {}) if x else {}
            if v.get("value") and out[k]["value"] is None:  # confirmed by a person at intake
                put(k, v["value"], f"intake {link.intake_id} draft v{link.extraction_version}",
                    f"intake:{link.intake_id}:v{link.extraction_version}", True)
    if out["case.lot"]["value"] is None:
        lots = sorted({json.loads(e.raw_json).get("lot_id") for e in session.scalars(select(SourceEvent).where(
            SourceEvent.case_id == case_id, SourceEvent.entity_type == "lots"))} - {None})
        if lots:
            put("case.lot", ", ".join(lots), "line data (lots)", None, True)
    for dtype, key in (("NCR", "d2"), ("CONTAINMENT", "d3"), ("RCA", "d4")):
        docs = session.scalars(select(DocumentVersion).where(DocumentVersion.case_id == case_id,
                                                             DocumentVersion.doc_type == dtype)
                               .order_by(DocumentVersion.version.desc())).all()
        doc = next((d for d in docs if d.status == "APPROVED"), docs[0] if docs else None)
        if doc is None:
            continue
        text = " ".join(c.text for c in session.scalars(select(DocumentClaim).where(
            DocumentClaim.document_version_id == doc.id).order_by(DocumentClaim.id)))
        field = {"d2": "d2.problem", "d3": "d3.containment", "d4": "d4.rca_summary"}[key]
        ver = f"{dtype} v{doc.version} {doc.content_sha256[:12]}"
        put(field, text or None, f"{dtype} v{doc.version} ({doc.status})", ver, doc.status == "APPROVED")
        ap = session.scalar(select(ApprovalEvent).where(ApprovalEvent.document_version_id == doc.id,
                                                        ApprovalEvent.action == "APPROVE")
                            .order_by(ApprovalEvent.id.desc()).limit(1))
        if ap and doc.status == "APPROVED":
            put(f"{key}.approved_by", f"{ap.actor_id} ({ap.created_at[:10]})", f"approval #{ap.id}", ver, True)
            put(f"{key}.approved_on", ap.created_at[:10], f"approval #{ap.id}", ver, True)
    by_type: dict[str, list] = {}
    for h in causes.confirmed(session, case_id):
        by_type.setdefault(h.cause_type, []).append(h)
    for t, k in (("OCCURRENCE", "d4.occurrence_cause"), ("NON_DETECTION", "d4.escape_cause"),
                 ("SYSTEMIC", "d4.systemic_cause")):
        if hs := by_type.get(t):
            put(k, " / ".join(h.text for h in hs), "confirmed cause " + ", ".join(f"H{h.id}" for h in hs),
                ",".join(f"H{h.id}" for h in hs), True)
    c = session.scalar(select(Closure).where(Closure.case_id == case_id).order_by(Closure.id.desc()).limit(1))
    if c:
        put("case.closure", f"{c.decision} ({c.created_at[:10]})", f"closure #{c.id}", c.snapshot_sha256[:12],
            c.decision == "CLOSED")
    return out


def data_version(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# --- the model's proposal --------------------------------------------------------------------------------------
PROMPT = """You map the fillable slots of a customer's quality report form to case field ids.
The server found the slots (id, label, context) and lists the allowed fields (id, label, meaning). You see no case
values. For every slot give one field id or "NONE". Root cause of occurrence (why the defect was made) and cause of
non-detection or escape (why it was not caught) are different fields: never put one in place of the other. A slot
that only says "Root Cause" with no occurrence/escape hint maps to d4.occurrence_cause. Use NONE and list the slot
in unresolved when you are not sure. A slot with "certain": false holds text such as "-", "TBD" or "N/A" that may be
a blank to fill or the customer's real answer: map it only when the label clearly asks for a case value. For every
slot also pick a format id: a date format only when the label itself shows one (e.g. "YYYY.MM.DD" -> DATE_DOT,
"MM/DD/YYYY" -> DATE_SLASH_US, "년 월 일" -> DATE_KO), else AS_IS. Give a short reason per slot."""


def schema(sl: list[dict]) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "docx_mapping", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["slots", "unresolved"],
        "properties": {
            "slots": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["slot_id", "field_id", "format", "reason"],
                "properties": {"slot_id": {"type": "string", "enum": [s["id"] for s in sl]},
                               "field_id": {"type": "string", "enum": [*FIELDS, "NONE"]},
                               "format": {"type": "string", "enum": list(FORMATS)},
                               "reason": {"type": "string"}}}},
            "unresolved": {"type": "array", "items": {"type": "string", "enum": [s["id"] for s in sl]}}}}}}


def propose(provider, sl: list[dict], protected: bool) -> dict:
    """One structured call over slots and field definitions; the server keeps only known slot and field ids."""
    from app.egress import MASK_NOTE, Masker
    from app.inspection_layout import header_terms, languages, mask_header
    from app.model_provider import ProviderError

    masker = Masker()
    terms = header_terms(languages([s["label"] for s in sl])) if protected else set()

    def m(t):
        return mask_header(t, terms, masker) if protected else t
    sent = {"slots": [{"id": s["id"], "kind": s["kind"], "label": m(s["label"]), "context": m(s["context"]),
                       "certain": s.get("certain", True)} for s in sl],
            "formats": list(FORMATS),
            "fields": [{"id": k, "label": v[0], "meaning": v[1]} for k, v in FIELDS.items()]}
    base = {"sent": sent, "reply": None, "proposal": None, "usage": {}}
    if provider is None:
        return {**base, "status": "OFFLINE", "mode": "OFFLINE", "model": None,
                "issues": [{"code": "OFFLINE", "message": "Meta 미연결: 칸을 직접 연결하세요"}]}
    try:
        r = provider.chat([{"role": "system", "content": PROMPT + ("\n" + MASK_NOTE if protected else "")},
                           {"role": "user", "content": json.dumps(sent, ensure_ascii=False)}], [],
                          response_format=schema(sl))
        reply = masker.unmask_obj(json.loads(r["message"].get("content") or ""))
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        return {**base, "status": "FAILED", "mode": provider.mode, "model": provider.model,
                "issues": [{"code": "MODEL_FAILED", "message": f"AI 제안 실패 ({type(exc).__name__}): 칸을 직접 연결하세요"}]}
    ids, mapping, reasons, formats, issues = {s["id"] for s in sl}, {}, {}, {}, []
    for x in (reply.get("slots") if isinstance(reply, dict) else None) or []:
        if not isinstance(x, dict):
            continue
        sid, fid = x.get("slot_id"), x.get("field_id")
        if sid not in ids or (fid != "NONE" and fid not in FIELDS):
            issues.append({"code": "OUT_OF_RANGE", "message": f"서버가 찾은 칸·허용 필드가 아님: {sid} -> {fid}"})
            continue
        mapping.setdefault(sid, None if fid == "NONE" else fid)
        reasons.setdefault(sid, str(x.get("reason", ""))[:300])
        formats.setdefault(sid, x.get("format") if x.get("format") in FORMATS else "AS_IS")
    unresolved = sorted({u for u in (reply.get("unresolved") or []) if u in ids} | (ids - set(mapping)))
    return {**base, "status": "OK", "mode": provider.mode, "model": provider.model, "reply": reply,
            "usage": r.get("usage") or {}, "issues": issues,
            "proposal": {"mapping": {s["id"]: mapping.get(s["id"]) for s in sl}, "reasons": reasons,
                         "formats": {s["id"]: formats.get(s["id"], "AS_IS") for s in sl},
                         "unresolved": unresolved}}


# --- register, confirm, fill -----------------------------------------------------------------------------------
class TemplateIn(BaseModel):
    customer: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)
    content_base64: str = Field(min_length=1, max_length=20_000_000)
    reason: FreeText


class MappingIn(BaseModel):
    mapping: dict[str, str | None]
    required: list[str] = []  # slots that must be filled for the final file (default: those mapped to SUBMISSION)
    formats: dict[str, str] = {}  # slot -> FORMATS id; a slot left out is AS_IS
    proposal_id: int | None = None
    reason: FreeText


def latest_mapping(session: Session, template) -> object | None:
    from app.db import CustomerTemplateMapping

    return session.scalar(select(CustomerTemplateMapping).where(CustomerTemplateMapping.template_id == template.id)
                          .order_by(CustomerTemplateMapping.version.desc()).limit(1))


def reusable(session: Session, template) -> object | None:
    """A confirmed mapping of an earlier version of this form whose slot structure is the same (DOC-OUT-01/04)."""
    from app.db import CustomerTemplate, CustomerTemplateMapping

    for t in session.scalars(select(CustomerTemplate).where(CustomerTemplate.customer == template.customer,
                                                            CustomerTemplate.name == template.name,
                                                            CustomerTemplate.id != template.id)
                             .order_by(CustomerTemplate.version.desc())):
        if t.structure_sha == template.structure_sha:
            m = session.scalar(select(CustomerTemplateMapping).where(CustomerTemplateMapping.template_id == t.id)
                               .order_by(CustomerTemplateMapping.version.desc()).limit(1))
            if m:
                return m
    return None


def template_out(session: Session, t) -> dict:
    m = latest_mapping(session, t)
    reuse = None if m else reusable(session, t)
    route = "CONFIRMED" if m else "REUSABLE" if reuse else "NEEDS_REVIEW"
    return {"template_id": t.id, "customer": t.customer, "name": t.name, "version": t.version,
            "sha256": t.sha256, "structure_sha": t.structure_sha, "data_origin": t.data_origin, "slots": t.slots,
            "created_by": t.created_by, "created_at": t.created_at, "reason": t.reason, "route": route,
            "mapping": mapping_out(m or reuse) if (m or reuse) else None, "formats": list(FORMATS),
            "fields": [{"id": k, "label": v[0], "meaning": v[1], "submission": k in SUBMISSION}
                       for k, v in FIELDS.items()]}


def mapping_out(m) -> dict:
    return {"mapping_id": m.id, "template_id": m.template_id, "version": m.version, "mapping": m.mapping,
            "formats": m.formats or {},
            "required": m.required, "edits": m.edits, "proposal_id": m.proposal_id, "created_by": m.created_by,
            "created_at": m.created_at, "reason": m.reason}


def register(session: Session, body: TemplateIn, actor) -> tuple[int, dict]:
    import base64

    from app.db import CustomerTemplate
    from app.intake import FIXTURE_HASHES
    from app.workflow import now

    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except ValueError:
        raise HTTPException(422, "content_base64 is not base64") from None
    sl = slots(data)
    if not sl:
        raise HTTPException(422, "채울 칸을 찾지 못했습니다 (빈 표 칸, '항목: ____' 문단, {{자리표시}})")
    sha = hashlib.sha256(data).hexdigest()
    prev = session.scalar(select(CustomerTemplate).where(CustomerTemplate.customer == body.customer,
                                                         CustomerTemplate.name == body.name)
                          .order_by(CustomerTemplate.version.desc()).limit(1))
    if prev and prev.sha256 == sha:
        return 200, template_out(session, prev)  # the same file again: the same version
    t = CustomerTemplate(customer=body.customer, name=body.name, version=(prev.version + 1) if prev else 1,
                         content=data, sha256=sha, slots=sl, structure_sha=structure_sha(sl),
                         data_origin="SYNTHETIC" if sha in FIXTURE_HASHES else "UNKNOWN", reason=body.reason,
                         created_by=actor.id, created_at=now())
    session.add(t)
    session.flush()
    return 201, template_out(session, t)


def check_mapping(t, mapping: dict, required: list[str], formats: dict | None = None) -> None:
    ids = {s["id"] for s in t.slots}
    if bad := sorted(set(mapping) - ids):
        raise HTTPException(422, f"이 양식에 없는 칸 ID: {bad[:5]}")
    if bad := sorted({f for f in mapping.values() if f} - set(FIELDS)):
        raise HTTPException(422, f"허용되지 않은 사건 필드 ID: {bad[:5]}")
    if bad := sorted(set(required) - ids):
        raise HTTPException(422, f"이 양식에 없는 필수 칸 ID: {bad[:5]}")
    if bad := [s for s in required if not mapping.get(s)]:
        raise HTTPException(422, f"필수 칸이 사건 필드에 연결되지 않았습니다: {bad[:5]}")
    if bad := sorted(k for k, v in (formats or {}).items() if k not in ids or v not in FORMATS):
        raise HTTPException(422, f"없는 칸이거나 허용되지 않은 형식: {bad[:5]} (가능: {list(FORMATS)})")


def confirm(session: Session, t, body: MappingIn, actor) -> dict:
    from app.db import CustomerTemplateMapping, CustomerTemplateProposal
    from app.workflow import now

    mapping = {s["id"]: body.mapping.get(s["id"]) or None for s in t.slots} | \
        {k: v for k, v in body.mapping.items() if k not in {s["id"] for s in t.slots}}
    required = body.required or [s for s, f in mapping.items() if f in SUBMISSION]
    formats = {k: v for k, v in body.formats.items() if v != "AS_IS"}
    check_mapping(t, mapping, required, formats)
    prop = session.get(CustomerTemplateProposal, body.proposal_id) if body.proposal_id else None
    if body.proposal_id and (prop is None or prop.template_id != t.id):
        raise HTTPException(422, "이 양식의 제안이 아닙니다")
    edits = sum(1 for s in mapping if (prop.proposal or {}).get("mapping", {}).get(s) != mapping[s]) \
        if prop and prop.proposal else None
    prev = latest_mapping(session, t)
    m = CustomerTemplateMapping(template_id=t.id, version=(prev.version + 1) if prev else 1, mapping=mapping,
                                required=required, formats=formats, proposal_id=prop.id if prop else None,
                                edits=edits,
                                reason=body.reason, created_by=actor.id, created_at=now())
    session.add(m)
    session.flush()
    return mapping_out(m)


def fill_view(session: Session, t, m, case_id: str) -> dict:
    """Every slot with the case's own current value, its source and approval, or 작성 필요; and what blocks the
    final file."""
    values = case_values(session, case_id)
    rows, blocks = [], []
    for s in t.slots:
        f = m.mapping.get(s["id"]) if m else None
        v = values.get(f) if f else None
        status = "UNMAPPED" if not f else "MISSING" if v["value"] is None else "UNAPPROVED" if not v["approved"] \
            else "FILLED"
        req = bool(m) and s["id"] in m.required
        fmt = ((m.formats or {}) if m else {}).get(s["id"], "AS_IS")
        shown, converted = apply_format(v["value"], fmt) if status in ("FILLED", "UNAPPROVED") else (None, True)
        if not converted:
            blocks.append({"slot": s["id"], "code": "FORMAT_UNCONVERTIBLE",
                           "message": f"{s['label']}: 값 {str(v['value'])[:40]!r}을 형식 {fmt}로 바꿀 수 없습니다"})
        if req and status == "MISSING":
            blocks.append({"slot": s["id"], "code": "REQUIRED_MISSING", "message": f"{s['label']}: 제출 필수 값이 없습니다 ({FIELDS[f][0]})"})
        if status == "UNAPPROVED":
            blocks.append({"slot": s["id"], "code": "NOT_APPROVED", "message": f"{s['label']}: 승인되지 않은 값 ({v['source']})"})
        rows.append({**s, "field": f, "field_label": FIELDS[f][0] if f else None, "required": req, "status": status,
                     "value": v["value"] if v else None, "source": v["source"] if v else None,
                     "version": v["version"] if v else None, "format": fmt, "converted": converted,
                     "shown": (shown if status in ("FILLED", "UNAPPROVED") else NEEDS if f else "")})
    if m is None:
        blocks.insert(0, {"code": "NO_CONFIRMED_MAPPING", "message": "확정된 매핑이 없습니다 (재검토 필요)"})
    return {"template_id": t.id, "template_version": t.version, "customer": t.customer, "case_id": case_id,
            "mapping_version": m.version if m else None, "mapping_id": m.id if m else None,
            "case_data_version": data_version(values), "slots": rows, "final_blocked_by": blocks}


def render(t, view: dict, final: bool = False) -> bytes:
    """The customer's own file with the slot values written in; nothing else in it changes. A final file leaves an
    optional slot without a value blank (a required one never gets here: fill_view blocks it)."""
    d = docx.Document(io.BytesIO(t.content))
    by = {s["id"]: {**s, "shown": "" if final and s["status"] == "MISSING" else s["shown"]} for s in view["slots"]}

    def write(p, text):
        runs = p.runs
        if runs:
            runs[0].text = text
            for r in runs[1:]:
                r.text = ""
        else:
            p.add_run(text)
    def labeled(p, s):
        m = LABELED.match(p.text.strip())
        rest = m.group("rest").strip() if m else ""
        write(p, f"{m.group('label').strip()}: {s['shown']}" if m and (_blank(rest) or MAYBE.fullmatch(rest))
              else PLACEHOLDER.sub(str(s["shown"]), p.text))
    for i, p in enumerate(d.paragraphs):
        s = by.get(f"P{i}")
        if s and s["shown"]:
            labeled(p, s)
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    for k, sdt in enumerate(d.element.body.iter(f"{W}sdt")):
        s = by.get(f"S{k}")
        content = sdt.find(f"{W}sdtContent")
        if not (s and s["shown"]) or content is None:
            continue
        ts = list(content.iter(f"{W}t"))
        if ts:
            ts[0].text = str(s["shown"])
            for rest in ts[1:]:
                rest.text = ""
        else:
            r, wt = OxmlElement("w:r"), OxmlElement("w:t")
            wt.text = str(s["shown"])
            r.append(wt)
            (content.find(f"{W}p") if content.find(f"{W}p") is not None else content).append(r)
        if (ph := sdt.find(f"{W}sdtPr/{W}showingPlcHdr")) is not None:
            ph.getparent().remove(ph)  # the control now holds a value, not its placeholder
    boxes = [b for b in d.element.body.iter(f"{W}txbxContent")
             if not any(a.tag.endswith("}Fallback") for a in b.iterancestors())]
    for k, box in enumerate(boxes):
        for n, par in enumerate(box.iter(f"{W}p")):
            s = by.get(f"X{k}.P{n}")
            if s and s["shown"]:
                labeled(Paragraph(par, None), s)
    for ti, table in enumerate(d.tables):
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                s = by.get(f"T{ti}.R{ri}.C{ci}")
                if s and s["shown"]:
                    write(cell.paragraphs[0], str(s["shown"]))
                    for extra in cell.paragraphs[1:]:
                        write(extra, "")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def text_of(data: bytes) -> str:
    """All text a reader sees, content controls and text boxes included (read back after rendering)."""
    d = docx.Document(io.BytesIO(data))
    return "\n".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells]
                     + [_texts(p) for p in d.element.body.iter(f"{W}p")])
