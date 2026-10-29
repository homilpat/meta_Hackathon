"""G7: D7 counts only released, in-effect revisions raised by the case with training done; D8 closes in one
re-evaluation of every gate and archives its snapshot; reopening appends."""

import pytest

from app.synthetic import spi_correction
from tests.v5_util import (
    CLOSE,
    H,
    acknowledge_all,
    deploy,
    line_client,
    ok,
    ready_to_close,
    revise_doc,
)


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def close(c, user="bob", **kw):
    return c.post("/cases/L/closure", json={**CLOSE, **kw}, headers=H(user))


def blocks(c):
    return c.get("/cases/L/closure", headers=H("bob")).json()["blocks"]


def test_valid_closure_archives_a_snapshot(c):
    ids = ready_to_close(c)
    assert c.get("/cases/L/prevention", headers=H("alice")).json()["state"] == "DONE"
    assert any("acknowledged" in b for b in blocks(c))
    acknowledge_all(c)
    assert blocks(c) == []
    out = ok(close(c))
    snap = out["snapshot"]
    assert out["decision"] == "CLOSED" and len(out["snapshot_sha256"]) == 64
    assert snap["confirmed_causes"] == [ids["cause"]] and snap["data_origin"] == "SYNTHETIC"
    assert {p["doc_number"] for p in snap["prevention"]} == {"FMEA-SMT-001", "SOP-SMT-010"}
    assert all(v in ("DONE", "APPROVED", None) for k, v in snap["state"].items() if k != "D8")
    assert c.get("/cases/L/gates", headers=H("alice")).json()["state"]["D8"] == "CLOSED"
    assert close(c).status_code == 409  # already closed


def test_fmea_claim_without_a_real_revision_is_not_d7(c):
    ready_to_close(c, effective=True)
    r = deploy(c, "L", "FMEA-SMT-001", 99)
    assert r.status_code == 422 and "not in the registry" in r.json()["detail"]
    r = deploy(c, "L", "CP-SMT-001", 2)  # an existing fixture revision, not a change made for this case
    assert r.status_code == 422 and "not revised for this case" in r.json()["detail"]
    draft = ok(c.post("/controlled-documents/revisions", headers=H("alice"), json={
        "doc_number": "CP-SMT-001", "kind": "CONTROL_PLAN", "base_revision": 2, "title": "SMT print control plan",
        "body": "Stop line on 2 consecutive low-volume boards.", "case_id": "L"}))
    r = deploy(c, "L", "CP-SMT-001", draft["revision"])
    assert r.status_code == 422 and "DRAFT" in r.json()["detail"]


def test_policy_required_document_kind_blocks_closure(c):
    import copy

    from app.policy import DEFAULT_BODY

    ready_to_close(c)
    acknowledge_all(c)
    body = {**copy.deepcopy(DEFAULT_BODY), "prevention_required": ["FMEA", "SOP", "CONTROL_PLAN"]}
    ok(c.post("/policies", json={"policy_id": "DEFAULT", "body": body}, headers=H("bob")))
    r = close(c)
    assert r.status_code == 409 and "no CONTROL_PLAN revision deployed" in r.json()["detail"]


def test_untrained_operator_keeps_d7_open(c):
    ids = ready_to_close(c)
    sop = revise_doc(c, "L", "SOP-SMT-010", "SOP", ids["sop"], "Stencil cleaning and inspection",
                     "Clean every 6 h of print time, counter-enforced.")
    ok(deploy(c, "L", "SOP-SMT-010", sop, operators=("OP-1", "OP-2", "OP-3"), trained=("OP-1",)))
    p = c.get("/cases/L/prevention", headers=H("alice")).json()
    assert p["state"] == "IN_PROGRESS" and any("not trained" in r for r in p["reasons"])
    acknowledge_all(c)
    r = close(c)
    assert r.status_code == 409 and "not trained" in r.json()["detail"]


def test_superseded_revision_is_not_current_prevention(c):
    ids = ready_to_close(c)
    revise_doc(c, "L", "SOP-SMT-010", "SOP", ids["sop"], "Stencil cleaning and inspection", "A later change.")
    p = c.get("/cases/L/prevention", headers=H("alice")).json()
    assert p["state"] == "IN_PROGRESS" and any("superseded" in r for r in p["reasons"])


def test_open_d6_failure_blocks_closure(c):
    ready_to_close(c, effective=False)
    acknowledge_all(c)
    r = close(c)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "D4 is not complete" in detail and "D6 is not complete (is NOT_EFFECTIVE)" in detail


def test_changed_evidence_blocks_closure(c):
    ready_to_close(c)
    acknowledge_all(c)
    ok(c.post("/cases/L/source-revisions", headers=H("alice"), json={
        "asset": spi_correction(7, row_id="SPI-L02-P02-B2-C01-1", version=2, line=True), "reason": "re-measured"}))
    r = close(c)
    assert r.status_code == 409 and "D2 is not complete" in r.json()["detail"]


def test_signers_and_notification(c):
    ready_to_close(c)
    assert c.post("/cases/L/closure/acknowledgements", headers=H("carol"),
                  json={"contribution": "not on the team"}).status_code == 403
    r = c.post("/controlled-documents/revisions", headers=H("alice"), json={
        "doc_number": "CP-SMT-001", "kind": "CONTROL_PLAN", "base_revision": 2, "title": "SMT print control plan",
        "body": "Stop line on 2 consecutive low-volume boards.", "case_id": "L"})
    assert c.post(f"/controlled-documents/CP-SMT-001/revisions/{r.json()['revision']}/release", headers=H("alice"),
                  json={"reason": "self release"}).status_code == 403
    acknowledge_all(c)
    assert close(c, user="frank").status_code == 403  # not the D8 approver
    r = close(c, customer_notification_ref=None)
    assert r.status_code == 409 and "customer_notification_ref" in r.json()["detail"]
    assert c.post("/cases/L/closure", headers=H("bob"), json={**CLOSE, "residual_risks": []}).status_code == 422


def test_reopen_keeps_the_closed_archive_and_needs_new_acknowledgements(c):
    ready_to_close(c)
    acknowledge_all(c)
    closed = ok(close(c))
    assert c.post("/cases/L/closure/reopen", headers=H("frank"), json={"reason": "customer reports a recurrence"}
                  ).status_code == 403
    ok(c.post("/cases/L/closure/reopen", headers=H("bob"), json={"reason": "customer reports a recurrence"}))
    st = c.get("/cases/L/closure", headers=H("bob")).json()
    assert [h["decision"] for h in st["history"]] == ["CLOSED", "REOPENED"]
    assert st["history"][0]["snapshot_sha256"] == closed["snapshot_sha256"]
    assert st["state"]["D8"] == "REOPENED" and any("acknowledged" in b for b in st["blocks"])
    acknowledge_all(c)
    assert ok(close(c))["decision"] == "CLOSED"
