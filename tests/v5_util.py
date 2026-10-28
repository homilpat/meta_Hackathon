"""Shared fixture for v5 gate tests: the synthetic SMT line case (seed 7) with the full demo team assigned."""

import uuid

from fastapi.testclient import TestClient

from app.db import Base
from app.main import create_app
from app.synthetic import generate_line

TEAM = ("bob", "carol", "erin", "frank", "dave")


def H(user: str) -> dict:
    return {"X-User": user, "Idempotency-Key": uuid.uuid4().hex}


def line_client(tmp_path, case_id: str = "L", process: bool = True) -> TestClient:
    app = create_app(f"sqlite:///{tmp_path / 'v5.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": case_id}, headers=H("alice"))
    assert c.post(f"/cases/{case_id}/sources", json=generate_line(7), headers=H("alice")).status_code == 201
    for u in TEAM:
        c.post(f"/cases/{case_id}/assignments", json={"user_id": u}, headers=H("alice"))
    if process:
        r = c.post(f"/cases/{case_id}/process-context", json={"site": "SITE-A", "customer": "DEFAULT"},
                   headers=H("alice"))
        assert r.status_code == 201, r.text
    c.app_ref = app
    return c
