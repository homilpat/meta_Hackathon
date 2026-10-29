"""Phase A (G8 focused audit): Experience Memory counterexamples (MASTER TC-A-01 / TC-A-02).

KNOWN / ANALOGICAL / NO_RELEVANT_HISTORY, negative precedents and decision auditing are already covered in
test_v5_5_g8; these add the closed-case labelling and who revoked an entry.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ExperienceEntry
from app.synthetic import generate_line
from tests.test_v5_5_g8 import decide, retrieve
from tests.v5_util import CLOSE, TEAM, H, acknowledge_all, line_client, ok, ready_to_close


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def closed_then_next_case(c):
    ready_to_close(c)
    acknowledge_all(c)
    ok(c.post("/cases/L/closure", json=CLOSE, headers=H("bob")))
    c.post("/cases", json={"case_id": "M"}, headers=H("alice"))
    ok(c.post("/cases/M/sources", json=generate_line(7), headers=H("alice")))
    for u in TEAM:
        c.post("/cases/M/assignments", json={"user_id": u}, headers=H("alice"))
    ok(c.post("/cases/M/process-context", json={"site": "SITE-A"}, headers=H("alice")))
    return retrieve(c, case="M", q="insufficient deposit on boards after the stencil cleaning overrun")


def test_closed_case_is_an_effect_verified_reference_not_known(c):  # TC-A-01
    r = closed_then_next_case(c)
    mine = [m for m in r["matches"] if m["entry_key"].startswith("CASE:L:")]
    assert mine, "a newly closed case must be retrievable by the next case"
    for m in mine:
        assert m["recurrence"] == "NOT_YET_OBSERVED"  # never shown as NONE
        assert m["mode"] == "ANALOGICAL" and m["requires_revalidation"]  # never promoted to KNOWN
        if m["outcome"] == "VERIFIED_EFFECTIVE":
            assert m["evidence_level"] == "EFFECT_VERIFIED_REFERENCE"
            assert any("recurrence not yet observed" in w for w in m["warnings"]), m["warnings"]
    known = [m for m in r["matches"] if m["mode"] == "KNOWN"]
    assert all(m["recurrence"] == "NONE" and m["evidence_level"] == "VERIFIED_NO_RECURRENCE" for m in known)


def test_negative_precedent_cannot_be_chosen_as_success_and_choice_is_audited(c):  # TC-A-02
    r = retrieve(c)
    neg = r["negative_precedents"]
    assert neg and all(m["evidence_level"] == "NEGATIVE" and m["warnings"] for m in neg)
    assert not {m["entry_key"] for m in neg} & {m["entry_key"] for m in r["recommendations"]}
    key = neg[0]["entry_key"]
    assert decide(c, r["retrieval_id"], key, "REVIEW_PRIOR_RESPONSE").status_code == 422
    ok(decide(c, r["retrieval_id"], key, "CONSIDER_ALTERNATIVE"))
    assert c.get("/cases/L/actions", headers=H("alice")).json() == []  # nothing applied
    events = [e["event"] for e in c.get("/cases/L/timeline", headers=H("alice")).json()]
    assert "EXPERIENCE_CONSIDER_ALTERNATIVE" in events


def test_revocation_records_who_revoked_it(c):
    r = ok(c.post("/experience/entries/EXP:X01/revoke", json={"reason": "follow-up audit found a recurrence"},
                  headers=H("bob")))
    assert r["status"] == "REVOKED" and r["revoked_by"] == "bob"
    with Session(c.app_ref.state.engine) as s:  # the stored, hash-chained row names the actor too
        row = s.scalars(select(ExperienceEntry).where(ExperienceEntry.entry_key == "EXP:X01")
                        .order_by(ExperienceEntry.version.desc())).first()
    assert row.status == "REVOKED" and "by bob" in row.reason and "recurrence" in row.reason
    assert c.get("/audit/verify", headers=H("bob")).json()["ok"] is True
