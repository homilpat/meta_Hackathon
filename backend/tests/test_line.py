import json

import pytest
from fastapi.testclient import TestClient

from app.db import Base
from app.ingestion import SyntheticBundle, normalize
from app.main import create_app
from app.synthetic import generate_line, sha256
from tests.test_s6_followups import H


@pytest.fixture(scope="module")
def line(tmp_path_factory):
    app = create_app(f"sqlite:///{tmp_path_factory.mktemp('line') / 'l.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": "L"}, headers=H("alice"))
    r = c.post("/cases/L/sources", json=c.get("/synthetic/line/7").json(), headers=H("alice"))
    assert r.status_code == 201, r.text
    yield c
    app.state.engine.dispose()


def tables(bundle):
    return {a["entity_type"]: a["records"] for a in bundle["assets"]}


def test_generator_shape_and_worn_stencil_lot():
    t = tables(generate_line(7))
    assert len(t["lots"]) == 3 and len(t["panels"]) == 36 and len(t["boards"]) == 144
    assert len(t["spi_measurements"]) == 144 * 4 * 2
    confirmed = {r["panel_id"].split("-")[0] for r in t["human_verifications"] if r["result"] == "DEFECT_CONFIRMED"}
    assert confirmed == {"L02"}  # true defects only where the stencil drifts
    assert [e["tool_id"] for e in t["equipment_events"]] == ["STN-2"]
    assert generate_line(7) == generate_line(7)


def test_lot_containment_scope_and_rca_hypothesis(line):
    assert line.post("/cases/L/ncr", json={}, headers=H("alice")).status_code == 201
    plan = line.post("/cases/L/containment", json={}, headers=H("alice")).json()["claims"]
    holds = [c["text"] for c in plan if c["classification"] == "PROPOSAL"]
    assert any("8 unshipped panels of lot L02 (32 boards)" in t for t in holds)
    assert any("4 already SHIPPED panels of lot L02" in t for t in holds)
    assert not any("lot L01" in t or "lot L03" in t for t in holds)  # only false alarms there
    rca = line.post("/cases/L/rca", json={}, headers=H("alice")).json()["claims"]
    hyp = [c["text"] for c in rca if c["classification"] == "HYPOTHESIS"]
    assert len(hyp) == 1 and "stencil STN-2" in hyp[0]  # one lot cause, not one per board


def test_line_spi_correction_endpoint(line):
    a = line.get("/synthetic/7/spi-correction", params={"row_id": "SPI-L02-P12-B1-C01-1", "line": True}).json()
    assert a["records"][0]["original_row_id"] == "SPI-L02-P12-B1-C01-1"


@pytest.mark.parametrize("lot, code", [("L99", "MISSING_LOT"), ("L03", "LOT_MISMATCH")])
def test_lot_integrity_checks(lot, code):
    b = generate_line(7)
    ship = next(a for a in b["assets"] if a["entity_type"] == "shipments")
    ship["records"][0] = {**ship["records"][0], "lot_id": lot}  # L01-P01 shipment claims another lot
    ship["content_sha256"] = sha256(ship["records"])
    _, issues = normalize(SyntheticBundle.model_validate(json.loads(json.dumps(b))))
    assert [i["code"] for i in issues if i["code"] in ("MISSING_LOT", "LOT_MISMATCH")] == [code]


def test_western_electric_rules():
    from app.spc import we_rules
    assert we_rules([0, 0, 3.5], 2) == ["WE1"]
    assert we_rules([2.5, 0, 2.2], 2) == ["WE2"]
    assert we_rules([1.5, 1.2, -0.5, 1.1, 1.3], 4) == ["WE3"]
    assert we_rules([0.2] * 8, 7) == ["WE4"] and we_rules([0.2] * 7 + [-0.1], 7) == []


def test_spc_replay_opens_case_before_aoi_confirms(tmp_path):
    from app.synthetic import generate
    app = create_app(f"sqlite:///{tmp_path / 'spc.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    assert c.post("/monitoring/line-replay", json={"seed": 7}, headers=H("bob")).status_code == 403
    r = c.post("/monitoring/line-replay", json={"seed": 7}, headers=H("alice")).json()
    cid, a = r["case_id"], r["alarm"]
    assert a["lot"] == "L02" and a["phase"] == "II" and a["rules"]
    assert a["t"] < r["first_confirmed_defect_in_lot"]  # the drift signals before AOI + human confirm a defect
    assert c.post("/monitoring/line-replay", json={"seed": 7}, headers=H("alice")).status_code == 409
    assert [t["event"] for t in c.get(f"/cases/{cid}/timeline", headers=H("frank")).json()] == ["SPC_ALARM"]
    m = c.get(f"/cases/{cid}/spc", headers=H("bob")).json()
    assert m["reference_lot"] == "L01" and m["lots"]["L01"]["alarms"] == 0
    assert m["lots"]["L02"]["cpk"] < m["lots"]["L01"]["cpk"]
    claims = c.post(f"/cases/{cid}/ncr", json={}, headers=H("alice")).json()["claims"]
    first = next(cl for cl in claims if cl["text"].startswith("Lot L02:") and "Western Electric" in cl["text"])
    assert first["value"] == a["xbar"] and len(first["evidence_ids"]) == 8
    c.post("/cases", json={"case_id": "S"}, headers=H("alice"))
    c.post("/cases/S/sources", json=generate(7), headers=H("alice"))
    assert c.get("/cases/S/spc", headers=H("alice")).status_code == 404  # no lots in the small fixture
    app.state.engine.dispose()
