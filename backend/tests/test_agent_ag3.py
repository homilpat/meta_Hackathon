"""Agent-First AG3: allowlisted writes and human gates (spec §22.3, §22.4, §22.10; AG-T02/T05/T09/T10).

The agent may save and validate a draft through the existing routes. A review request needs the user's explicit
confirmation of a server-chosen reviewer; approval stays a human decision in the existing screens.
"""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import ApprovalEvent, DocumentVersion, Review
from app.main import create_app
from tests.test_agent_ag2 import Scripted, plan
from tests.v5_util import H, evidence, line_client, ok

GOAL = "이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘."


def run(c, goal: str = GOAL, user: str = "alice"):
    return c.post("/agent/runs", json={"case_id": "L", "goal": goal}, headers=H(user))


def resume(c, out: dict, user: str = "alice", **body):
    return c.post(f"/agent/runs/{out['run_id']}/resume", json={"token": out["pending"]["token"], "confirm": True, **body},
                  headers=H(user))


def count(c, model, *where) -> int:
    with Session(c.app_ref.state.engine) as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def queue(c, user: str, scope: str = "mine") -> list[tuple]:
    return [(i["kind"], i["version"], i["task"], i["owner"])
            for i in c.get(f"/queue?scope={scope}", headers=H(user)).json() if i["case_id"] == "L"]


def d0_d1(c) -> None:
    """D0 triage and D1 team the legitimate way (as tests/v5_util.ready_to_close does)."""
    spc = evidence(c, "L", "spi_measurements", panel_id="L02-P02", board_id="B2")
    ok(c.post("/cases/L/triage", headers=H("bob"), json={
        "signal_kind": "SPC_SIGNAL", "observed_defect": "SIGNAL_ONLY", "scope_lots": ["L02"],
        "route": "EMERGENCY_FULL_8D", "severity": "HIGH", "risk_flags": {"customer_impact": True},
        "rationale": "WE1 on L02 panel 2", "evidence_ids": spc}))
    for resp, user in (("LEAD", "alice"), ("QUALITY", "bob"), ("PRODUCTION", "erin"), ("PROCESS", "frank")):
        ok(c.post("/cases/L/team", headers=H("alice"), json={"event": "ASSIGN", "responsibility": resp, "user_id": user}))
        ok(c.post("/cases/L/team", headers=H(user), json={"event": "ACCEPT", "responsibility": resp}))


def test_a_draft_is_saved_and_validated_but_is_not_an_approval(tmp_path):
    c = line_client(tmp_path)
    out = run(c).json()
    assert out["status"] == "NEEDS_HUMAN" and out["pending"]["action"] == "request_review"
    writes = [(s["tool"], s["status"]) for s in out["steps"] if s["kind"] == "WRITE"]
    assert writes == [("create_draft", "OK"), ("validate_document", "OK")]
    assert [s["http_status"] for s in out["steps"] if s["kind"] == "WRITE"] == [201, 201]  # what the routes return
    draft = next(s for s in out["steps"] if s["tool"] == "create_draft")
    assert draft["result"]["status"] == "DRAFT" and draft["audit_event_ids"]  # DRAFT_CREATED is in the audit log
    assert [c["user_id"] for c in out["pending"]["candidates"]] == ["bob", "carol"]  # server-chosen, not the model's
    assert out["pending"]["validation"] in ("PASS", "WARN")
    # §22.10 (1): saved draft != approval; the existing queue shows the author's next step, nothing more
    assert count(c, Review) == 0 and count(c, ApprovalEvent) == 0
    assert queue(c, "alice") == [("ncr", 1, "SEND_FOR_REVIEW", "alice")]
    assert queue(c, "bob") == []


def test_confirmed_review_is_verified_and_handed_to_the_reviewers_own_queue(tmp_path):
    c = line_client(tmp_path)
    out = run(c).json()
    done = resume(c, out, reviewer_id="bob").json()
    assert done["status"] == "COMPLETED" and done["pending"] is None
    assert next(x for x in done["reply"] if "handoff" in x)["handoff"] == {"user_id": "bob", "role": "REVIEWER", "kind": "ncr", "version": 1}
    # §22.10 (2)(3)(4): DB, the reviewer's queue and the agent's own report agree
    doc = c.get("/cases/L/ncr/1", headers=H("alice")).json()
    assert doc["status"] == "IN_REVIEW" and doc["reviews"] == [{"reviewer_id": "bob", "state": "PENDING"}]
    assert queue(c, "bob") == [("ncr", 1, "REVIEW", "bob")]
    agent_q = next(s for s in reversed(done["steps"]) if s["tool"] == "queue")["result"]
    assert [(i["kind"], i["task"]) for i in agent_q["department"]] == [] and agent_q["mine"] == []
    # AG-T09 / §22.10 (6): the same answer again changes nothing
    assert resume(c, out, reviewer_id="bob").status_code == 409
    assert count(c, Review) == 1
    # AG-T02: the agent never approved anything
    assert count(c, ApprovalEvent) == 0


def test_the_same_goal_twice_reuses_the_draft(tmp_path):
    c = line_client(tmp_path)
    run(c)
    second = run(c).json()
    assert second["status"] == "NEEDS_HUMAN" and second["pending"]["version"] == 1
    assert [s["tool"] for s in second["steps"] if s["kind"] == "WRITE"] == ["validate_document"]
    assert count(c, DocumentVersion) == 1


def test_a_document_changed_after_the_question_is_not_sent(tmp_path):
    c = line_client(tmp_path)
    out = run(c).json()
    ok(c.post("/cases/L/ncr", json={}, headers=H("alice")))  # the author makes v2 in the documents screen
    stale = resume(c, out, reviewer_id="bob").json()  # AG-T05
    assert stale["status"] == "BLOCKED" and any("stale" in x["text"] for x in stale["reply"])
    assert count(c, Review) == 0
    assert c.get("/cases/L/ncr/2", headers=H("alice")).json()["status"] == "DRAFT"


def test_reviewer_must_be_a_server_candidate(tmp_path):
    c = line_client(tmp_path)
    out = run(c).json()
    for who in ("alice", "erin", None):
        r = resume(c, out, reviewer_id=who)
        assert r.status_code == 200 and r.json()["status"] == "BLOCKED"
        out = run(c).json()  # ask again for a fresh decision
    assert count(c, Review) == 0


def test_server_role_check_refuses_a_draft_for_a_reviewer(tmp_path):
    c = line_client(tmp_path)
    out = run(c, user="bob").json()
    draft = next(s for s in out["steps"] if s["tool"] == "create_draft")
    assert draft["status"] == "DENIED" and draft["http_status"] == 403 and "AUTHOR" in draft["error"]
    assert out["status"] == "BLOCKED" and count(c, DocumentVersion) == 0


def test_waits_for_the_human_decision_and_continues_only_after_the_server_shows_it(tmp_path):
    c = line_client(tmp_path)
    d0_d1(c)
    resume(c, run(c).json(), reviewer_id="bob")
    waiting = run(c).json()
    assert waiting["status"] == "NEEDS_HUMAN" and waiting["pending"]["action"] == "await"
    assert waiting["pending"]["owner"] == "bob"
    still = resume(c, waiting).json()  # nothing changed on the server: still waiting, nothing written
    assert still["status"] == "NEEDS_HUMAN" and still["pending"]["action"] == "await"
    assert count(c, DocumentVersion) == 1
    d = c.get("/cases/L/ncr/1", headers=H("bob")).json()
    ok(c.post("/cases/L/ncr/1/decision", headers=H("bob"),  # the human decision, in the existing route
              json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]}), 200)
    nxt = resume(c, still).json()
    assert nxt["status"] == "NEEDS_HUMAN" and nxt["pending"]["action"] == "request_review"
    assert nxt["pending"]["kind"] == "containment"
    assert [p["user_id"] for p in nxt["pending"]["candidates"]] == ["erin"]
    assert c.get("/cases/L/containment/1", headers=H("alice")).json()["status"] == "DRAFT"


def test_a_pending_decision_survives_a_server_restart(tmp_path):
    c = line_client(tmp_path)
    out = run(c).json()
    c2 = TestClient(create_app(f"sqlite:///{tmp_path / 'v5.db'}"))  # a new process on the same database
    again = c2.get(f"/agent/runs/{out['run_id']}", headers=H("alice")).json()
    assert again["status"] == "NEEDS_HUMAN" and again["pending"] == out["pending"]
    assert resume(c2, again, reviewer_id="bob").json()["status"] == "COMPLETED"
    assert c2.get("/cases/L/ncr/1", headers=H("alice")).json()["status"] == "IN_REVIEW"


def test_model_planner_can_prepare_but_never_send_or_approve(tmp_path):
    p = Scripted([plan(["DRAFT_DOC"], tools=["request_review"])])  # extra keys are ignored
    c = line_client(tmp_path, provider=p)
    out = run(c).json()
    assert "request_review" not in str(p.seen[0]["response_format"])  # the model cannot even name tools
    assert not any(s["tool"] == "request_review" for s in out["steps"])
    assert out["status"] == "NEEDS_HUMAN" and out["pending"]["action"] == "request_review"
    assert count(c, Review) == 0 and count(c, ApprovalEvent) == 0


def test_agent_draft_equals_the_manual_draft(tmp_path):
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    a, b = line_client(tmp_path / "a"), line_client(tmp_path / "b")  # same initial state, user and evidence
    run(a)
    manual = ok(b.post("/cases/L/ncr", json={}, headers=H("alice")))
    agent = a.get("/cases/L/ncr/1", headers=H("alice")).json()
    assert agent["content_sha256"] == manual["content_sha256"] and agent["claims"] == manual["claims"]  # AG-T10
    va = a.get("/cases/L/ncr/1/validation", headers=H("alice")).json()
    vb = ok(b.post("/cases/L/ncr/1/validate", headers=H("alice")))
    assert (va["result"], va["issues"]) == (vb["result"], vb["issues"])
