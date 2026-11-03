"""Customer-document intake (spec v5.8 §23), IN1: receive PDF/DOCX files, keep the originals, check them.

A file is identified by its bytes (not its extension), limited in size / pages / unpacked size, refused when
encrypted, corrupt or macro-enabled, and flagged (never run or followed) for active content or external links.
It counts as SYNTHETIC, and so may later leave for the model, only if its sha256 is one of the shipped fixtures;
anything else is UNKNOWN. Nothing here creates a Quality Case.
"""

import base64
import binascii
import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import docparse, egress, intake_extract, limits
from app.db import IntakeExtraction, IntakeFile, IntakeParse, IntakeRecord
from app.fields import FreeText, OptionalText
from app.model_provider import ModelProvider, ProviderError
from app.workflow import Actor, now, require_role, run_idempotent

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "intake"
MAX_BYTES = limits.get("MAX_UPLOAD_BYTES")
MAX_FILES = limits.get("MAX_FILES_PER_UPLOAD")
MASKED_EGRESS = True  # protected files go masked to the external model; False withholds them entirely
PDF, DOCX = "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX, CSV = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"
RETRY = "PDF 또는 DOCX를 다시 저장해 올리거나, 내용을 직접 입력해 접수할 수 있습니다."


def _fixture_hashes() -> frozenset[str]:
    return frozenset(hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURE_DIR.glob("*") if p.is_file())


FIXTURE_HASHES = _fixture_hashes()


def refuse(code: int, why: str) -> HTTPException:
    return HTTPException(code, f"{why} {RETRY}")


def zip_guard(infos: list[zipfile.ZipInfo], kind: str) -> None:
    """Zip-bomb guard (limits.py: entries, unpacked size, compression ratio per entry and in total)."""
    ratio = limits.get("MAX_COMPRESSION_RATIO")
    total, packed = sum(i.file_size for i in infos), sum(i.compress_size for i in infos)
    if len(infos) > limits.get("MAX_ZIP_ENTRIES") or total > limits.get("MAX_UNZIPPED_BYTES") \
            or total > ratio * max(packed, 1) or any(i.file_size > ratio * max(i.compress_size, 1) for i in infos):
        raise refuse(413, f"압축을 풀면 비정상적으로 커지는 {kind}입니다 (압축률·크기 한도 초과).")


def inspect(data: bytes) -> tuple[str, dict]:
    """(media type, checks) from the bytes; raises 413/415/422 with the reason and a retry path."""
    if len(data) > (cap := limits.get("MAX_UPLOAD_BYTES")):
        raise refuse(413, f"파일이 {cap // (1024 * 1024)}MB를 넘습니다.")
    if data.startswith(b"%PDF-"):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise refuse(422, "암호화된 PDF는 열 수 없습니다.")
            pages = len(reader.pages)
        except (PdfReadError, ValueError, KeyError, TypeError) as exc:
            raise refuse(422, f"손상된 PDF입니다 ({type(exc).__name__}).") from None
        active = sorted({m.decode() for m in re.findall(rb"/(JavaScript|JS|OpenAction|Launch|EmbeddedFile)\b", data)})
        return PDF, {"pages": pages, "active_content": active}
    if data.startswith(b"\xd0\xcf\x11\xe0"):  # OLE container: encrypted OOXML or legacy .doc/.xls
        raise refuse(422, "암호화되었거나 구형 Office 형식(.doc/.xls)입니다.")
    if data.startswith(b"PK"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            infos = z.infolist()
        except zipfile.BadZipFile:
            raise refuse(422, "손상된 Office 파일입니다.") from None
        names = {i.filename for i in infos}
        if "xl/workbook.xml" in names:
            if any(i.flag_bits & 0x1 for i in infos):
                raise refuse(422, "암호화된 XLSX는 열 수 없습니다.")
            zip_guard(infos, "XLSX")
            if "xl/vbaProject.bin" in names:
                raise refuse(415, "매크로가 포함된 통합 문서는 접수하지 않습니다.")
            return XLSX, {"external_links": sum(n.startswith("xl/externalLinks/") for n in names),
                          "charts": sum(n.startswith("xl/charts/chart") for n in names)}
        if "word/document.xml" not in names:
            raise refuse(415, "PDF·DOCX·XLSX·CSV만 접수합니다 (본문이 없는 압축 파일).")
        if any(i.flag_bits & 0x1 for i in infos):
            raise refuse(422, "암호화된 DOCX는 열 수 없습니다.")
        zip_guard(infos, "DOCX")
        if "word/vbaProject.bin" in names:
            raise refuse(415, "매크로가 포함된 문서는 접수하지 않습니다.")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8", "replace") \
            if "word/_rels/document.xml.rels" in names else ""
        return DOCX, {"external_links": len(re.findall(r'TargetMode="External"', rels)),
                      "embedded_objects": sum(n.startswith("word/embeddings/") for n in names)}
    if (csv_checks := docparse.sniff_csv(data)) is not None:
        return CSV, csv_checks
    raise refuse(415, "PDF·DOCX·XLSX·CSV만 접수합니다 (확장자가 아닌 파일 내용으로 판단합니다).")


class FileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # generous: a file a little over the limit gets the clear 413 from inspect(), not a schema error
    content_base64: str = Field(min_length=1, max_length=MAX_BYTES * 2)


class IntakeIn(BaseModel):
    files: list[FileIn] = Field(min_length=1, max_length=MAX_FILES)


def file_out(f: IntakeFile) -> dict:
    return {"file_id": f.id, "name": f.name, "media_type": f.media_type, "size": f.size, "sha256": f.sha256,
            "data_origin": f.data_origin, "checks": f.checks, "uploaded_by": f.uploaded_by,
            "uploaded_at": f.uploaded_at}


def intake_out(session: Session, r: IntakeRecord) -> dict:
    files = session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id).order_by(IntakeFile.id)).all()
    return {"intake_id": r.id, "owner_id": r.owner_id, "channel": r.channel, "created_at": r.created_at,
            "files": [file_out(f) for f in files]}


def add_files(session: Session, intake_id: int, files: list[FileIn], actor: Actor) -> None:
    for f in files:
        try:
            data = base64.b64decode(f.content_base64, validate=True)
        except (binascii.Error, ValueError):
            raise refuse(422, f"{f.name}: base64 내용이 올바르지 않습니다.") from None
        try:
            media, checks = inspect(data)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, f"{f.name}: {exc.detail}") from None
        sha = hashlib.sha256(data).hexdigest()
        session.add(IntakeFile(intake_id=intake_id, name=f.name, media_type=media, size=len(data), sha256=sha,
                               content=data, data_origin="SYNTHETIC" if sha in FIXTURE_HASHES else "UNKNOWN",
                               checks=checks, uploaded_by=actor.id, uploaded_at=now()))


def require_intake(session: Session, intake_id: int, actor: Actor) -> IntakeRecord:
    r = session.get(IntakeRecord, intake_id)
    if r is None or r.owner_id != actor.id:  # another user's intake does not exist for you (linked-case access: IN3)
        raise HTTPException(404, "Intake not found")
    return r


class EditIn(BaseModel):
    field: str = Field(pattern="^(" + "|".join(intake_extract.FIELDS) + ")$")
    value: OptionalText | None = None
    reason: FreeText  # why a person changed what the document says
    element_id: str | None = Field(None, max_length=60)
    excerpt: OptionalText | None = None


class EditsIn(BaseModel):
    base_version: int  # the draft version the person looked at; an older one is refused (409)
    changes: list[EditIn] = Field(min_length=1, max_length=len(intake_extract.FIELDS))


PROMPT_VERSION = hashlib.sha256((intake_extract.EXTRACT_PROMPT + str(intake_extract.EXTRACT_SCHEMA)).encode()
                                ).hexdigest()[:12]


def parsed(session: Session, f: IntakeFile) -> IntakeParse:
    """The parse of a file for the current parser version, made once (append-only)."""
    row = session.scalar(select(IntakeParse).where(IntakeParse.file_id == f.id,
                                                   IntakeParse.parser_version == docparse.PARSER_VERSION))
    if row is None:
        elements, coverage, _ = docparse.parse(f.media_type, f.content)
        row = IntakeParse(file_id=f.id, parser_version=docparse.PARSER_VERSION, elements=elements,
                          coverage=coverage, created_at=now())
        session.add(row)
        session.flush()
    return row


def latest(session: Session, intake_id: int) -> IntakeExtraction | None:
    return session.scalar(select(IntakeExtraction).where(IntakeExtraction.intake_id == intake_id)
                          .order_by(IntakeExtraction.version.desc()).limit(1))


def elements_of(session: Session, intake_id: int) -> dict[str, dict]:
    rows = session.scalars(select(IntakeParse).join(IntakeFile, IntakeParse.file_id == IntakeFile.id)
                           .where(IntakeFile.intake_id == intake_id, IntakeParse.parser_version == docparse.PARSER_VERSION))
    return {e["id"]: {**e, "file_id": pp.file_id} for pp in rows for e in pp.elements}


def draft_out(session: Session, r: IntakeRecord) -> dict:
    files = session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id).order_by(IntakeFile.id)).all()
    out = []
    for f in files:
        pp = session.scalar(select(IntakeParse).where(IntakeParse.file_id == f.id,
                                                      IntakeParse.parser_version == docparse.PARSER_VERSION))
        out.append({**file_out(f), "egress": egress.egress_view(session, f),
                    **({"elements": pp.elements, "coverage": pp.coverage} if pp else {})})
    x = latest(session, r.id)
    return {"intake_id": r.id, "files": out, "draft": None if x is None else {
        "version": x.version, "kind": x.kind, "mode": x.mode, "status": x.status, "model": x.model,
        "prompt_version": x.prompt_version, "parser_version": x.parser_version, "withheld": x.withheld,
        "error": x.error, "created_by": x.created_by, "created_at": x.created_at, "changes": x.changes, **x.draft}}


def own_file(session: Session, intake_id: int, file_id: int, actor: Actor) -> IntakeFile:
    require_intake(session, intake_id, actor)
    f = session.get(IntakeFile, file_id)
    if f is None or f.intake_id != intake_id:
        raise HTTPException(404, "File not found")
    return f


def route(provider: ModelProvider | None, local: ModelProvider | None, inputs: list[dict]):
    """Which model reads, and how protected files go: everything to an in-house model when one is configured and a
    file is protected (nothing leaves); otherwise the external model with protected files masked."""
    if local is not None and any(i["tier"] != "RAW" for i in inputs):
        return local, "RAW"
    return provider, "MASK" if MASKED_EGRESS else "WITHHOLD"


def analysis(provider: ModelProvider | None, inputs: list[dict], local: ModelProvider | None = None,
             read: str | None = None):
    """(mode, status, model output, withheld files, error, egress info). Never raises for model problems."""
    model, protected = route(provider, local, inputs)
    if model is None:
        return "OFFLINE", "OFFLINE", None, [], "Meta 미연결: 원문을 보고 직접 입력하세요.", None
    try:
        raw, withheld, info = intake_extract.extract(model, inputs, protected, read)
        return model.mode, "PARTIAL" if withheld or any(s["sent"] == "MASKED" for s in info["files"]) else "OK", \
            raw, withheld, None, info
    except ProviderError as exc:
        return model.mode, "FAILED", None, [], f"모델 추출 실패 ({exc}). 원문을 보고 직접 입력하세요.", None


def add_draft_routes(router: APIRouter, sessions: sessionmaker, Who, IdemKey, provider: ModelProvider | None,
                     local: ModelProvider | None = None) -> None:
    @router.post("/intakes/{intake_id}/analyze", status_code=201)
    def analyze(intake_id: int, key: IdemKey, actor: Who, read: Literal["WHOLE", "HYBRID"] | None = None):
        """Parse every file (server), then one Muse extraction over the files cleared for egress, checked by the
        server. No provider, nothing cleared, or a model failure: an empty draft for manual entry, never a guess."""
        with sessions.begin() as session:
            r = require_intake(session, intake_id, actor)
            inputs = []
            for f in session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id).order_by(IntakeFile.id)):
                pp = parsed(session, f)
                inputs.append({"file_id": f.id, "name": f.name, "data_origin": f.data_origin,
                               "tier": egress.tier_of(session, f), "elements": pp.elements,
                               "coverage": pp.coverage,
                               "images": docparse.parse(f.media_type, f.content)[2]})
        # read=WHOLE: a person chose to have every part read (e.g. after HYBRID left fields unfound)
        mode, status, raw, withheld, error, info = analysis(provider, inputs, local, read)  # outside any transaction
        checked = {**intake_extract.draft(raw, inputs), "egress": info}

        def run(session: Session) -> tuple[int, dict]:
            r = require_intake(session, intake_id, actor)
            v = (session.scalar(select(func.max(IntakeExtraction.version))
                                .where(IntakeExtraction.intake_id == r.id)) or 0) + 1
            session.add(IntakeExtraction(
                intake_id=r.id, version=v, kind="EXTRACTION", mode=mode, status=status,
                model=(local if mode == "LOCAL" else provider).model if mode != "OFFLINE" else None,
                prompt_version=PROMPT_VERSION if mode != "OFFLINE" else None, parser_version=docparse.PARSER_VERSION,
                draft=checked, raw=raw, withheld=withheld, changes=[], error=error, created_by=actor.id,
                created_at=now()))
            session.flush()
            return 201, draft_out(session, r)
        return run_idempotent(sessions, f"intake_analyze:{intake_id}", key, actor, run)

    @router.get("/intakes/{intake_id}/draft")
    def get_draft(intake_id: int, actor: Who) -> dict:
        with sessions() as session:
            return draft_out(session, require_intake(session, intake_id, actor))

    @router.post("/intakes/{intake_id}/draft/edits", status_code=201)
    def edit(intake_id: int, body: EditsIn, key: IdemKey, actor: Who):
        def run(session: Session) -> tuple[int, dict]:
            r = require_intake(session, intake_id, actor)
            x = latest(session, r.id)
            if x is None:
                raise HTTPException(409, "No draft yet: analyze the files first")
            if body.base_version != x.version:
                raise HTTPException(409, f"Draft changed (now v{x.version}); reload before editing")
            at, changes = now(), [c.model_dump() for c in body.changes]
            fields = intake_extract.apply_edits(x.draft["fields"], changes, elements_of(session, r.id), actor.id, at)
            session.add(IntakeExtraction(
                intake_id=r.id, version=x.version + 1, kind="USER_EDIT", mode=x.mode, status="EDITED", model=x.model,
                prompt_version=x.prompt_version, parser_version=x.parser_version, draft={**x.draft, "fields": fields},
                raw=None, withheld=x.withheld, changes=[{**c, "by": actor.id, "at": at} for c in changes],
                error=None, created_by=actor.id, created_at=at))
            session.flush()
            return 201, draft_out(session, r)
        return run_idempotent(sessions, f"intake_edit:{intake_id}", key, actor, run)

    @router.get("/intakes/{intake_id}/files/{file_id}/pages/{page}")
    def page_png(intake_id: int, file_id: int, page: int, actor: Who) -> Response:
        """A bounded render of one PDF page to check the layout; DOCX is not rendered (structural locators)."""
        with sessions() as session:
            f = own_file(session, intake_id, file_id, actor)
            if f.media_type != PDF:
                raise HTTPException(409, "DOCX is not rendered; use the paragraph/table locators")
            data, last = f.content, f.checks.get("pages", 0)
        if not 1 <= page <= last:
            raise HTTPException(404, f"Page outside 1..{last}")
        try:
            png = docparse.render_page_png(data, page)
        except docparse.RENDER_ERRORS as exc:  # a renderer failure: say so and keep the structural path
            raise HTTPException(422, f"렌더링 실패 ({type(exc).__name__}). 구조 추출 결과와 원문 다운로드로 "
                                     "확인하세요.") from None
        return Response(png, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})

    @router.get("/intakes/{intake_id}/files/{file_id}/images/{element_id}")
    def image(intake_id: int, file_id: int, element_id: str, actor: Who) -> Response:
        with sessions() as session:
            f = own_file(session, intake_id, file_id, actor)
            blobs = docparse.parse(f.media_type, f.content)[2]
        if element_id not in blobs:
            raise HTTPException(404, "Image not found")
        return Response(blobs[element_id], media_type="application/octet-stream",
                        headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"})


def add_inspection_routes(router: APIRouter, sessions: sessionmaker, Who, IdemKey,
                          provider: ModelProvider | None = None) -> None:
    """Inspection-result XLSX (spec §28): preview and checks on the intake file, a person's confirmation into a
    case, and reconciliation with the customer's documents. Only the intake's owner reads the file; only people on
    the case see or change its imports."""
    from app import inspection_layout as lay
    from app import inspection_xlsx as ix
    from app.db import InspectionImport, InspectionMappingProposal
    from app.workflow import require_case

    def xlsx(session: Session, intake_id: int, file_id: int, actor: Actor) -> IntakeFile:
        f = own_file(session, intake_id, file_id, actor)
        if f.media_type != XLSX:
            raise HTTPException(422, "검사 결과 양식은 XLSX 파일만 읽습니다 (XLS·XLSM·CSV는 지원하지 않음)")
        return f

    def view(data: bytes, sha: str, known: list[dict], table: str | None = None, chosen: dict | None = None,
             form: str | None = None, sheet: str | None = None, header_row: int | None = None) -> dict:
        """The preview with the server's table candidates and route (§29): a confirmed mapping for the same structure
        is used by itself; table: read one candidate (multi-row header, its own end row) with a proposed mapping."""
        cands = lay.tables(data)
        r = lay.route(cands, known)
        if form is None and table is None and r["route"] == "REUSED":
            form, table = r["form"], r["table"]
        c = next((t for t in cands if t["id"] == (table or r["table"])), None)
        if table and c is None:
            raise HTTPException(422, f"표 후보 {table}가 이 파일에 없습니다")
        if table:
            saved = next((f for f in known if f["name"] == form), None)
            if saved and saved.get("structure_sha"):
                out = ix.read(data, sha, None, None, chosen, known, form)
            else:
                out = ix.read(data, sha, c["sheet"], c["header_rows"][-1], chosen or ix.suggest(c["columns"]), known,
                              form or ix.FORM, c["last_row"])
            out["columns"] = c["columns"]  # multi-row headers joined: what the person compares with
        else:
            out = ix.read(data, sha, sheet, header_row, chosen, known, form)
        tables_out = [{k: t[k] for k in ("id", "range", "sheet", "header_rows", "data_rows", "columns",
                                          "merged_header")} for t in cands]
        out["layout"] = {**r, "tables": tables_out, "table": c["id"] if c else None,
                         "uncertain": lay.uncertain(c, out["mapping"], data) if c and out.get("mapping") else []}
        return out

    def chosen_mapping(mapping: str | None) -> dict | None:
        import json

        try:
            chosen = json.loads(mapping) if mapping else None
        except ValueError:
            raise HTTPException(422, "mapping must be JSON") from None
        if chosen is not None and (not isinstance(chosen, dict) or set(chosen) - set(ix.FIELDS)):
            raise HTTPException(422, f"mapping fields must be among {sorted(ix.FIELDS)}")
        return chosen

    @router.get("/intakes/{intake_id}/files/{file_id}/inspection")
    def preview(intake_id: int, file_id: int, actor: Who, sheet: str | None = None,
                header_row: int | None = None, mapping: str | None = None, form: str | None = None,
                table: str | None = None) -> dict:
        """mapping: the person's edited field -> column as JSON; the checks run again on it."""
        chosen = chosen_mapping(mapping)
        with sessions() as session:
            f = xlsx(session, intake_id, file_id, actor)
            data, sha = f.content, f.sha256
        with sessions() as session:
            known = ix.forms(session)
        return view(data, sha, known, table, chosen, form, sheet, header_row)

    @router.post("/intakes/{intake_id}/files/{file_id}/inspection/proposals", status_code=201)
    def propose(intake_id: int, file_id: int, actor: Who) -> dict:
        """AI-CFG-01: one Meta proposal over the server's table candidates (headers and types only; masked when the
        file is protected), checked by the server and recorded. A failure leaves the manual mapping open."""
        with sessions() as session:
            f = xlsx(session, intake_id, file_id, actor)
            data, sha, protected = f.content, f.sha256, egress.tier_of(session, f) != "RAW"
        cands = lay.tables(data)

        def none(status: str, code: str, msg: str) -> dict:
            return {"status": status, "mode": "OFFLINE", "model": None, "sent": {"candidates": []}, "reply": None,
                    "proposal": None, "usage": {}, "issues": [{"code": code, "message": msg}]}
        if not cands:
            res = none("INVALID", "NO_HEADER", "헤더와 데이터가 있는 표를 찾지 못했습니다: 직접 연결하세요")
        elif protected and not MASKED_EGRESS:
            res = none("WITHHELD", "WITHHELD", "보호 파일은 외부 AI에 보내지 않습니다: 직접 연결하세요")
        else:
            res = lay.propose(provider, cands, protected)  # outside any transaction
        with sessions.begin() as session:
            row = InspectionMappingProposal(intake_id=intake_id, file_id=file_id, file_sha256=sha, mode=res["mode"],
                                            model=res["model"], status=res["status"], sent=res["sent"],
                                            reply=res["reply"], proposal=res["proposal"], issues=res["issues"],
                                            usage=res["usage"], created_by=actor.id, created_at=now())
            session.add(row)
            session.flush()
            pid = row.id
            known = ix.forms(session)
        p = res["proposal"]
        out = view(data, sha, known, p["table"], p["mapping"]) if p else             view(data, sha, known, cands[0]["id"]) if cands else view(data, sha, known)
        if p:
            out["layout"]["uncertain"] = lay.uncertain(next(t for t in cands if t["id"] == p["table"]),
                                                       out["mapping"], data, p["unresolved"])
        return {"proposal_id": pid, "status": res["status"], "mode": res["mode"], "model": res["model"],
                "issues": res["issues"], "proposal": p, "preview": out}

    @router.post("/intakes/{intake_id}/files/{file_id}/inspection/mapping", status_code=201)
    def save_mapping(intake_id: int, file_id: int, body: lay.MappingIn, key: IdemKey, actor: Who):
        """AI-CFG-02: a person's confirmed mapping, saved with its table structure as a new inspection form version;
        the next file of the same structure reuses it, a changed one goes back to review."""
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            f = xlsx(session, intake_id, file_id, actor)
            return 201, lay.save(session, body, f.content, f, actor)
        return run_idempotent(sessions, f"inspection_mapping:{file_id}", key, actor, run)

    @router.get("/inspection-forms")
    def list_forms(actor: Who) -> dict:
        with sessions() as session:
            return {"forms": [{**f, "form_version": ix.form_version(f)} for f in ix.forms(session)],
                    "fields": sorted(ix.FIELDS), "admin_role": limits.ADMIN_ROLE,
                    "template": {k: [] for k in ix.FIELDS}}  # blank: fill in a company form's header words

    @router.post("/inspection-forms", status_code=201)
    def register_form(body: ix.FormIn, key: IdemKey, actor: Who):
        if actor.role != limits.ADMIN_ROLE:  # the department that owns operating settings (limits.py)
            raise HTTPException(403, f"양식 등록은 {limits.ADMIN_ROLE} 역할만 할 수 있습니다")

        def run(session: Session) -> tuple[int, dict]:
            return 201, ix.register(session, body, actor)
        return run_idempotent(sessions, "inspection_form", key, actor, run)

    @router.post("/cases/{case_id}/inspection-imports", status_code=201)
    def confirm_import(case_id: str, body: ix.ImportIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            f = xlsx(session, body.intake_id, body.file_id, actor)
            if f.sha256 != body.file_sha256:
                raise HTTPException(409, "확인한 파일과 저장된 파일이 다릅니다; 다시 미리보기 하세요")
            return ix.confirm(session, case_id, body, f, actor)
        return run_idempotent(sessions, f"inspection_import:{case_id}", key, actor, run)

    @router.get("/cases/{case_id}/inspection-imports")
    def list_imports(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            return [ix.import_out(i) for i in session.scalars(select(InspectionImport).where(
                InspectionImport.case_id == case_id).order_by(InspectionImport.id))]

    @router.get("/cases/{case_id}/inspection-imports/{import_id}/reconciliation")
    def reconciliation(case_id: str, import_id: int, actor: Who, comparable: str = "") -> dict:
        with sessions.begin() as session:  # the server's sums are stored as calculations (calculation ids)
            require_case(session, case_id, actor)
            imp = session.get(InspectionImport, import_id)
            if imp is None or imp.case_id != case_id:
                raise HTTPException(404, "Import not found")
            fields = {x for x in comparable.split(",") if x in ("inspected_qty", "defective_qty")}
            return ix.reconcile(session, case_id, imp, fields)


def make_intake_router(sessions: sessionmaker, current_user, provider: ModelProvider | None = None,
                       local: ModelProvider | None = None) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    @router.post("/intakes", status_code=201)
    def create(body: IntakeIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            r = IntakeRecord(owner_id=actor.id, idem_key=key, channel="CHAT_UPLOAD", created_at=now())
            session.add(r)
            session.flush()
            add_files(session, r.id, body.files, actor)
            session.flush()
            return 201, intake_out(session, r)
        return run_idempotent(sessions, "intake_create", key, actor, run)

    @router.post("/intakes/{intake_id}/files", status_code=201)
    def add(intake_id: int, body: IntakeIn, key: IdemKey, actor: Who):
        def run(session: Session) -> tuple[int, dict]:
            r = require_intake(session, intake_id, actor)
            add_files(session, r.id, body.files, actor)
            session.flush()
            return 201, intake_out(session, r)
        return run_idempotent(sessions, f"intake_files:{intake_id}", key, actor, run)

    @router.get("/intakes")
    def mine(actor: Who) -> list[dict]:
        with sessions() as session:
            rows = session.scalars(select(IntakeRecord).where(IntakeRecord.owner_id == actor.id)
                                   .order_by(IntakeRecord.id.desc()).limit(50)).all()
            return [intake_out(session, r) for r in rows]

    @router.get("/intakes/{intake_id}")
    def get(intake_id: int, actor: Who) -> dict:
        with sessions() as session:
            return intake_out(session, require_intake(session, intake_id, actor))

    @router.get("/intakes/{intake_id}/files/{file_id}/content")
    def content(intake_id: int, file_id: int, actor: Who) -> Response:
        """The original bytes, as a download only (never rendered inline by the browser)."""
        with sessions() as session:
            require_intake(session, intake_id, actor)
            f = session.get(IntakeFile, file_id)
            if f is None or f.intake_id != intake_id:
                raise HTTPException(404, "File not found")
            return Response(f.content, media_type=f.media_type, headers={
                "Content-Disposition": f'attachment; filename="intake-{intake_id}-{file_id}"',
                "X-Content-Type-Options": "nosniff"})

    add_draft_routes(router, sessions, Who, IdemKey, provider, local)
    add_inspection_routes(router, sessions, Who, IdemKey, provider)
    return router
