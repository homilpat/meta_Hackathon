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


def evidence(c: TestClient, case_id: str, kind: str, **match) -> list[str]:
    """Evidence ids of current source rows of `kind` whose record fields equal `match` (prefix match on str with *)."""
    from sqlalchemy.orm import Session

    from app import ncr

    def ok(rec: dict) -> bool:
        for k, v in match.items():
            r = rec.get(k)
            if isinstance(v, str) and v.endswith("*"):
                if not str(r).startswith(v[:-1]):
                    return False
            elif r != v:
                return False
        return True

    with Session(c.app_ref.state.engine) as s:
        return [i["ev"] for i in ncr.current(ncr._evidence(s, case_id)) if i["type"] == kind and ok(i["rec"])]


def valid(c: TestClient, case_id: str, kind: str, **match) -> list[str]:
    """Like evidence(), restricted to rows whose effective quality state is VALID."""
    ok = {i["evidence_id"] for i in c.get(f"/cases/{case_id}/evidence-quality?state=VALID",
                                          headers=H("alice")).json()["items"]}
    return [e for e in evidence(c, case_id, kind, **match) if e in ok]


def confirmed_cause(c: TestClient, case_id: str = "L", text: str = "Worn stencil STN-2 under-deposits paste in L02",
                    category: str = "MACHINE") -> int:
    """A D4 cause CONFIRMED the legitimate way: hypothesis, supporting experiment by alice, decision by frank."""
    ev = valid(c, case_id, "equipment_events")[:1] + valid(c, case_id, "lots", lot_id="L02")[:1]
    h = c.post(f"/cases/{case_id}/hypotheses", headers=H("alice"), json={
        "cause_type": "OCCURRENCE", "category": category, "text": text, "evidence_ids": ev}).json()["hypothesis_id"]
    e = c.post(f"/cases/{case_id}/experiments", headers=H("alice"), json={
        "hypothesis_id": h, "method": "Swap STN-2 for a fresh stencil, same paste lot, compare SPI volume",
        "controlled_conditions": ["paste lot unchanged", "same line"], "baseline": {"stencil": "STN-2"},
        "intervention": {"stencil": "fresh"}, "sample_size": 32, "acceptance_rule": "mean SPI 0.11-0.13 mm3",
        "evidence_ids": valid(c, case_id, "spi_measurements", panel_id="L02*")[:8],
        "result": "SUPPORTS"}).json()["experiment_id"]
    r = c.post(f"/cases/{case_id}/causal-decisions", headers=H("frank"), json={
        "hypothesis_id": h, "decision": "CONFIRMED", "basis_experiment_ids": [e],
        "rationale": "independent fresh-stencil run restored the SPI volume"})
    assert r.status_code == 201, r.text
    return h
