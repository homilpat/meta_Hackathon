import uuid

import pytest
from fastapi.testclient import TestClient

from app import ncr
from app.db import Base
from app.main import create_app
from app.synthetic import generate


@pytest.fixture
def app_client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'case.db'}")
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


def call(client, user, method, path, body=None, key=None):
    headers = {"X-User": user}
    if key is not False:
        headers["Idempotency-Key"] = key or uuid.uuid4().hex
    return client.request(method, path, json=body, headers=headers)


@pytest.fixture
def case(app_client):
    """Case C1 owned by alice, bob assigned as reviewer, carol and dave not assigned."""
    c = app_client
    assert call(c, "alice", "POST", "/cases", {"case_id": "C1"}).status_code == 201
    assert call(c, "alice", "POST", "/cases/C1/sources", generate(7)).status_code == 201
    assert call(c, "alice", "POST", "/cases/C1/assignments", {"user_id": "bob"}).status_code == 201
    return c


def draft(c, user="alice", **kw):
    r = call(c, user, "POST", "/cases/C1/ncr", kw or {})
    assert r.status_code == 201, r.text
    return r.json()


def to_review(c, version, reviewer="bob"):
    r = call(c, "alice", "POST", f"/cases/C1/ncr/{version}/request-review", {"reviewer_id": reviewer})
    assert r.status_code == 200, r.text
    return r.json()


def decide(c, doc, user="bob", decision="APPROVE", **kw):
    body = {"decision": decision, "comment": "ok", "content_sha256": doc["content_sha256"], **kw}
    return call(c, user, "POST", f"/cases/C1/ncr/{doc['version']}/decision", body)


def test_every_numeric_or_observed_claim_cites_existing_evidence(case):
    doc = draft(case)
    known = {e["evidence_id"] for e in call(case, "alice", "GET", "/cases/C1/evidence").json()}
    classes = {c["classification"] for c in doc["claims"]}
    assert {"OBSERVED", "CALCULATED", "HYPOTHESIS", "UNKNOWN"} <= classes
    for c in doc["claims"]:
        assert set(c["evidence_ids"]) <= known
        if c["classification"] in ("OBSERVED", "CALCULATED") or c["value"] is not None:
            assert c["evidence_ids"]
    assert any(c["classification"] == "UNKNOWN" and "not a PASS" in c["text"] for c in doc["claims"])
    assert doc["builder"] == ncr.BUILDER and doc["status"] == "DRAFT"


def test_calculated_mean_matches_source_rows(case):
    doc = draft(case)
    claim = next(c for c in doc["claims"] if c["unit"] == "mm3" and "P02/B01" in c["text"])
    vols = [e["record"]["volume_mm3"] for e in call(case, "alice", "GET", "/cases/C1/events").json()
            if e["entity_type"] == "spi_measurements" and e["entity_key"][:2] == ["P02", "B01"]]
    assert claim["value"] == round(sum(vols) / len(vols), 4)


def test_validator_rejects_unbacked_numbers_and_unknown_evidence():
    ok = {"claim_id": "C1", "classification": "OBSERVED", "text": "t", "evidence_ids": ["EV-1"]}
    ncr.validate_claims([ok], {"EV-1"})
    with pytest.raises(ValueError, match="needs evidence"):
        ncr.validate_claims([{**ok, "evidence_ids": []}], {"EV-1"})
    with pytest.raises(ValueError, match="numeric"):
        ncr.validate_claims([{**ok, "classification": "UNKNOWN", "evidence_ids": [], "value": 3.0}], set())
    with pytest.raises(ValueError, match="unknown evidence"):
        ncr.validate_claims([{**ok, "evidence_ids": ["EV-9"]}], {"EV-1"})
    with pytest.raises(ValueError, match="classification"):
        ncr.validate_claims([{**ok, "classification": "CONFIRMED"}], {"EV-1"})


def test_extra_claim_without_evidence_is_rejected(case):
    bad = {"classification": "CALCULATED", "text": "defect rate 12%", "value": 12.0}
    r = call(case, "alice", "POST", "/cases/C1/ncr", {"extra_claims": [bad]})
    assert r.status_code == 422
    assert call(case, "alice", "GET", "/cases/C1/ncr").json() == []


def test_ncr_needs_sources(app_client):
    call(app_client, "alice", "POST", "/cases", {"case_id": "EMPTY"})
    assert call(app_client, "alice", "POST", "/cases/EMPTY/ncr", {}).status_code == 422


def test_full_approval_flow_with_hash_bound_history(case):
    doc = to_review(case, draft(case)["version"])
    assert doc["status"] == "IN_REVIEW"
    done = decide(case, doc)
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"
    after = call(case, "bob", "GET", "/cases/C1/ncr/1").json()  # "refresh": history is persisted
    assert after["decisions"][0]["actor_id"] == "bob"
    assert after["decisions"][0]["content_sha256"] == doc["content_sha256"]
    events = [t["event"] for t in call(case, "bob", "GET", "/cases/C1/timeline").json()]
    assert events == ["ASSIGNED", "DRAFT_CREATED", "REVIEW_REQUESTED", "APPROVE"]


def test_author_cannot_approve_and_reviewer_cannot_author(case):
    doc = to_review(case, draft(case)["version"])
    assert decide(case, doc, user="alice").status_code == 403
    assert call(case, "bob", "POST", "/cases/C1/ncr", {}).status_code == 403
    assert call(case, "bob", "POST", "/cases", {"case_id": "X"}).status_code == 403


def test_other_case_access_is_403(case):
    for user in ("carol", "dave"):
        for path in ("/cases/C1", "/cases/C1/evidence", "/cases/C1/ncr", "/cases/C1/timeline",
                     "/cases/C1/events", "/cases/C1/ncr/1/html"):
            assert call(case, user, "GET", path).status_code == 403, (user, path)
        assert call(case, user, "GET", "/cases").json() == []
    assert call(case, "dave", "POST", "/cases/C1/ncr", {}).status_code == 403
    assert call(case, "alice", "GET", "/cases/NOPE").status_code == 404


def test_unassigned_or_unrequested_reviewer_cannot_decide(case):
    call(case, "alice", "POST", "/cases/C1/assignments", {"user_id": "carol"})
    doc = to_review(case, draft(case)["version"], reviewer="bob")
    assert decide(case, doc, user="carol").status_code == 403  # assigned but never asked
    r = call(case, "alice", "POST", "/cases/C1/ncr/1/request-review", {"reviewer_id": "dave"})
    assert r.status_code in (409, 422)


def test_stale_version_cannot_be_approved(case):
    v1 = to_review(case, draft(case)["version"])
    v2 = draft(case)
    assert v2["version"] == 2
    assert call(case, "alice", "GET", "/cases/C1/ncr/1").json()["status"] == "SUPERSEDED"
    assert decide(case, v1).status_code == 409


def test_changed_content_hash_is_409(case):
    doc = to_review(case, draft(case)["version"])
    assert decide(case, doc, content_sha256="0" * 64).status_code == 409
    assert decide(case, doc).status_code == 200


def test_request_info_closes_the_review_and_needs_a_new_version(case):
    doc = to_review(case, draft(case)["version"])
    assert decide(case, doc, decision="REQUEST_INFO").json()["status"] == "INFO_REQUESTED"
    assert decide(case, doc).status_code == 403  # review request already consumed
    assert draft(case)["version"] == 2


def test_retries_do_not_duplicate(case):
    key = "retry-key-0001"
    a = call(case, "alice", "POST", "/cases/C1/ncr", {}, key=key)
    b = call(case, "alice", "POST", "/cases/C1/ncr", {}, key=key)
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    assert len(call(case, "alice", "GET", "/cases/C1/ncr").json()) == 1
    doc = to_review(case, 1)
    body = {"decision": "APPROVE", "comment": "ok", "content_sha256": doc["content_sha256"]}
    r1 = call(case, "bob", "POST", "/cases/C1/ncr/1/decision", body, key="decide-key-01")
    r2 = call(case, "bob", "POST", "/cases/C1/ncr/1/decision", body, key="decide-key-01")
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert len(call(case, "bob", "GET", "/cases/C1/ncr/1").json()["decisions"]) == 1


def test_missing_idempotency_key_and_unknown_user(case):
    assert call(case, "alice", "POST", "/cases/C1/ncr", {}, key=False).status_code == 422
    assert call(case, "mallory", "GET", "/cases").status_code == 401
    assert case.get("/cases").status_code == 401


def test_html_marks_generator_and_escapes(case):
    extra = {"classification": "UNKNOWN", "text": "<script>alert(1)</script>"}
    draft(case, extra_claims=[extra])
    page = call(case, "bob", "GET", "/cases/C1/ncr/1/html").text
    assert ncr.BUILDER in page and "no AI model used" in page
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_ui_is_served(app_client):
    page = app_client.get("/ui")
    assert page.status_code == 200 and "QualityOps AI" in page.text
