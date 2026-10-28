from fastapi.testclient import TestClient

from app.main import app, create_app


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stage": "S6"}



def test_provider_status_never_exposes_a_key(tmp_path):
    from tests.test_s3_investigation import Scripted

    configured = TestClient(create_app(f"sqlite:///{tmp_path / 'p.db'}", Scripted())).get("/provider").json()
    assert configured == {"model": "scripted-test-double", "mode": "TEST_DOUBLE", "configured": True,
                          "live_status": "TEST_DOUBLE"}


def test_built_web_ui_is_served_when_present():
    from pathlib import Path

    client = TestClient(app)
    if (Path(__file__).parents[1] / "app" / "static" / "web" / "index.html").is_file():
        assert '<div id="root">' in client.get("/app/").text


def test_steel_reference_is_aggregates_only_and_beats_baselines():
    out = TestClient(app).get("/reference-models/steel").json()  # committed docs/steel_eval.json
    assert out["data_origin"] == "REAL" and "CC BY 4.0" in out["attribution"]
    m = out["metrics_test"]
    assert m["lightgbm"]["macro_f1"] > m["logistic_regression"]["macro_f1"] > m["majority_class"]["macro_f1"]
    assert out["shap"]["max_additivity_error"] < 1e-6
    assert set(out) <= {"source", "archive_sha256", "archive_bytes", "attribution", "data_origin", "task", "rows",
                        "class_counts", "split", "metrics_test", "lightgbm_per_class_f1", "lightgbm_best_iteration",
                        "confusion_matrix_test", "shap", "versions"}  # no source rows are served
