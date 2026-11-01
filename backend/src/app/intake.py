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
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import IntakeFile, IntakeRecord
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


def make_intake_router(sessions: sessionmaker, current_user) -> APIRouter:
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

    return router
