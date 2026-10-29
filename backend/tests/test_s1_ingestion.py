import hashlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from app.db import Base
from app.ingestion import SyntheticBundle, normalize
from app.main import create_app
from app.synthetic import generate, sha256
from scripts.generate_synthetic_pcb import main as generate_cli


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'case.db'}")
    Base.metadata.create_all(app.state.engine)
    with TestClient(app, headers={"X-User": "alice"}) as test_client:
        yield test_client
    app.state.engine.dispose()


def test_seed_reproducible_and_changes_measurements():
    assert generate(7) == generate(7)
    assert generate(7)["assets"][4]["records"] != generate(8)["assets"][4]["records"]


def test_cli_writes_utf8_fixture(tmp_path, monkeypatch):
    target = tmp_path / "fixture.json"
    monkeypatch.setattr(sys, "argv", ["generate_synthetic_pcb", "--seed", "7", "--output", str(target)])
    generate_cli()
    assert json.loads(target.read_text(encoding="utf-8")) == generate(7)


def test_hierarchy_uses_composite_keys():
    events, issues = normalize(SyntheticBundle.model_validate(generate(7)))
    boards = {tuple(e["entity_key"]) for e in events if e["entity_type"] == "boards"}
    pins = {tuple(e["entity_key"]) for e in events if e["entity_type"] == "pins"}
    assert ("P01", "B01") in boards and ("P02", "B01") in boards
    assert ("P01", "B01", "C01", 1) in pins
    assert ("P02", "B01", "C01", 1) in pins
    assert not any(i["code"] == "MISSING_PARENT" for i in issues)


def test_normal_missing_duplicate_and_conflict_scenarios():
    events, issues = normalize(SyntheticBundle.model_validate(generate(7)))
    codes = {i["code"] for i in issues}
    assert {"MISSING_AOI", "DUPLICATE_ROW", "INSPECTION_DISAGREEMENT"} <= codes
    assert len([e for e in events if e["entity_type"] == "aoi_inspections" and e["entity_key"] == ["P01", "B01"]]) == 2
    assert any(e["entity_type"] == "aoi_inspections" and json.loads(e["raw_json"])["result"] == "PASS" for e in events)
    assert not any(e["entity_type"] == "aoi_inspections" and e["entity_key"] == ["P01", "B02"] for e in events)


def test_late_correction_preserves_both_source_versions():
    bundle = generate(7)
    first, corrected = bundle["assets"][4], bundle["assets"][-1]
    assert first["content_sha256"] == sha256(first["records"])
    assert corrected["supersedes_asset_id"] == first["asset_id"]
    assert corrected["records"][0]["original_row_id"] == first["records"][0]["original_row_id"]
    assert corrected["content_sha256"] != first["content_sha256"]
    _, issues = normalize(SyntheticBundle.model_validate(bundle))
    assert {"LATE_ARRIVAL", "SOURCE_CORRECTION"} <= {i["code"] for i in issues}


def test_wrong_panel_pin_link_is_detected():
    bundle = generate(7)
    spi = bundle["assets"][4]
    spi["records"][0]["panel_id"] = "P99"
    spi["content_sha256"] = sha256(spi["records"])
    _, issues = normalize(SyntheticBundle.model_validate(bundle))
    assert any(i["code"] == "MISSING_PARENT" and "P99" in i["detail"] for i in issues)


def test_human_aoi_join_uses_panel_and_board():
    bundle = generate(7)
    human = bundle["assets"][6]
    human["records"][0]["board_id"] = "B02"
    human["content_sha256"] = sha256(human["records"])
    _, issues = normalize(SyntheticBundle.model_validate(bundle))
    assert any(i["code"] == "MISSING_AOI_REFERENCE" for i in issues)


def test_duplicate_inspection_is_reported_without_dropping_raw_event():
    bundle = generate(7)
    aoi = bundle["assets"][5]
    duplicate = dict(aoi["records"][0])
    duplicate["original_row_id"] = "AOI-DUPLICATE"
    aoi["records"].append(duplicate)
    aoi["content_sha256"] = sha256(aoi["records"])
    events, issues = normalize(SyntheticBundle.model_validate(bundle))
    assert any(i["code"] == "DUPLICATE_INSPECTION" for i in issues)
    assert any(e["original_row_id"] == "AOI-DUPLICATE" for e in events)


def test_missing_key_and_naive_time_are_rejected():
    bundle = generate(7)
    del bundle["assets"][3]["records"][0]["pin_number"]
    bundle["assets"][3]["content_sha256"] = sha256(bundle["assets"][3]["records"])
    with pytest.raises(ValueError, match="manufacturing key"):
        normalize(SyntheticBundle.model_validate(bundle))
    bundle = generate(7)
    bundle["assets"][0]["records"][0]["event_time"] = "2026-01-01T08:00:00"
    bundle["assets"][0]["content_sha256"] = sha256(bundle["assets"][0]["records"])
    with pytest.raises(ValueError, match="timestamp"):
        normalize(SyntheticBundle.model_validate(bundle))


def test_wrong_hash_or_mixed_origin_rejected():
    bundle = generate(7)
    bundle["assets"][0]["records"][0]["panel_id"] = "P99"
    with pytest.raises(ValueError, match="content hash"):
        normalize(SyntheticBundle.model_validate(bundle))
    bundle = generate(7)
    bundle["assets"][0]["records"][0]["data_origin"] = "REAL"
    bundle["assets"][0]["content_sha256"] = sha256(bundle["assets"][0]["records"])
    with pytest.raises(ValueError, match="origin"):
        normalize(SyntheticBundle.model_validate(bundle))


def test_history_and_all_rows_labeled_synthetic():
    bundle = generate(7)
    assert all(asset["data_origin"] == "SYNTHETIC" for asset in bundle["assets"])
    assert all(row["data_origin"] == "SYNTHETIC" for asset in bundle["assets"] for row in asset["records"])
    history = next(a for a in bundle["assets"] if a["entity_type"] == "historical_quality_cases")
    assert {r["outcome"] for r in history["records"]} == {"EFFECTIVE_REPORTED", "INEFFECTIVE_REPORTED"}
    assert all(r["validation_status"] == "UNVERIFIED" for r in history["records"])


def test_api_ingest_and_read_lineage(client):
    assert client.post("/cases", json={"case_id": "CASE-1"}).status_code == 201
    response = client.post("/cases/CASE-1/sources", json=generate(7))
    assert response.status_code == 201
    assert response.json()["asset_count"] == 12
    assert response.json()["event_count"] == 42
    assets = client.get("/cases/CASE-1/sources").json()
    events = client.get("/cases/CASE-1/events?entity_type=spi_measurements&panel_id=P01&board_id=B01").json()
    assert len(events) == 4  # Two pins, one deliberate duplicate, one correction.
    assert {e["source_version"] for e in events} == {1, 2}
    assert all(e["data_origin"] == "SYNTHETIC" for e in events)
    assert all(e["source_sha256"] == next(a["content_sha256"] for a in assets if a["asset_id"] == e["source_asset_id"]) for e in events)
    assert all(a["content_sha256"] == next(source["content_sha256"] for source in generate(7)["assets"] if source["asset_id"] == a["asset_id"]) for a in assets)


def test_evidence_hash_and_issue_trace(client):
    client.post("/cases", json={"case_id": "CASE-1"})
    client.post("/cases/CASE-1/sources", json=generate(7))
    events = client.get("/cases/CASE-1/events").json()
    evidence = client.get("/cases/CASE-1/evidence").json()
    issues = client.get("/cases/CASE-1/data-issues").json()
    assert len(events) == len(evidence)
    first = events[0]
    expected = hashlib.sha256(json.dumps(first["record"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert evidence[0]["content_sha256"] == expected
    assert evidence[0]["classification"] == "OBSERVED"
    assert {i["code"] for i in issues} >= {"MISSING_AOI", "DUPLICATE_ROW", "INSPECTION_DISAGREEMENT"}


def test_api_rejects_disguised_or_modified_source_without_partial_write(client):
    client.post("/cases", json={"case_id": "CASE-1"})
    bundle = generate(7)
    bundle["assets"][0]["records"][0]["panel_id"] = "P99"
    assert client.post("/cases/CASE-1/sources", json=bundle).status_code == 422
    assert client.get("/cases/CASE-1/sources").json() == []
    bundle = generate(7)
    bundle["assets"][0]["records"][0]["data_origin"] = "REAL"
    assert client.post("/cases/CASE-1/sources", json=bundle).status_code == 422
    assert client.get("/cases/CASE-1/sources").json() == []


def test_duplicate_upload_and_case_scope(client):
    client.post("/cases", json={"case_id": "CASE-1"})
    assert client.post("/cases", json={"case_id": "CASE-1"}).status_code == 409
    assert client.post("/cases/CASE-1/sources", json=generate(7)).status_code == 201
    assert client.post("/cases/CASE-1/sources", json=generate(7)).status_code == 409
    assert client.get("/cases/MISSING/events").status_code == 404
    assert client.get("/cases/MISSING/sources").status_code == 404
