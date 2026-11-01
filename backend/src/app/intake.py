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
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import docparse, intake_extract
from app.db import IntakeExtraction, IntakeFile, IntakeParse, IntakeRecord
from app.fields import FreeText
from app.model_provider import ModelProvider, ProviderError
from app.workflow import Actor, now, require_role, run_idempotent

FIXTURE_DIR = Path(__file__).with_name("fixtures") / "intake"
MAX_BYTES = 10 * 1024 * 1024  # per file
MAX_FILES = 5  # per request
MAX_PDF_PAGES = 50
MAX_ZIP_ENTRIES = 2000
MAX_UNZIPPED = 50 * 1024 * 1024  # zip-bomb guard for DOCX
PDF, DOCX = "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
RETRY = "PDF 또는 DOCX를 다시 저장해 올리거나, 내용을 직접 입력해 접수할 수 있습니다."


def _fixture_hashes() -> frozenset[str]:
    return frozenset(hashlib.sha256(p.read_bytes()).hexdigest() for p in FIXTURE_DIR.glob("*") if p.is_file())


FIXTURE_HASHES = _fixture_hashes()


def refuse(code: int, why: str) -> HTTPException:
    return HTTPException(code, f"{why} {RETRY}")


def inspect(data: bytes) -> tuple[str, dict]:
    """(media type, checks) from the bytes; raises 413/415/422 with the reason and a retry path."""
    if len(data) > MAX_BYTES:
        raise refuse(413, f"파일이 {MAX_BYTES // (1024 * 1024)}MB를 넘습니다.")
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
        if pages > MAX_PDF_PAGES:
            raise refuse(413, f"PDF가 {MAX_PDF_PAGES}쪽을 넘습니다 ({pages}쪽).")
        active = sorted({m.decode() for m in re.findall(rb"/(JavaScript|JS|OpenAction|Launch|EmbeddedFile)\b", data)})
        return PDF, {"pages": pages, "active_content": active}
    if data.startswith(b"PK"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            infos = z.infolist()
        except zipfile.BadZipFile:
            raise refuse(422, "손상된 DOCX입니다.") from None
        names = {i.filename for i in infos}
        if "word/document.xml" not in names:
            raise refuse(415, "PDF·DOCX만 접수합니다 (DOCX 본문이 없는 압축 파일).")
        if any(i.flag_bits & 0x1 for i in infos):
            raise refuse(422, "암호화된 DOCX는 열 수 없습니다.")
        if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNZIPPED:
            raise refuse(413, "압축을 풀면 허용 크기를 넘는 DOCX입니다.")
        if "word/vbaProject.bin" in names:
            raise refuse(415, "매크로가 포함된 문서는 접수하지 않습니다.")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8", "replace") \
            if "word/_rels/document.xml.rels" in names else ""
        return DOCX, {"external_links": len(re.findall(r'TargetMode="External"', rels)),
                      "embedded_objects": sum(n.startswith("word/embeddings/") for n in names)}
    raise refuse(415, "PDF·DOCX만 접수합니다 (확장자가 아닌 파일 내용으로 판단합니다).")


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
    value: str | None = Field(None, max_length=500)
    reason: FreeText  # why a person changed what the document says
    element_id: str | None = Field(None, max_length=60)
    excerpt: str | None = Field(None, max_length=500)


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
        out.append({**file_out(f), **({"elements": pp.elements, "coverage": pp.coverage} if pp else {})})
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


def analysis(provider: ModelProvider | None, inputs: list[dict]) -> tuple[str, str, dict | None, list, str | None]:
    """(mode, status, raw model output, withheld files, error). Never raises for model problems."""
    withheld = [{"file_id": i["file_id"], "name": i["name"], "reason": "외부 전송 승인 안 됨 (UNKNOWN)"}
                for i in inputs if i["data_origin"] != "SYNTHETIC"]
    if provider is None:
        return "OFFLINE", "OFFLINE", None, withheld, "Meta 미연결: 원문을 보고 직접 입력하세요."
    if len(withheld) == len(inputs):
        return "OFFLINE", "OFFLINE", None, withheld, "외부 전송이 승인된 파일이 없어 모델을 호출하지 않았습니다."
    try:
        raw, withheld = intake_extract.extract(provider, inputs)
        return provider.mode, "PARTIAL" if withheld else "OK", raw, withheld, None
    except ProviderError as exc:
        return provider.mode, "FAILED", None, withheld, f"모델 추출 실패 ({exc}). 원문을 보고 직접 입력하세요."


def add_draft_routes(router: APIRouter, sessions: sessionmaker, Who, IdemKey, provider: ModelProvider | None) -> None:
    @router.post("/intakes/{intake_id}/analyze", status_code=201)
    def analyze(intake_id: int, key: IdemKey, actor: Who):
        """Parse every file (server), then one Muse extraction over the files cleared for egress, checked by the
        server. No provider, nothing cleared, or a model failure: an empty draft for manual entry, never a guess."""
        with sessions.begin() as session:
            r = require_intake(session, intake_id, actor)
            inputs = []
            for f in session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id).order_by(IntakeFile.id)):
                pp = parsed(session, f)
                blobs = docparse.parse(f.media_type, f.content)[2] if f.data_origin == "SYNTHETIC" else {}
                inputs.append({"file_id": f.id, "name": f.name, "data_origin": f.data_origin,
                               "elements": pp.elements, "images": blobs})
        mode, status, raw, withheld, error = analysis(provider, inputs)  # outside any DB transaction
        checked = intake_extract.draft(raw, inputs)

        def run(session: Session) -> tuple[int, dict]:
            r = require_intake(session, intake_id, actor)
            v = (session.scalar(select(func.max(IntakeExtraction.version))
                                .where(IntakeExtraction.intake_id == r.id)) or 0) + 1
            session.add(IntakeExtraction(
                intake_id=r.id, version=v, kind="EXTRACTION", mode=mode, status=status,
                model=provider.model if provider and mode != "OFFLINE" else None,
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
            data, last = f.content, min(f.checks.get("pages", 0), docparse.MAX_RENDER_PAGES)
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


def make_intake_router(sessions: sessionmaker, current_user, provider: ModelProvider | None = None) -> APIRouter:
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

    add_draft_routes(router, sessions, Who, IdemKey, provider)
    return router
