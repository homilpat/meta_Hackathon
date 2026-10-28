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


DETAILS = {"feasibility": "spare stencil in stock, 30 min change", "risk_analysis": "new stencil needs first-article",
           "side_effects": "none expected on other components"}


def ok(r, code=201):
    assert r.status_code == code, r.text
    return r.json()


def approve_doc(c: TestClient, case_id: str, kind: str, reviewer: str) -> None:
    ok(c.post(f"/cases/{case_id}/{kind}", json={}, headers=H("alice")))
    d = ok(c.post(f"/cases/{case_id}/{kind}/1/request-review", json={"reviewer_id": reviewer}, headers=H("alice")), 200)
    ok(c.post(f"/cases/{case_id}/{kind}/1/decision", headers=H(reviewer),
              json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]}), 200)


def act(c: TestClient, case_id: str, aid: int, user: str, event_type: str, note: str = "", evidence=()) -> dict:
    return ok(c.post(f"/cases/{case_id}/actions/{aid}/events", headers=H(user),
                     json={"event_type": event_type, "note": note, "evidence": list(evidence)}))


def revise_doc(c: TestClient, case_id: str, number: str, kind: str, base: int, title: str, body: str) -> int:
    rev = ok(c.post("/controlled-documents/revisions", headers=H("alice"), json={
        "doc_number": number, "kind": kind, "base_revision": base, "title": title, "body": body,
        "case_id": case_id}))["revision"]
    ok(c.post(f"/controlled-documents/{number}/revisions/{rev}/release", headers=H("bob"),
              json={"reason": "reviewed against the confirmed cause"}))
    return rev


def deploy(c: TestClient, case_id: str, number: str, rev: int, operators=("OP-1", "OP-2"), trained=None):
    trained = operators if trained is None else trained
    return c.post(f"/cases/{case_id}/prevention", headers=H("alice"), json={
        "doc_number": number, "new_revision": rev, "scopes": ["SMT-1"], "operators_in_scope": list(operators),
        "training": [{"operator_id": o, "evidence_ref": f"TRN-{o}-2026"} for o in trained],
        "sister_lines": [{"line": "SMT-2", "applies": True, "reason": "same stencil type"}]})


def ready_to_close(c: TestClient, case_id: str = "L", effective: bool = True) -> dict:
    """Drive the synthetic line case D0 -> D7 the legitimate way, stopping just before the D8 acknowledgements."""
    ids = {}
    spc = evidence(c, case_id, "spi_measurements", panel_id="L02-P02", board_id="B2")
    ok(c.post(f"/cases/{case_id}/triage", headers=H("bob"), json={
        "signal_kind": "SPC_SIGNAL", "observed_defect": "SIGNAL_ONLY", "scope_lots": ["L02"],
        "route": "EMERGENCY_FULL_8D", "severity": "HIGH", "risk_flags": {"customer_impact": True},
        "rationale": "WE1 on L02 panel 2; shipped panels in lot", "evidence_ids": spc}))
    for resp, user in (("LEAD", "alice"), ("QUALITY", "bob"), ("PRODUCTION", "erin"), ("PROCESS", "frank")):
        ok(c.post(f"/cases/{case_id}/team", headers=H("alice"),
                  json={"event": "ASSIGN", "responsibility": resp, "user_id": user}))
        ok(c.post(f"/cases/{case_id}/team", headers=H(user), json={"event": "ACCEPT", "responsibility": resp}))
    approve_doc(c, case_id, "ncr", "bob")
    approve_doc(c, case_id, "containment", "erin")
    d3 = ok(c.post(f"/cases/{case_id}/actions", headers=H("alice"), json={
        "action_type": "HOLD", "description": "Hold unshipped L02 panel 9 at SMT-1 exit", "targets": ["L02-P09"]}))
    act(c, case_id, d3["action_id"], "erin", "PLAN_APPROVED")
    act(c, case_id, d3["action_id"], "erin", "EXECUTED", "panel L02-P09 held at SMT-1 exit (simulated)")
    act(c, case_id, d3["action_id"], "bob", "INDEPENDENTLY_VERIFIED", "hold tag checked", ["REF:HOLD-TAG-1"])
    approve_doc(c, case_id, "rca", "frank")
    ids["cause"] = confirmed_cause(c, case_id)
    a5 = ok(c.post(f"/cases/{case_id}/actions", headers=H("alice"), json={
        "stage": "D5", "action_type": "EQUIPMENT_CHANGE", "cause_ids": [ids["cause"]], "details": DETAILS,
        "description": "Replace stencil STN-2 and enforce the cleaning interval"}))["action_id"]
    act(c, case_id, a5, "frank", "PLAN_APPROVED", "fresh stencil first-article passed")
    plan = ok(c.post(f"/cases/{case_id}/effectiveness-plans", headers=H("bob"), json={
        "action_id": a5, "metric": "SPI_MEAN_VOLUME_MM3", "baseline_lots": ["L02"], "min_sample": 50,
        "acceptance": {"op": ">=", "value": 0.115}, "inspection_conditions": {"inspection_id": "S01"},
        "monitoring": "SPI mean of the next lot after the change"}))["plan_id"]
    act(c, case_id, a5, "erin", "EXECUTED", "stencil STN-2 replaced on SMT-1 (simulated)")
    ok(c.post(f"/cases/{case_id}/synthetic/post-window", json={"action_id": a5, "effective": effective},
              headers=H("alice")))
    ok(c.post(f"/cases/{case_id}/effectiveness", headers=H("bob"), json={
        "plan_id": plan, "decision": "EFFECTIVE" if effective else "NOT_EFFECTIVE",
        "note": "reviewed SPI comparison for L04"}))
    ids.update(d3=d3["action_id"], d5=a5, plan=plan)
    if effective:
        ids["fmea"] = revise_doc(c, case_id, "FMEA-SMT-001", "FMEA", 5, "SMT print process FMEA",
                                 "Stencil wear: cleaning interval 8 h enforced by counter; occurrence 2.")
        ids["sop"] = revise_doc(c, case_id, "SOP-SMT-010", "SOP", 3, "Stencil cleaning and inspection",
                                "Clean every 8 h of print time, counter-enforced; replace stencils at 50k prints.")
        ok(deploy(c, case_id, "FMEA-SMT-001", ids["fmea"]))
        ok(deploy(c, case_id, "SOP-SMT-010", ids["sop"]))
    return ids


def acknowledge_all(c: TestClient, case_id: str = "L") -> None:
    for u in ("alice", "bob", "erin", "frank"):
        ok(c.post(f"/cases/{case_id}/closure/acknowledgements", headers=H(u),
                  json={"contribution": f"{u} did their part"}))


CLOSE = {"residual_risks": [{"risk": "other stencils of the same type", "mitigation": "SMT-2 rollout",
                             "owner": "frank"}], "customer_notification_ref": "CN-2026-0042",
         "comment": "D0-D7 complete on synthetic data"}
