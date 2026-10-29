"""G9 Human Docs: versioned editing, diff, re-validation, concurrency, AI proposals that are never auto-applied.
MASTER TC-B-01 … TC-B-04."""

import copy
import json

import pytest

from app.policy import DEFAULT_BODY
from tests.test_s3_investigation import Scripted, final
from tests.test_v5_5_g8 import l02_aoi, ncr, rate_claim, true_rate
from tests.v5_util import H, line_client, ok


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def doc(c, v=1):
    return ok(c.get(f"/cases/L/ncr/{v}", headers=H("alice")), 200)


def edit(c, v, user="alice", **body):
    body.setdefault("expected_sha256", doc(c, v)["content_sha256"])
    body.setdefault("reason", "correct the rate wording")
    return c.post(f"/cases/L/ncr/{v}/edits", json=body, headers=H(user))


def with_rate(c):
    rate = true_rate(c)
    d = ok(ncr(c, rate_claim(c, rate)))
    return rate, d["claims"][-1]["claim_id"]


def approve(c, v):
    d = ok(c.post(f"/cases/L/ncr/{v}/request-review", json={"reviewer_id": "bob"}, headers=H("alice")), 200)
    return c.post(f"/cases/L/ncr/{v}/decision", headers=H("bob"),
                  json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]})


def test_edit_creates_a_new_version_with_diff_and_validation_and_keeps_the_approved_one(c):  # TC-B-01
    rate, cid = with_rate(c)
    ok(approve(c, 1), 200)
    before = doc(c, 1)
    one = round(rate, 1)
    r = ok(edit(c, 1, changes=[{"claim_id": cid, "text": f"AOI FAIL share in lot L02 is about {one}%."}]))
    assert r["version"] == 2 and r["status"] == "DRAFT" and r["builder"] == "HUMAN_EDIT:NCR v1"
    assert r["diff"] == [{"claim_id": cid, "change": "CHANGED", "fields": {"text": [
        f"AOI FAIL share in lot L02 is {rate}%.", f"AOI FAIL share in lot L02 is about {one}%."]}}]
    assert r["validation"]["result"] in ("PASS", "WARN") and not r["validation"]["stale"]
    assert r["edit_reason"] == "correct the rate wording"
    after = doc(c, 1)  # the approved snapshot is untouched
    assert after["status"] == "APPROVED" and after["content_sha256"] == before["content_sha256"]
    assert after["claims"] == before["claims"] and after["decisions"] == before["decisions"]
    d = ok(c.get("/cases/L/ncr/2/diff", headers=H("bob")), 200)
    assert d["from"] == 1 and d["diff"] == r["diff"]
    trail = [t for t in doc(c, 2)["trail"] if t["event"] == "DRAFT_EDITED"]
    assert trail and trail[0]["actor_id"] == "alice" and "correct the rate wording" in trail[0]["detail"]
    assert c.get("/audit/verify", headers=H("bob")).json()["ok"] is True


def test_wrong_number_other_lot_and_false_execution_or_cause_are_blocked(c):  # TC-B-02
    rate, cid = with_rate(c)
    for change, says in (({"text": "AOI FAIL share in lot L02 is 2.1%."}, "but the claim value is"),
                         ({"value": 2.1, "text": "AOI FAIL share in lot L02 is 2.1%."}, "server recomputation"),
                         ({"text": f"AOI FAIL share in lots L02 and L03 is {rate}%."}, "text names lot")):
        r = edit(c, 1, changes=[{"claim_id": cid, **change}])
        assert r.status_code == 422 and says in r.json()["detail"], (change, r.text)
    for text in ("Lot L02 was held and quarantined.", "The defects in lot L02 were caused by stencil wear."):
        r = edit(c, 1, add=[{"classification": "OBSERVED", "text": text, "evidence_ids": l02_aoi(c)[:1]}])
        assert r.status_code == 422, text
    assert doc(c, 1)["status"] == "DRAFT"  # nothing was stored
    assert c.get("/cases/L/ncr/2", headers=H("alice")).status_code == 404


def test_concurrent_edit_review_and_stale_validation_are_refused(c):  # TC-B-03
    rate, cid = with_rate(c)
    sha = doc(c, 1)["content_sha256"]
    one = round(rate, 1)
    ok(edit(c, 1, expected_sha256=sha, changes=[{"claim_id": cid, "text": f"AOI FAIL in lot L02: {one}%."}]))
    late = edit(c, 1, expected_sha256=sha, changes=[{"claim_id": cid, "text": f"L02 AOI FAIL is {one}%."}])
    assert late.status_code == 409  # the other editor's base is no longer the latest
    assert edit(c, 2, expected_sha256=sha, changes=[{"claim_id": cid, "text": "x"}]).status_code == 409  # wrong hash
    # edit while in review: the pending review is superseded and can no longer be decided
    d = ok(c.post("/cases/L/ncr/2/request-review", json={"reviewer_id": "bob"}, headers=H("alice")), 200)
    ok(edit(c, 2, changes=[{"claim_id": cid, "text": f"AOI FAIL share in lot L02: {one}%."}]))
    r = c.post("/cases/L/ncr/2/decision", headers=H("bob"),
               json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]})
    assert r.status_code == 409 and doc(c, 2)["status"] == "SUPERSEDED"
    # policy changes after validation: the old validation cannot be reused for approval
    d = ok(c.post("/cases/L/ncr/3/request-review", json={"reviewer_id": "bob"}, headers=H("alice")), 200)
    ok(c.post("/policies", json={"policy_id": "DEFAULT", "body": copy.deepcopy(DEFAULT_BODY)}, headers=H("bob")))
    r = c.post("/cases/L/ncr/3/decision", headers=H("bob"),
               json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]})
    assert r.status_code == 409 and "stale" in r.json()["detail"]
    ok(c.post("/cases/L/ncr/3/validate", headers=H("bob")))
    ok(c.post("/cases/L/ncr/3/decision", headers=H("bob"),
              json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]}), 200)
    assert c.get("/audit/verify", headers=H("bob")).json()["ok"] is True


def test_roles_case_scope_and_self_approval(c):
    _, cid = with_rate(c)
    assert edit(c, 1, user="bob", changes=[{"claim_id": cid, "text": "x"}]).status_code == 403  # reviewer, not author
    assert edit(c, 1, reason="ok", changes=[{"claim_id": cid, "text": "x"}]).status_code == 422  # reason too short
    assert edit(c, 1, changes=[{"claim_id": "C9999", "text": "x"}]).status_code == 422
    assert c.get("/cases/L/ncr/1", headers=H("ivan")).status_code in (401, 403)  # unknown / unassigned user
    r = ok(c.post("/cases/L/ncr/1/request-review", json={"reviewer_id": "alice"}, headers=H("alice")), 422) \
        if False else c.post("/cases/L/ncr/1/request-review", json={"reviewer_id": "alice"}, headers=H("alice"))
    assert r.status_code == 422  # the editor cannot review their own version


def test_ai_proposal_is_not_applied_until_submitted_and_offline_keeps_manual_path(tmp_path):  # TC-B-04
    (tmp_path / "off").mkdir(), (tmp_path / "on").mkdir()
    off = line_client(tmp_path / "off")
    _, cid = with_rate(off)
    r = off.post("/cases/L/ncr/1/edit-proposals", json={"instruction": "shorter"}, headers=H("alice"))
    assert r.status_code == 503 and "AI OFFLINE" in r.json()["detail"]
    assert edit(off, 1, changes=[{"claim_id": cid, "text": "AOI FAIL share in lot L02, see value."}]).json()[
        "validation"]["result"] in ("PASS", "WARN")  # manual edit + validation work without a key
    off.app_ref.state.engine.dispose()

    model = Scripted(final({"changes": [{"claim_id": "C1", "text": "Short."}, {"claim_id": "C404", "text": "x"}]}))
    on = line_client(tmp_path / "on", provider=model)
    ok(ncr(on))
    p = ok(on.post("/cases/L/ncr/1/edit-proposals", json={"instruction": "shorter"}, headers=H("alice")), 200)
    assert p["applied"] is False and p["provider_mode"] == "TEST_DOUBLE"
    assert p["changes"] == [{"claim_id": "C1", "text": "Short."}]  # unknown claim ids dropped
    assert on.get("/cases/L/ncr/2", headers=H("alice")).status_code == 404  # nothing applied
    assert doc(on, 1)["status"] == "DRAFT"
    assert "Short." not in json.dumps(doc(on, 1)["claims"])
    events = [e["event"] for e in on.get("/cases/L/timeline", headers=H("alice")).json()]
    assert "AI_EDIT_PROPOSED" in events
    on.app_ref.state.engine.dispose()
