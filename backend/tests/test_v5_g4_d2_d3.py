"""G4: D2 claims checked against the source rows (lot, unit, superseded), 5W2H/IS-IS NOT, D3 actions."""

import pytest

from app.synthetic import spi_correction
from tests.v5_util import H, evidence, line_client


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def ncr(c, *claims):
    return c.post("/cases/L/ncr", json={"extra_claims": list(claims)}, headers=H("alice"))


def approve(c, kind, reviewer):
    d = c.post(f"/cases/L/{kind}/1/request-review", json={"reviewer_id": reviewer}, headers=H("alice")).json()
    r = c.post(f"/cases/L/{kind}/1/decision", headers=H(reviewer),
               json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]})
    assert r.status_code == 200, r.text


def l02_spi(c):
    return evidence(c, "L", "spi_measurements", panel_id="L02-P02", board_id="B2")


# --- D2 claim checks ----------------------------------------------------------------------------------

def test_valid_evidence_id_but_wrong_lot_in_text_is_blocked(c):
    r = ncr(c, {"classification": "OBSERVED", "text": "SPI volume low on lot L01", "evidence_ids": l02_spi(c)[:1]})
    assert r.status_code == 422 and "names lot ['L01']" in r.json()["detail"]
    ok = ncr(c, {"classification": "OBSERVED", "text": "SPI volume low on lot L02", "evidence_ids": l02_spi(c)[:1]})
    assert ok.status_code == 201


def test_lot_named_without_any_lot_context_is_blocked(c):
    eq = evidence(c, "L", "equipment_events")
    r = ncr(c, {"classification": "OBSERVED", "text": "Stencil issue affects L03", "evidence_ids": eq})
    assert r.status_code == 422


def test_unit_must_match_cited_measurement(c):
    ids = l02_spi(c)
    r = ncr(c, {"classification": "OBSERVED", "text": "Low paste volume", "evidence_ids": ids, "value": 0.1, "unit": "mm"})
    assert r.status_code == 422 and "unit mm" in r.json()["detail"]


def test_superseded_measurement_cannot_carry_a_fact(c):
    old = evidence(c, "L", "spi_measurements", original_row_id="SPI-L02-P12-B1-C01-1")
    r = c.post("/cases/L/source-revisions", headers=H("alice"), json={
        "asset": spi_correction(7, row_id="SPI-L02-P12-B1-C01-1", version=2, line=True), "reason": "re-measured"})
    assert r.status_code == 201, r.text
    bad = ncr(c, {"classification": "OBSERVED", "text": "Pin volume on L02-P12", "evidence_ids": old})
    assert bad.status_code == 422 and "superseded" in bad.json()["detail"]
    assert ncr(c).status_code == 201  # the template itself uses only current rows


def test_problem_definition_5w2h_and_is_is_not(c):
    p = c.get("/cases/L/problem-definition", headers=H("bob")).json()
    assert p["is"]["value"] == {"lots": ["L02"]} and p["is_not"]["value"] == {"lots": ["L01", "L03"]}
    assert p["how_many"]["value"]["denominator_aoi_inspections"] > p["how_many"]["value"]["confirmed"] > 0
    assert p["when"]["status"] == "KNOWN" and p["what"]["evidence_ids"]
    assert p["unknown_scope"] and p["how_many"]["value"]["boards_without_aoi"] == len(p["unknown_scope"])
    assert p["effective_source_versions"]["spi_measurements"] == 1


# --- D3 actions ---------------------------------------------------------------------------------------

def plan(c):
    assert ncr(c).status_code == 201
    approve(c, "ncr", "bob")
    assert c.post("/cases/L/containment", json={}, headers=H("alice")).status_code == 201


def d3(c, targets=("L02-P09",)):
    return c.post("/cases/L/actions", headers=H("alice"), json={
        "action_type": "HOLD", "description": "Hold unshipped L02 panels per plan", "targets": list(targets)})


def ev(c, aid, user, t, note="", evid=()):
    return c.post(f"/cases/L/actions/{aid}/events", headers=H(user),
                  json={"event_type": t, "note": note, "evidence": list(evid)})


def state(c):
    return c.get("/cases/L/gates", headers=H("bob")).json()["state"]["D3"]


def test_d3_action_needs_a_containment_plan(c):
    assert d3(c).status_code == 409


def test_plan_without_execution_is_not_containment_done(c):
    plan(c)
    aid = d3(c).json()["action_id"]
    assert ev(c, aid, "erin", "PLAN_APPROVED").status_code == 409  # plan document not approved yet
    approve(c, "containment", "erin")
    assert state(c) == "PLAN_APPROVED"
    assert ev(c, aid, "erin", "EXECUTED", note="held L02-P09 in cage B").status_code == 409  # not plan-approved
    assert ev(c, aid, "bob", "PLAN_APPROVED").status_code == 403  # wrong role
    assert ev(c, aid, "erin", "PLAN_APPROVED").status_code == 201
    assert state(c) == "PLAN_APPROVED"  # approved plan != executed
    assert ev(c, aid, "erin", "EXECUTED", note="held L02-P09 in cage B").status_code == 201
    assert state(c) == "PLAN_APPROVED"  # executed != independently verified
    assert ev(c, aid, "erin", "INDEPENDENTLY_VERIFIED", evid=["REF:cage B sheet"]).status_code == 403
    assert ev(c, aid, "bob", "INDEPENDENTLY_VERIFIED", evid=["REF:cage B sheet"]).status_code == 201
    assert state(c) == "DONE"


def test_d3_scope_binds_to_exact_objects_and_refuses_shipped(c):
    plan(c)
    a = d3(c, targets=["L02-P09", "L02-P10"]).json()
    assert [s["object_id"] for s in a["target_snapshot"]] == ["L02-P09", "L02-P10"]
    assert all(s["identity_source"].startswith("EV-") for s in a["target_snapshot"])
    assert d3(c, targets=["L02-P01"]).status_code == 422  # shipped
    assert c.post("/cases/L/actions", headers=H("erin"), json={
        "action_type": "HOLD", "description": "Hold unshipped panels", "targets": ["L02-P09"]}).status_code == 403


def test_d3_binds_board_and_shipment_rows(c):
    plan(c)
    a = d3(c, targets=["L02-P09/B1", "L02-P09/B2"]).json()
    assert [s["object_type"] for s in a["target_snapshot"]] == ["BOARD", "BOARD"]
    assert d3(c, targets=["L02-P01/B1"]).status_code == 422  # board of a shipped panel
    ship = c.post("/cases/L/actions", headers=H("alice"), json={
        "action_type": "CUSTOMER_NOTIFY_REQUEST", "description": "Ask QA to decide customer notice for shipment",
        "targets": ["SHIP-L02-P01"]})
    assert ship.status_code == 201 and ship.json()["target_snapshot"][0]["object_type"] == "SHIPMENT"
    assert ship.json()["target_snapshot"][0]["shipment_state"] == "SHIPPED"
    hold_ship = c.post("/cases/L/actions", headers=H("alice"), json={
        "action_type": "HOLD", "description": "Hold the shipment in plant", "targets": ["SHIP-L02-P01"]})
    assert hold_ship.status_code == 422


def test_ncr_states_5w2h_and_is_is_not_inside_the_approved_document(c):
    doc = ncr(c).json()
    texts = [x["text"] for x in doc["claims"]]
    assert any(t.startswith("5W2H What:") for t in texts) and any(t.startswith("5W2H When:") for t in texts)
    how = next(x for x in doc["claims"] if x["text"].startswith("5W2H How many"))
    p = c.get("/cases/L/problem-definition", headers=H("bob")).json()
    assert how["value"] == p["how_many"]["value"]["denominator_aoi_inspections"]  # same computation
    assert "IS: confirmed defects are in lot L02." in texts
    assert "IS NOT: no human-confirmed defect recorded in lot L01, L03." in texts
    assert doc["template_version"] == "v5.g5"
    approve(c, "ncr", "bob")  # the problem statement is under the approval hash
    got = c.get("/cases/L/ncr/1", headers=H("bob")).json()
    assert got["status"] == "APPROVED" and got["decisions"][0]["content_sha256"] == doc["content_sha256"]
    cont = c.post("/cases/L/containment", json={}, headers=H("alice")).json()
    assert cont["template_version"] == "s6.1"  # unchanged template keeps its label


def test_existing_d2_d3_stage_review_unchanged(c):
    plan(c)
    stages = {s["doc_type"]: s for s in c.get("/cases/L/stages", headers=H("alice")).json()}
    assert stages["CONTAINMENT"]["approval_open"] and stages["CONTAINMENT"]["status"] == "DRAFT"
