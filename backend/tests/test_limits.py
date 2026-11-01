"""Operating limits: one table with each value's basis; only the AI operations department changes them, with a reason."""

import zipfile

from fastapi.testclient import TestClient

from app import limits
from app.main import create_app
from tests.test_intake_in1 import DOCX_FIXTURE, upload
from tests.test_intake_in2 import client
from tests.v5_util import H


def test_every_limit_states_its_basis_and_source(tmp_path):
    c = client(tmp_path, None)
    rows = c.get("/limits", headers=H("bob")).json()["limits"]  # everyone may read what the system runs on
    assert {r["basis"] for r in rows} <= {"STANDARD", "MEASURED", "DERIVED", "DECISION", "DEFAULT"}
    assert all(r["source"] for r in rows)
    by = {r["name"]: r for r in rows}
    assert by["MODEL_RUNS_PER_USER_HOUR"]["basis"] == "DEFAULT" and "budget" in by["MODEL_RUNS_PER_USER_HOUR"]["source"]
    assert by["MAX_UNZIPPED_BYTES"]["value"] == by["MAX_UPLOAD_BYTES"]["value"] * by["MAX_COMPRESSION_RATIO"]["value"]


def test_only_the_ai_operations_department_changes_a_limit_with_a_reason_and_it_survives_a_restart(tmp_path):
    c = client(tmp_path, None)
    body = {"value": "12", "reason": "월 예산 승인으로 상향"}
    assert c.post("/limits/MODEL_RUNS_PER_USER_HOUR", json=body, headers=H("alice")).status_code == 403
    assert c.post("/limits/MODEL_RUNS_PER_USER_HOUR", json={**body, "reason": " "}, headers=H("gina")).status_code == 422
    assert c.post("/limits/MODEL_RUNS_PER_USER_HOUR", json={**body, "value": "-1"}, headers=H("gina")).status_code == 422
    assert c.post("/limits/NOPE", json=body, headers=H("gina")).status_code == 404
    out = c.post("/limits/MODEL_RUNS_PER_USER_HOUR", json=body, headers=H("gina")).json()["limit"]
    assert out["value"] == 12 and out["set_by"] == "SETTING" and limits.get("MODEL_RUNS_PER_USER_HOUR") == 12
    hist = c.get("/limits", headers=H("alice")).json()["history"]
    assert hist == [{"name": "MODEL_RUNS_PER_USER_HOUR", "value": "12", "reason": "월 예산 승인으로 상향",
                     "actor_id": "gina", "at": hist[0]["at"]}]
    limits.OVERRIDES.clear()
    TestClient(create_app(f"sqlite:///{tmp_path / 'in2.db'}"))  # a restarted server replays the recorded setting
    assert limits.get("MODEL_RUNS_PER_USER_HOUR") == 12
    limits.OVERRIDES.clear()


def test_time_zones_are_korea_and_the_us_by_name_and_changeable(tmp_path):
    c = client(tmp_path, None)
    bad = c.post("/limits/ALLOWED_TIMEZONES", json={"value": "Asia/Seoul,Not/AZone", "reason": "x"}, headers=H("gina"))
    assert bad.status_code == 422
    from fastapi import HTTPException

    from app.case_requests import due_moment
    assert due_moment("2026-11-10 18:00", "KST").utcoffset().total_seconds() == 9 * 3600
    assert due_moment("2026-11-10 18:00", "America/Chicago").utcoffset().total_seconds() == -6 * 3600
    for tz in ("CST", "Asia/Tokyo"):  # ambiguous, or not an allowed country
        try:
            due_moment("2026-11-10 18:00", tz)
            raise AssertionError(tz)
        except HTTPException as exc:
            assert exc.status_code == 422
    c.post("/limits/ALLOWED_TIMEZONES", json={"value": "Asia/Seoul,Asia/Tokyo", "reason": "일본 고객 추가"},
           headers=H("gina"))
    assert due_moment("2026-11-10 18:00", "Asia/Tokyo").utcoffset().total_seconds() == 9 * 3600
    limits.OVERRIDES.clear()


def test_a_zip_bomb_is_refused_by_its_compression_ratio_while_ordinary_office_files_pass(tmp_path):
    c = client(tmp_path, None)
    assert upload(c, [("ok.docx", DOCX_FIXTURE.read_bytes())]).status_code == 201  # about 24x: ordinary
    import io

    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(DOCX_FIXTURE.read_bytes())) as src, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for i in src.infolist():
            dst.writestr(i.filename, src.read(i.filename))
        dst.writestr("word/media/zeros.bin", b"\0" * (5 * 1024 * 1024))  # small packed, ~1000x unpacked
    r = upload(c, [("bomb.docx", out.getvalue())])
    assert r.status_code == 413 and "압축률" in r.json()["detail"]


def test_parsing_stops_at_the_time_budget_and_says_what_is_left():
    from app import docparse
    from app.intake import FIXTURE_DIR

    els, cov, _ = docparse.parse("application/pdf", (FIXTURE_DIR / "complaint_HM-CC-2026-0417.pdf").read_bytes(),
                                 docparse.Budget(0))
    assert els == [] and cov["budget_exhausted"] is True and cov["unprocessed_from"] == "page 1"
    assert cov["render"] in ("OK", "PARTIAL")
