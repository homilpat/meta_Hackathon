from fastapi.testclient import TestClient

from app.main import app, create_app


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stage": "S6"}



def test_provider_status_never_exposes_a_key(tmp_path):
    from tests.test_s3_investigation import Scripted

    configured = TestClient(create_app(f"sqlite:///{tmp_path / 'p.db'}", Scripted())).get("/provider").json()
    assert configured == {"model": "scripted-test-double", "mode": "TEST_DOUBLE", "configured": True}


def test_built_web_ui_is_served_when_present():
    from pathlib import Path

    client = TestClient(app)
    if (Path(__file__).parents[1] / "app" / "static" / "web" / "index.html").is_file():
        assert '<div id="root">' in client.get("/app/").text
