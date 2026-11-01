"""IN1 (spec §23): customer-document upload keeps the original, checks it by its bytes, and creates no case."""

import base64
import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.db import Base, QualityCase
from app.intake import FIXTURE_DIR, MAX_BYTES
from app.main import create_app
from tests.v5_util import H

PDF_FIXTURE = FIXTURE_DIR / "complaint_HM-CC-2026-0417.pdf"
DOCX_FIXTURE = FIXTURE_DIR / "supplement_HM-CC-2026-0417.docx"


@pytest.fixture
def c(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'in1.db'}")
    Base.metadata.create_all(app.state.engine)
    return TestClient(app)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def upload(c, files, user="alice", headers=None):
    return c.post("/intakes", json={"files": [{"name": n, "content_base64": b64(d)} for n, d in files]},
                  headers=headers or H(user))


def own_pdf(extra: bytes = b"") -> bytes:
    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    cv.drawString(72, 750, "a customer file that is not a shipped fixture")
    cv.save()
    return buf.getvalue() + extra


def test_fixtures_are_synthetic_other_files_are_unknown_and_no_case_is_created(c):
    r = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes()), ("supp.docx", DOCX_FIXTURE.read_bytes()),
                   ("SYNTHETIC_own.pdf", own_pdf())])
    assert r.status_code == 201, r.text
    files = r.json()["files"]
    assert [f["media_type"].split("/")[-1][:3] for f in files] == ["pdf", "vnd", "pdf"]
    assert [f["data_origin"] for f in files] == ["SYNTHETIC", "SYNTHETIC", "UNKNOWN"]  # a name declares nothing
    assert files[0]["checks"]["pages"] == 1 and files[1]["checks"]["external_links"] == 0
    with Session(c.app.state.engine) as s:
        assert s.scalar(select(func.count()).select_from(QualityCase)) == 0  # T01: no case before confirmation


def test_the_original_comes_back_byte_for_byte_and_only_for_its_owner(c):
    body = upload(c, [("complaint.pdf", PDF_FIXTURE.read_bytes())]).json()
    iid, fid = body["intake_id"], body["files"][0]["file_id"]
    got = c.get(f"/intakes/{iid}/files/{fid}/content", headers=H("alice"))
    assert got.content == PDF_FIXTURE.read_bytes() and got.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in got.headers["content-disposition"]
    assert c.get(f"/intakes/{iid}", headers=H("alice")).json() == body  # T10: restored after reconnect
    assert c.get("/intakes", headers=H("alice")).json()[0]["intake_id"] == iid
    for path in (f"/intakes/{iid}", f"/intakes/{iid}/files/{fid}/content"):  # T07: another user sees nothing
        assert c.get(path, headers=H("dave")).status_code == 404
    assert c.get("/intakes", headers=H("dave")).json() == []
    assert upload(c, [("x.pdf", own_pdf())], user="bob").status_code == 403  # reviewers do not open intakes


def test_a_retried_upload_is_one_intake(c):
    headers = H("alice")
    first = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())], headers=headers).json()
    again = upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())], headers=headers).json()
    assert first == again and len(c.get("/intakes", headers=H("alice")).json()) == 1


def test_files_are_judged_by_their_bytes_and_bad_ones_are_refused_with_a_way_forward(c):
    docx_bytes = DOCX_FIXTURE.read_bytes()

    def rezip(add: dict[str, bytes] | None = None, drop: str | None = None) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for i in src.infolist():
                if i.filename != drop:
                    dst.writestr(i.filename, src.read(i.filename))
            for n, d in (add or {}).items():
                dst.writestr(n, d)
        return out.getvalue()

    cases = {
        "renamed.pdf": (b"just text pretending to be a PDF", 415),
        "broken.pdf": (b"%PDF-1.4\n garbage", 422),
        "macro.docx": (rezip({"word/vbaProject.bin": b"\0"}), 415),
        "notdocx.docx": (rezip(drop="word/document.xml"), 415),
        "bomb.docx": (rezip({"word/media/big.bin": b"\0" * (51 * 1024 * 1024)}), 413),
        "big.pdf": (own_pdf(b"%" * MAX_BYTES), 413),
    }
    for name, (data, code) in cases.items():
        r = upload(c, [(name, data)])
        assert r.status_code == code, (name, r.text)
        assert name in r.json()["detail"] and "직접 입력" in r.json()["detail"]  # T09: reason + manual path
    assert c.get("/intakes", headers=H("alice")).json() == []  # a refused upload leaves nothing behind


def test_external_links_and_active_content_are_flagged_never_followed(c):
    rels = (b'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            b'relationships"><Relationship Id="r9" Type="hyperlink" Target="http://evil.example" '
            b'TargetMode="External"/></Relationships>')
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(DOCX_FIXTURE.read_bytes())) as src, zipfile.ZipFile(out, "w") as dst:
        for i in src.infolist():
            dst.writestr(i.filename, rels if i.filename == "word/_rels/document.xml.rels" else src.read(i.filename))
    pdf = own_pdf().replace(b"/Type /Catalog", b"/Type /Catalog /OpenAction << /S /JavaScript /JS (x) >>")
    files = upload(c, [("link.docx", out.getvalue()), ("js.pdf", pdf)]).json()["files"]
    assert files[0]["checks"]["external_links"] == 1 and files[0]["data_origin"] == "UNKNOWN"
    assert {"OpenAction", "JavaScript", "JS"} <= set(files[1]["checks"]["active_content"])


def test_intake_files_are_append_only(c):
    upload(c, [("c.pdf", PDF_FIXTURE.read_bytes())])
    with Session(c.app.state.engine) as s, pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("UPDATE intake_files SET data_origin='SYNTHETIC'"))
