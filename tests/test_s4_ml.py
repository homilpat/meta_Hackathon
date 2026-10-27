import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import ml
from app.db import Base
from app.main import create_app
from app.report import InvestigationReport, validate_report
from app.synthetic import generate
from app.tools import EvidenceTools

A = {"X-User": "alice"}


@pytest.fixture(scope="module")
def trained():
    return ml.train(11)


def key():
    return {"Idempotency-Key": uuid.uuid4().hex}


# --- leakage and split ---

def test_post_hoc_sources_cannot_feed_the_predictor():
    spi = ("spi_measurements", {"volume_mm3": 0.12})
    assert ml.board_features([spi])["vol_mean"] == 0.12
    for leaky in ml.POST_HOC:
        with pytest.raises(ml.LeakageError):
            ml.board_features([spi, (leaky, {"volume_mm3": 0.12, "result": "FAIL"})])


def test_feature_schema_is_the_audited_spi_list():
    ml.assert_no_leakage(ml.FEATURES)
    for extra in ("aoi_result", "human_result", "repair", "label"):
        with pytest.raises(ml.LeakageError):
            ml.assert_no_leakage([*ml.FEATURES, extra])


def test_post_hoc_columns_do_not_change_features():
    rows = ml.training_boards(11, n_panels=20)
    shuffled = json.loads(json.dumps(rows))
    for r in shuffled:
        r["post_hoc"] = {"aoi_result": "FAIL", "human_result": "DEFECT_CONFIRMED", "repair": "REPAIRED"}
    assert np.array_equal(ml.matrix(rows)[0], ml.matrix(shuffled)[0])


def test_split_is_time_ordered_with_zero_panel_overlap():
    parts = ml.split_by_time(ml.training_boards(11))
    groups = {k: {r["panel_id"] for r in v} for k, v in parts.items()}
    assert not groups["train"] & groups["test"] and not groups["train"] & groups["valid"]
    assert not groups["valid"] & groups["test"]
    assert max(r["produced_at"] for r in parts["train"]) < min(r["produced_at"] for r in parts["test"])


# --- reproducibility, metrics, SHAP ---

def test_training_is_reproducible(trained):
    again = ml.train(11)
    for k in ("artifact_sha256", "train_data_sha256", "feature_schema_sha256", "metrics", "threshold"):
        assert again[k] == trained[k]
    assert ml.train(12)["train_data_sha256"] != trained["train_data_sha256"]


def test_metrics_include_baselines_and_are_real(trained):
    m = trained["metrics"]
    assert {"dummy_prior", "logistic_regression", "lightgbm", "lightgbm_calibration"} <= set(m)
    assert m["dummy_prior"]["roc_auc"] == 0.5
    assert m["lightgbm"]["pr_auc"] > m["dummy_prior"]["pr_auc"]
    assert trained["label_kind"] == "SYNTHETIC_LABEL"


def test_shap_is_additive_and_card_disclaims(trained):
    f = ml.board_features([("spi_measurements", {"volume_mm3": v}) for v in (0.09, 0.15, 0.12)])
    out = ml.predict_explain(trained["artifact_text"], f)
    assert out["additivity_error"] < 1e-9 and 0 < out["risk_score"] < 1
    assert set(out["contributions"]) == set(ml.FEATURES)
    card = ml.model_card(trained)
    assert "not** industrial performance" in card and "not\nevidence of a physical defect cause" in card


# --- API / case evidence ---

@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'ml.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": "C1"}, headers=A)
    c.post("/cases/C1/sources", json=generate(7), headers=A)
    c.post("/cases/C1/assignments", json={"user_id": "bob"}, headers=A)
    c.engine = app.state.engine
    yield c
    app.state.engine.dispose()


def scored(client):
    assert client.post("/cases/C1/predictions", json={}, headers={**A, **key()}).status_code == 409
    mv = client.post("/models/train", json={"seed": 11}, headers=A).json()
    assert client.post("/models/train", json={"seed": 11}, headers=A).json()["model_version_id"] == mv["model_version_id"]
    r = client.post("/cases/C1/predictions", json={}, headers={**A, **key()})
    assert r.status_code == 201, r.text
    return mv, r.json()["predictions"]


def test_predictions_are_case_evidence_with_hashes(client):
    mv, preds = scored(client)
    assert {tuple(p["target_key"]) for p in preds} == {("P01", "B01"), ("P01", "B02"), ("P02", "B01"), ("P02", "B02")}
    p = next(p for p in preds if p["target_key"] == ["P01", "B01"])
    assert len(p["input_evidence_ids"]) == 2  # duplicate row and superseded v1 measurement are excluded
    assert p["model"]["artifact_sha256"] == mv["artifact_sha256"] and len(p["input_sha256"]) == 64
    assert p["xai"]["additivity_error"] < 1e-9 and "not evidence of a physical defect cause" in p["note"]
    detail = client.get(f"/cases/C1/predictions/{p['prediction_id']}", headers=A).json()
    assert detail == p


def test_ncr_cites_prediction_and_shap(client):
    _, preds = scored(client)
    doc = client.post("/cases/C1/ncr", json={}, headers={**A, **key()}).json()
    cited = {e for c in doc["claims"] for e in c["evidence_ids"]}
    assert {p["evidence_id"] for p in preds} <= cited and {p["xai_evidence_id"] for p in preds} <= cited
    shap = [c for c in doc["claims"] if "SHAP" in c["text"]]
    assert shap and all("not the physical defect cause" in c["text"] for c in shap)


def test_card_endpoint_and_access(client):
    mv, _ = scored(client)
    card = client.get(f"/models/{mv['model_version_id']}/card", headers=A).text
    assert mv["artifact_sha256"] in card
    assert client.get("/cases/C1/predictions", headers={"X-User": "carol"}).status_code == 403
    assert client.post("/cases/C1/predictions", json={}, headers={"X-User": "bob", **key()}).status_code == 403
    assert client.post("/models/train", json={}, headers={"X-User": "bob"}).status_code == 403


def test_prediction_tools_and_validator(client):
    from sqlalchemy.orm import Session
    _, preds = scored(client)
    p = preds[0]
    with Session(client.engine) as s:
        tools = EvidenceTools(s, "C1")
        assert tools.call("get_prediction", {})["predictions"][0]["evidence_id"] == preds[0]["evidence_id"]
        assert tools.call("explain_prediction", {"prediction_id": p["prediction_id"]})["evidence_id"] == p["xai_evidence_id"]

        def check(**finding):
            return validate_report(s, "C1", InvestigationReport(summary="s", findings=[finding]))

        assert check(classification="CALCULATED", text="Mean risk score.", evidence_ids=[p["evidence_id"]],
                     value=p["risk_score"], calc={"op": "mean", "field": "risk_score"}) == []
        assert check(classification="OBSERVED", text="Score per model.", evidence_ids=[p["xai_evidence_id"]]) == []
        bad = check(classification="HYPOTHESIS", text="The SHAP contribution of vol_std shows the bridge was "
                    "caused by paste.", evidence_ids=[p["xai_evidence_id"]])
        assert any("SHAP attribution is not causal" in e for e in bad)
        assert any("nonexistent" in e for e in check(classification="UNKNOWN", text="See PRED-999."))
