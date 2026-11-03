import json
import logging
import re
import uuid

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.db import APPEND_ONLY, ApprovalEvent, Base, SourceEvent, ToolCall, WorkflowEvent
from app.main import create_app
from app.model_provider import MODEL, EgressBlocked, MetaProvider
from app.ncr import DONE_CLAIM
from app.synthetic import generate, sha256, spi_correction
from tests.test_s3_investigation import LOOKUP, Opener, Scripted, final

APPROVERS = {"ncr": "bob", "containment": "erin", "rca": "frank"}


def H(user):
    return {"X-User": user, "Idempotency-Key": uuid.uuid4().hex}


@pytest.fixture
def env(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 's6.db'}", Scripted())
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": "C1"}, headers={"X-User": "alice"})
    c.post("/cases/C1/sources", json=generate(7), headers={"X-User": "alice"})
    for u in ("bob", "erin", "frank"):
        c.post("/cases/C1/assignments", json={"user_id": u}, headers={"X-User": "alice"})
    c.app_ref = app
    yield c
    app.state.engine.dispose()


def create(c, kind, **body):
    return c.post(f"/cases/C1/{kind}", json=body, headers=H("alice"))


def approve(c, kind, version):
    d = c.post(f"/cases/C1/{kind}/{version}/request-review", json={"reviewer_id": APPROVERS[kind]},
               headers=H("alice")).json()
    r = c.post(f"/cases/C1/{kind}/{version}/decision", headers=H(APPROVERS[kind]),
               json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]})
    assert r.status_code == 200, r.text
    return r.json()


def chain(c):
    for kind in ("ncr", "containment", "rca"):
        assert create(c, kind).status_code == 201
        approve(c, kind, 1)


def revise(c, **kw):
    return c.post("/cases/C1/source-revisions", headers=H("alice"),
                  json={"asset": spi_correction(7, **kw), "reason": "SPI re-measurement"})


def status(c, kind, version=1):
    return c.get(f"/cases/C1/{kind}/{version}", headers={"X-User": "alice"}).json()["status"]


def review(c, kind, version, reviewer=None):
    return c.post(f"/cases/C1/{kind}/{version}/request-review", headers=H("alice"),
                  json={"reviewer_id": reviewer or APPROVERS[kind]})


def test_ncr_containment_rca_chain_with_role_gates(env):
    c = env
    assert create(c, "containment").status_code == 409  # no NCR draft to build on
    assert create(c, "ncr").status_code == 201
    cont = create(c, "containment").json()  # drafts may be written ahead ...
    assert cont["based_on"] == ["NCR v1"] and "NOT_EXECUTED" in cont["note"]
    assert review(c, "containment", 1).status_code == 409  # ... but D3 is not reviewed before D2 is approved
    steps = c.get("/cases/C1/stages", headers={"X-User": "alice"}).json()
    assert [(s["step"], s["approval_open"]) for s in steps] == [("D2", True), ("D3", False), ("D4", False)]
    approve(c, "ncr", 1)
    assert create(c, "rca").status_code == 201
    assert review(c, "rca", 1).status_code == 409  # containment not approved yet
    assert any(cl["classification"] == "PROPOSAL" for cl in cont["claims"])
    assert not any(DONE_CLAIM.search(cl["text"]) for cl in cont["claims"])
    bad = c.post("/cases/C1/containment/1/request-review", json={"reviewer_id": "bob"}, headers=H("alice"))
    assert bad.status_code == 422  # NCR reviewer cannot approve a containment plan
    d = c.post("/cases/C1/containment/1/request-review", json={"reviewer_id": "erin"}, headers=H("alice")).json()
    wrong = c.post("/cases/C1/containment/1/decision", headers=H("frank"),
                   json={"decision": "APPROVE", "content_sha256": d["content_sha256"]})
    assert wrong.status_code == 403
    c.post("/cases/C1/containment/1/decision", headers=H("erin"),
           json={"decision": "APPROVE", "content_sha256": d["content_sha256"]})
    rca = c.get("/cases/C1/rca/1", headers={"X-User": "alice"}).json()
    assert rca["based_on"] == ["NCR v1", "CONTAINMENT v1"] and "UNCONFIRMED" in rca["note"]
    assert any(cl["classification"] == "HYPOTHESIS" and "UNCONFIRMED" in cl["text"] for cl in rca["claims"])
    assert approve(c, "rca", 1)["status"] == "APPROVED"
    assert "Cause status: UNCONFIRMED" in c.get("/cases/C1/rca/1/html", headers={"X-User": "alice"}).text
    done = create(c, "containment", extra_claims=[{"classification": "UNKNOWN", "text": "Board P02/B01 was quarantined."}])
    assert done.status_code == 422


def test_correction_reopens_exactly_the_dependent_documents(env):
    c = env
    chain(c)
    with Session(c.app_ref.state.engine) as s:
        before = [(a.id, a.action, a.content_sha256, a.created_at) for a in s.scalars(select(ApprovalEvent))]
    r = revise(c)
    assert r.status_code == 201, r.text
    hit = {d["doc_type"]: d for d in r.json()["documents"]}
    assert set(hit) == {"NCR", "RCA"}  # the containment plan cites no SPI row
    assert all(d["status_before"] == "APPROVED" and d["status_after"] == "REVALIDATION_REQUIRED" for d in hit.values())
    assert [d["doc_type"] for d in r.json()["basis_changed"]] == ["CONTAINMENT"]  # content intact, basis moved
    assert status(c, "containment") == "BASIS_CHANGED"
    ncr1 = c.get("/cases/C1/ncr/1", headers={"X-User": "alice"}).json()
    texts = {cl["claim_id"]: cl["text"] for cl in ncr1["claims"]}
    assert hit["NCR"]["claims"] and all("P02/B01" in texts[cid] for cid in hit["NCR"]["claims"])
    untouched = [cid for cid, t in texts.items() if cid not in hit["NCR"]["claims"]]
    assert untouched  # other claims of the same NCR are not flagged
    with Session(c.app_ref.state.engine) as s:
        after = [(a.id, a.action, a.content_sha256, a.created_at) for a in s.scalars(select(ApprovalEvent))]
    assert after == before  # approvals are history, not rewritten
    events = [t["event"] for t in c.get("/cases/C1/timeline", headers={"X-User": "alice"}).json()]
    assert events.count("REVALIDATION_REQUIRED") == 2 and events.count("BASIS_CHANGED") == 1
    assert "SOURCE_REVISED" in events
    cont = c.get("/cases/C1/containment/1", headers={"X-User": "alice"}).json()

    def check(user="erin", decision="NO_SCOPE_IMPACT"):
        return c.post("/cases/C1/containment/1/basis-check", headers=H(user), json={
            "decision": decision, "comment": "same boards held", "content_sha256": cont["content_sha256"]})

    assert check().status_code == 409  # NCR v2 is not approved yet
    ncr2 = create(c, "ncr").json()
    mean_v1 = next(cl for cl in ncr1["claims"] if "Mean SPI" in cl["text"] and "P02/B01" in cl["text"])
    mean_v2 = next(cl for cl in ncr2["claims"] if "Mean SPI" in cl["text"] and "P02/B01" in cl["text"])
    assert mean_v2["value"] == round(mean_v1["value"] - 0.015, 4)  # one of two pins re-measured -0.03
    approve(c, "ncr", 2)
    assert create(c, "rca").json()["based_on"] == ["NCR v2", "CONTAINMENT v1"]
    assert review(c, "rca", 2).status_code == 409  # containment scope not yet reconfirmed by QA
    assert check("bob").status_code == 403 and check("frank").status_code == 403
    done = check()
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"
    assert done.json()["decisions"][-1]["action"] == "NO_SCOPE_IMPACT" and "NCR v2" in done.json()["decisions"][-1]["comment"]
    assert approve(c, "rca", 2)["status"] == "APPROVED"
    assert c.get("/cases/C1/change-impact", headers={"X-User": "alice"}).json()[0]["changed_evidence"]


def test_stale_draft_basis_and_revise_decision(env):
    c = env
    create(c, "ncr")
    approve(c, "ncr", 1)
    create(c, "containment")  # drafted on NCR v1
    create(c, "ncr")
    approve(c, "ncr", 2)
    r = review(c, "containment", 1)
    assert r.status_code == 409 and "Create a new draft" in r.json()["detail"]
    assert create(c, "containment").json()["based_on"] == ["NCR v2"]
    approve(c, "containment", 2)
    revise(c, row_id="SPI-P01-B01-1")  # a false-alarm board: NCR cites it, containment does not
    assert status(c, "containment", 2) == "BASIS_CHANGED"
    sha = c.get("/cases/C1/containment/2", headers={"X-User": "alice"}).json()["content_sha256"]
    out = c.post("/cases/C1/containment/2/basis-check", headers=H("erin"),
                 json={"decision": "REVISE", "comment": "re-scope after NCR", "content_sha256": sha}).json()
    assert out["status"] == "REVALIDATION_REQUIRED"


def test_correction_on_an_uncited_row_reopens_nothing(env):
    c = env
    create(c, "ncr")
    approve(c, "ncr", 1)
    r = revise(c, row_id="SPI-P01-B02-1")  # board with no AOI FAIL: no claim cites its SPI rows
    assert r.status_code == 201 and r.json()["documents"] == [] and r.json()["changed_evidence"]
    assert status(c, "ncr") == "APPROVED"


def test_pending_review_is_held_and_predictions_propagate(env):
    c = env
    c.post("/models/train", json={}, headers={"X-User": "alice"})
    preds = c.post("/cases/C1/predictions", json={}, headers=H("alice")).json()["predictions"]
    target = next(p for p in preds if p["target_key"] == ["P02", "B01"])
    create(c, "ncr")
    d = c.post("/cases/C1/ncr/1/request-review", json={"reviewer_id": "bob"}, headers=H("alice")).json()
    r = revise(c).json()
    assert {target["evidence_id"], target["xai_evidence_id"]} <= set(r["derived"])
    assert all(p["evidence_id"] not in r["derived"] for p in preds if p is not target)
    doc = c.get("/cases/C1/ncr/1", headers={"X-User": "alice"}).json()
    assert doc["status"] == "REVALIDATION_REQUIRED" and doc["reviews"][0]["state"] == "HELD"
    late = c.post("/cases/C1/ncr/1/decision", headers=H("bob"),
                  json={"decision": "APPROVE", "content_sha256": d["content_sha256"]})
    assert late.status_code in (403, 409)


def test_revision_input_is_validated_and_fails_closed(env):
    c = env

    def post(asset, user="alice"):
        return c.post("/cases/C1/source-revisions", json={"asset": asset, "reason": "fix"}, headers=H(user))

    good = spi_correction(7)
    assert post({**good, "supersedes_asset_id": "synthetic:spi_measurements:v1"}).status_code == 422  # not latest
    assert post({**good, "sensitivity": "CONFIDENTIAL"}).status_code == 422
    assert post({**good, "data_origin": "REAL"}).status_code == 422
    assert post({**good, "content_sha256": "0" * 64}).status_code == 422
    ghost = {**good["records"][0], "original_row_id": "SPI-NEW-ROW"}
    assert post({**good, "records": [ghost], "content_sha256": sha256([ghost])}).status_code == 422
    moved = {**good["records"][0], "board_id": "B02"}
    assert post({**good, "records": [moved], "content_sha256": sha256([moved])}).status_code == 422
    assert post(good, "bob").status_code == 403
    dave = c.post("/cases/C1/source-revisions", json={"asset": good, "reason": "fix"}, headers=H("dave"))
    assert dave.status_code == 403  # an AUTHOR not assigned to the case
    key = H("alice")
    first = c.post("/cases/C1/source-revisions", json={"asset": good, "reason": "fix"}, headers=key)
    again = c.post("/cases/C1/source-revisions", json={"asset": good, "reason": "fix"}, headers=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert post(good).status_code == 422  # same asset id cannot be imported twice


def test_audit_tables_are_append_only(env, tmp_path):
    c = env
    create(c, "ncr")
    approve(c, "ncr", 1)
    with Session(c.app_ref.state.engine) as s:
        for stmt in ("UPDATE approval_events SET action='REJECT'", "DELETE FROM approval_events",
                     "UPDATE workflow_events SET detail='x'", "DELETE FROM workflow_events"):
            with pytest.raises(DatabaseError, match="append-only"):
                s.execute(text(stmt))
            s.rollback()
        assert s.scalar(select(WorkflowEvent.id).limit(1))
    url = f"sqlite:///{(tmp_path / 'mig.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        triggers = set(conn.scalars(text("SELECT name FROM sqlite_master WHERE type='trigger'")))
    engine.dispose()
    assert triggers == {f"{t}_no_{op}" for t in APPEND_ONLY for op in ("update", "delete")}  # migrations == models
    assert {"approval_events", "workflow_events", "doc_comments", "audit_chain"} <= set(APPEND_ONLY)


REPLY = {"model": MODEL, "choices": [{"message": {"role": "assistant", "content": "{}"}}], "usage": {}}


@pytest.mark.parametrize("leak", ['{"data_origin":"REAL"}', '{"sensitivity": "CONFIDENTIAL"}',
                                  '{"source_origin":"UNKNOWN"}', "customer CONFIDENTIAL note"])
def test_gateway_blocks_unapproved_data_in_any_message(leak):
    opener = Opener(REPLY)
    tool_msg = {"role": "tool", "tool_call_id": "t1", "content": json.dumps({"events": [json.loads(leak)]})
                if leak.startswith("{") else leak}
    with pytest.raises(EgressBlocked):
        MetaProvider("k-test-0000", opener=opener).chat([{"role": "user", "content": "x"}, tool_msg], [])
    assert opener.requests == []  # nothing left the process


def test_gateway_passes_approved_synthetic_payload():
    opener = Opener(REPLY)
    rec = {"data_origin": "SYNTHETIC", "sensitivity": "APPROVED_FOR_EXTERNAL", "volume_mm3": 0.1}
    MetaProvider("k-test-0000", opener=opener).chat([{"role": "tool", "content": json.dumps(rec)}], [])
    assert len(opener.requests) == 1


def test_confidential_row_stays_out_of_prompts_logs_and_run_records(env, caplog):
    c = env
    with Session(c.app_ref.state.engine) as s, s.begin():
        ev = s.scalars(select(SourceEvent).where(SourceEvent.entity_type == "aoi_inspections")).first()
        ev.sensitivity, ev.raw_json = "CONFIDENTIAL", '{"note":"SECRET-MARKER-S6"}'
    provider = c.app_ref.state.provider
    provider.replies[:] = [LOOKUP, final({"summary": "s", "findings": [{"classification": "UNKNOWN", "text": "t"}]})]
    with caplog.at_level(logging.DEBUG):
        run = c.post("/cases/C1/investigations", json={"use_history": True}, headers=H("alice")).json()
    assert not run["tool_calls"][1]["ok"]
    assert not any("SECRET-MARKER-S6" in m for m in provider.seen)
    assert "SECRET-MARKER-S6" not in caplog.text
    with Session(c.app_ref.state.engine) as s:
        logged = [json.dumps([t.arguments_json, t.error]) for t in s.scalars(select(ToolCall))]
    assert not any("SECRET-MARKER-S6" in x for x in logged) and "SECRET-MARKER-S6" not in json.dumps(run)


def test_authorization_regression_on_every_case_route(env):
    c = env
    def walk(routes):  # FastAPI keeps included routers as wrappers
        for r in routes:
            yield from walk(r.original_router.routes) if hasattr(r, "original_router") else [r]

    # every method of every /cases/{case_id}/... route, path values filled by name only: the app-wide case guard
    # (main.case_guard) answers before any route code, so no route-specific value or FastAPI internal is needed
    paths, calls = set(), set()
    for route in walk(c.app_ref.routes):
        if "{case_id}" not in getattr(route, "path", ""):
            continue
        kinds = APPROVERS if "{kind" in route.path else [None]
        for kind in kinds:
            url = re.sub(r"\{(\w+)(:\w+)?\}", lambda m, kind=kind: "C1" if m.group(1) == "case_id" else
                         kind if m.group(1) == "kind" else "1", route.path)
            paths.add(url)
            calls |= {(m, url) for m in route.methods - {"HEAD"}}
    assert {"/cases/C1/change-impact", "/cases/C1/rca", "/cases/C1/ncr/1", "/cases/C1/timeline"} <= paths
    for method, p in sorted(calls):
        assert c.request(method, p, json={}).status_code == 401, (method, p)
        r = c.request(method, p, json={}, headers={"X-User": "carol", "Idempotency-Key": "k" * 12})
        assert r.status_code == 403, (method, p, r.status_code)  # carol is not assigned
    for kind in ("ncr", "containment", "rca"):
        assert create(c, kind).status_code in (201, 409)
        assert c.post(f"/cases/C1/{kind}", json={}, headers=H("bob")).status_code == 403
        for user in {"bob", "erin", "frank"} - {APPROVERS[kind]}:
            r = c.post(f"/cases/C1/{kind}/1/decision", headers=H(user),
                       json={"decision": "APPROVE", "content_sha256": "x"})
            assert r.status_code == 403, (kind, user)
