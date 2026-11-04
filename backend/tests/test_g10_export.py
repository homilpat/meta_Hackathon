"""G10: approved documents and the closed 8D case as real DOCX/PDF files (MASTER TC-D-01 / TC-D-02).

Files are opened with independent parsers (python-docx, pypdf) and compared with the snapshot they claim to show.
"""

import io

import docx
import pytest
from pypdf import PdfReader

from app import export
from tests.test_c_e2e import success
from tests.v5_util import H, line_client, ok, ready_to_close


def opened(r, fmt: str) -> str:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == export.MIME[fmt]
    if fmt == "docx":
        d = docx.Document(io.BytesIO(r.content))
        assert d.core_properties.author == "bob"
        cells = [cell.text for t in d.tables for row in t.rows for cell in row.cells]
        return "".join([p.text for p in d.paragraphs] + cells)
    pdf = PdfReader(io.BytesIO(r.content))
    assert pdf.metadata.author == "bob" and len(pdf.pages) >= 1
    return "".join(p.extract_text() for p in pdf.pages)


def squash(s: str) -> str:
    return "".join(s.split())


def events(c, name: str) -> list[dict]:
    return [e for e in c.get("/cases/L/timeline", headers=H("bob")).json() if e.get("event") == name]


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def test_closed_case_report_and_approved_document_match_the_snapshot(c):  # TC-D-01
    closed = success(c)
    snap, ref = closed["snapshot"], closed["snapshot_sha256"]
    ncr2 = ok(c.get("/cases/L/ncr/2", headers=H("bob")), 200)
    for fmt in ("docx", "pdf"):
        r = c.get(f"/cases/L/report/export?format={fmt}", headers=H("bob"))
        text = squash(opened(r, fmt))
        assert f'filename="L_8D_report.{fmt}"' in r.headers["content-disposition"]
        assert r.headers["x-reference-sha256"] == ref and ref not in text  # readers get words, not hashes
        assert not any(d["content_sha256"] in text for d in snap["documents"])
        for cl in ncr2["claims"]:  # the edited, approved NCR v2: statements (LOTs), values, units
            assert squash(export.plain(cl["text"])) in text and not any(e in text for e in cl["evidence_ids"])
            if cl["value"] is not None:
                assert export.num(cl["value"]) in text
        assert "(alllots)" in text  # the Docs edit is what was exported
        assert all(squash(f"{k}{export.ko(v)}") in text for k, v in snap["state"].items() if v) and "D8종결" in text
        assert all(f"ACT-{a['action_id']}" in text for a in snap["actions"])
        assert all(f"H{h}" in text for h in snap["confirmed_causes"])
        assert all(squash(f"{p['doc_number']}rev{p['revision']}") in text for p in snap["prevention"])
        assert "bob" in text and "EQ-STN-2" in text  # a few records are named by their row id
        # the approved NCR on its own
        r = c.get(f"/cases/L/documents/ncr/export?format={fmt}", headers=H("bob"))
        text = squash(opened(r, fmt))
        assert r.headers["x-reference-sha256"] == ncr2["content_sha256"] and "NCRv2" in text
        assert ncr2["content_sha256"] not in text
        assert f'filename="L_NCR_v2.{fmt}"' in r.headers["content-disposition"]
    assert len(events(c, "EXPORTED")) == 4
    assert c.get("/audit/verify", headers=H("bob")).json()["ok"] is True


def test_unapproved_stale_or_replaced_documents_are_not_exported(c):  # TC-D-02
    ready_to_close(c)
    assert c.get("/cases/L/report/export", headers=H("bob")).status_code == 409  # not CLOSED
    v1 = ok(c.get("/cases/L/ncr/1", headers=H("alice")), 200)
    e = ok(c.post("/cases/L/ncr/1/edits", headers=H("alice"), json={
        "expected_sha256": v1["content_sha256"], "reason": "clearer wording",
        "changes": [{"claim_id": "C1", "text": v1["claims"][0]["text"] + " (all lots)"}]}))
    r = c.get("/cases/L/documents/ncr/export", headers=H("bob"))  # latest is the v2 draft
    assert r.status_code == 409 and "DRAFT" in r.json()["detail"]
    assert c.get("/cases/L/documents/ncr/export?version=1", headers=H("bob")).status_code == 200  # still approved
    ok(c.post("/cases/L/ncr/2/request-review", json={"reviewer_id": "bob"}, headers=H("alice")), 200)
    ok(c.post("/cases/L/ncr/2/decision", headers=H("bob"), json={
        "decision": "APPROVE", "comment": "ok", "content_sha256": e["content_sha256"]}), 200)
    r = c.get("/cases/L/documents/ncr/export?version=1", headers=H("bob"))
    assert r.status_code == 409 and "replaced by approved v2" in r.json()["detail"]
    r = c.get("/cases/L/documents/containment/export", headers=H("bob"))  # approved on NCR v1
    assert r.status_code == 409 and "BASIS_CHANGED" in r.json()["detail"]
    assert len(events(c, "EXPORTED")) == 1


def test_file_missing_a_snapshot_field_is_not_returned(c, monkeypatch):
    ready_to_close(c)
    real = export.doc_section

    def with_extra_field(session, doc):
        blocks, required = real(session, doc)
        return blocks, [*required, "LOT-NOT-IN-FILE"]

    monkeypatch.setattr(export, "doc_section", with_extra_field)
    for fmt in ("docx", "pdf"):
        r = c.get(f"/cases/L/documents/ncr/export?format={fmt}", headers=H("bob"))
        assert r.status_code == 500 and "LOT-NOT-IN-FILE" in r.json()["detail"]
    assert events(c, "EXPORTED") == []
