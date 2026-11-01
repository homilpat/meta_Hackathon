import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from tests.test_s6_followups import H, approve, create, env, review, revise  # noqa: F401 - env: seeded case fixture


def get(c, path, user="alice"):
    return c.get(path, headers={"X-User": user}).json()


def comment(c, user, body, version=1, kind="ncr", **kw):
    return c.post(f"/cases/C1/{kind}/{version}/comments", headers=H(user), json={"body": body, **kw})


def tasks(c, user, scope="department"):
    return [(i["task"], i["doc_type"], i["owner"]) for i in get(c, f"/queue?scope={scope}", user)
            if i["kind"] != "triage"]  # document tasks; D0 tasks are checked in test_intake_in3


def test_claim_comments_reach_the_author_queue_and_are_append_only(env):  # noqa: F811
    c = env
    create(c, "ncr")
    review(c, "ncr", 1)
    assert tasks(c, "bob") == [("REVIEW", "NCR", "bob")]
    assert tasks(c, "carol") == []  # not assigned to C1
    first = comment(c, "bob", "Which pins were re-measured?", claim_id="C2")
    assert first.status_code == 201 and first.json()["open"]
    assert comment(c, "bob", "x", claim_id="C999").status_code == 422
    assert comment(c, "carol", "x").status_code == 403
    assert ("ANSWER_COMMENT", "NCR", "alice") in tasks(c, "alice", "mine")
    cid = first.json()["comment_id"]
    assert comment(c, "alice", "Both pins of row 1.", reply_to=cid).status_code == 201
    assert c.post(f"/cases/C1/ncr/1/comments/{cid}/resolve", headers=H("erin"), json={"body": "ok"}).status_code == 403
    done = c.post(f"/cases/C1/ncr/1/comments/{cid}/resolve", headers=H("alice"), json={"body": "answered"})
    assert done.status_code == 201 and not any(x["open"] for x in done.json()["comments"])
    assert c.post(f"/cases/C1/ncr/1/comments/{cid}/resolve", headers=H("bob"), json={"body": "x"}).status_code == 409
    assert "ANSWER_COMMENT" not in [t for t, _, _ in tasks(c, "alice")]
    with Session(c.app_ref.state.engine) as s:
        for stmt in ("UPDATE doc_comments SET body='x'", "DELETE FROM doc_comments"):
            with pytest.raises(DatabaseError, match="append-only"):
                s.execute(text(stmt))
            s.rollback()


def test_department_queue_and_responsibility_trail(env):  # noqa: F811
    c = env
    for kind in ("ncr", "containment", "rca"):
        create(c, kind)
    assert ("WAITING_UPSTREAM", "CONTAINMENT", "alice") in tasks(c, "alice")
    approve(c, "ncr", 1)
    approve(c, "containment", 1)
    revise(c)  # reopens NCR + RCA, flags the containment plan
    assert tasks(c, "erin") == [("BASIS_CHECK", "CONTAINMENT", "erin")]  # the approver who signed it owns it
    assert {("REDRAFT", "NCR", "alice"), ("REDRAFT", "RCA", "alice")} <= set(tasks(c, "alice"))
    assert tasks(c, "dave", "mine") == [] and tasks(c, "dave") == []  # dave is not assigned
    trail = get(c, "/cases/C1/containment/1")["trail"]
    assert [(t["event"], t["actor_id"], t["role"]) for t in trail] == [
        ("DRAFT_CREATED", "alice", "AUTHOR"), ("REVIEW_REQUESTED", "alice", "AUTHOR"),
        ("APPROVE", "erin", "QA_PRODUCTION"), ("BASIS_CHANGED", "alice", "AUTHOR")]


def test_concurrent_decisions_on_one_review_accept_exactly_one(env):  # noqa: F811
    c = env
    create(c, "ncr")
    sha = review(c, "ncr", 1).json()["content_sha256"]
    gate = threading.Barrier(3)

    def decide(decision):
        gate.wait()
        return c.post("/cases/C1/ncr/1/decision", headers=H("bob"),
                      json={"decision": decision, "content_sha256": sha}).status_code

    with ThreadPoolExecutor(3) as pool:
        codes = list(pool.map(decide, ("APPROVE", "REJECT", "REQUEST_INFO")))
    assert codes.count(200) == 1, codes
    assert len(get(c, "/cases/C1/ncr/1")["decisions"]) == 1
