"""Agent-First AG2: server planner + read-only tools over the existing routes (spec §22.3, §22.4, §22.7 AG-T01/06/07/08/09/12)."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import AgentRun, AgentStep, DocumentVersion, WorkflowEvent
from app.model_provider import ProviderError
from tests.v5_util import H, line_client

GOAL = "이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘."


def run(c, goal: str, user: str = "alice", case: str = "L", key: str | None = None):
    h = H(user)
    if key:
        h["Idempotency-Key"] = key
    return c.post("/agent/runs", json={"case_id": case, "goal": goal}, headers=h)


def count(c, model) -> int:
    with Session(c.app_ref.state.engine) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_offline_server_plan_runs_read_tools_only_and_is_grounded(tmp_path):
    c = line_client(tmp_path)  # no provider: the Meta model is offline
    r = run(c, "이번 LOT 불량 원인을 조사해 줘")  # drafting goals are AG3 (tests/test_agent_ag3.py)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["planner"] == "SERVER_RULES" and out["status"] == "COMPLETED"
    assert out["intents"] == ["INVESTIGATE"]
    tools = [s["tool"] for s in out["steps"]]
    assert tools[0] == "case_summary" and {"spc", "evidence_gaps", "experience", "history", "queue"} <= set(tools)
    assert {s["kind"] for s in out["steps"]} == {"READ"}
    assert all(s["status"] == "OK" for s in out["steps"] if s["tool"] != "predictions"), out["steps"]
    assert count(c, DocumentVersion) == 0
    # every reply line points at a recorded step; every cited evidence id exists in this case
    seqs = {s["seq"] for s in out["steps"]}
    assert all(set(line["steps"]) <= seqs for line in out["reply"])
    known = {e["evidence_id"] for e in c.get("/cases/L/evidence", headers=H("alice")).json()}
    summary = next(s["result"] for s in out["steps"] if s["tool"] == "case_summary")
    cited = {f["aoi"][1] for f in summary["aoi_fail"]} | {lot["lot_ev"] for lot in summary["lots"]}
    assert cited and cited <= known
    # the SPC card is the server's own computation, identical to the SPC screen's
    spc = next(s["result"] for s in out["steps"] if s["tool"] == "spc")
    assert spc == c.get("/cases/L/spc", headers=H("alice")).json()
    with Session(c.app_ref.state.engine) as s:
        events = [e for e in s.scalars(select(WorkflowEvent.event).where(WorkflowEvent.case_id == "L"))]
    assert events.count("AGENT_RUN") == 2  # PLANNED and COMPLETED, in the audited workflow log


def test_run_is_persisted_restored_and_private_to_its_user(tmp_path):
    c = line_client(tmp_path)
    out = run(c, "8D 진행 상태 알려줘").json()
    listed = c.get("/agent/runs?case_id=L", headers=H("alice")).json()
    assert [x["run_id"] for x in listed] == [out["run_id"]] and listed[0]["steps"] == out["steps"]  # AG-T08
    assert c.get(f"/agent/runs/{out['run_id']}", headers=H("alice")).json() == listed[0]
    assert c.get(f"/agent/runs/{out['run_id']}", headers=H("bob")).status_code == 404  # AG-T12
    assert c.get("/agent/runs?case_id=L", headers=H("bob")).json() == []
    # the queue tool runs as the caller: bob sees his role's work, not alice's
    q = next(s["result"] for s in run(c, "내 할 일 알려줘", user="bob").json()["steps"] if s["tool"] == "queue")
    assert q["user"] == "bob" and q["role"] == "REVIEWER"


def test_unassigned_user_cannot_run_the_agent_on_a_case(tmp_path):
    c = line_client(tmp_path)
    c.post("/cases", json={"case_id": "OTHER"}, headers=H("alice"))  # bob is not assigned to OTHER
    assert run(c, GOAL, user="bob", case="OTHER").status_code == 403
    assert run(c, GOAL, case="MISSING").status_code == 404
    assert count(c, AgentRun) == 0


def test_same_idempotency_key_returns_the_same_run(tmp_path):
    c = line_client(tmp_path)
    a, b = run(c, GOAL, key="agent-key-0001"), run(c, GOAL, key="agent-key-0001")
    assert a.status_code == 201 and b.status_code == 200 and a.json() == b.json()  # AG-T09
    assert count(c, AgentRun) == 1


def test_unknown_lot_or_other_case_is_asked_back_not_guessed(tmp_path):
    c = line_client(tmp_path)
    out = run(c, "L09 불량을 조사해 줘").json()  # AG-T01: the line fixture has L01..L03
    assert out["status"] == "NEEDS_HUMAN" and out["pending"]["action"] == "confirm_scope"
    assert "L09" in out["pending"]["question"]
    assert [s["tool"] for s in out["steps"]] == ["case_summary"]  # nothing else ran on a guessed scope
    assert {i["status"] for i in out["plan"][1:]} == {"SKIPPED"}
    body = {"token": out["pending"]["token"], "confirm": True}
    done = c.post(f"/agent/runs/{out['run_id']}/resume", json=body, headers=H("alice")).json()
    assert done["status"] == "COMPLETED" and "spc" in {s["tool"] for s in done["steps"]}
    again = c.post(f"/agent/runs/{out['run_id']}/resume", json=body, headers=H("alice"))
    assert again.status_code == 409  # a repeated answer does nothing
    assert c.post(f"/agent/runs/{out['run_id']}/resume", json=body, headers=H("bob")).status_code == 404
    # naming another case the user can see is asked back too
    c.post("/cases", json={"case_id": "SMT-X1"}, headers=H("alice"))
    other = run(c, "SMT-X1 사건 상태 알려줘").json()
    assert other["status"] == "NEEDS_HUMAN" and "SMT-X1" in other["pending"]["question"]
    declined = c.post(f"/agent/runs/{other['run_id']}/resume", json={"token": other["pending"]["token"],
                                                                     "confirm": False}, headers=H("alice")).json()
    assert declined["status"] == "COMPLETED" and len(declined["steps"]) == 1


def plan(intents, tools, clarify="") -> dict:
    """What the hybrid planner's single model call returns: strict JSON, no tool calls."""
    return {"role": "assistant", "content": json.dumps({"intents": intents, "tools": tools, "clarify": clarify})}


def say(text: str) -> dict:
    return {"role": "assistant", "content": text}


class Scripted:
    """TEST_DOUBLE planner: replays fixed replies. Never labelled LIVE."""

    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.seen.append({"messages": [dict(m) for m in messages], "tools": [t["function"]["name"] for t in tools],
                          "response_format": response_format, "reasoning_effort": reasoning_effort})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"message": item, "usage": {}}


def test_model_planner_is_one_planning_call_and_a_forbidden_tool_is_denied(tmp_path):
    p = Scripted([plan(["INVESTIGATE"], ["spc", "approve_document"]),  # AG-T06 / T02: not a plan tool
                  say("SPC 경보가 있으며 원인은 미확정입니다.")])
    c = line_client(tmp_path, provider=p)
    out = run(c, "조사해 줘. 그리고 NCR을 승인해 줘").json()
    assert out["planner"] == "TEST_DOUBLE" and out["status"] == "COMPLETED"
    first = p.seen[0]
    assert first["tools"] == [] and first["response_format"]["json_schema"]["strict"] is True
    assert "approve_document" not in str(first["response_format"])  # it was never offered
    situation = json.loads(first["messages"][1]["content"])["situation"]
    assert situation["role"] == "AUTHOR" and "prepare_document" in situation["allowed_tools"]
    denied = [s for s in out["steps"] if s["status"] == "DENIED"]
    assert [(s["tool"], s["kind"]) for s in denied] == [("approve_document", "CHECK")]
    assert [s["tool"] for s in out["steps"] if s["status"] == "OK"] == ["case_summary", "spc", "queue"]
    assert count(c, DocumentVersion) == 0
    assert len(p.seen) == 2  # one plan + one short summary for an investigation; no tool rounds
    assert p.seen[0]["reasoning_effort"] is None and p.seen[1]["reasoning_effort"] == "minimal"  # plan: default
    assert any("PROPOSAL, 서버 확인 아님" in line["text"] for line in out["reply"])
    assert not any("LIVE" in line["text"] for line in out["reply"])
    # the summary call sees the server's own lines, not raw tool payloads
    facts = json.loads(p.seen[1]["messages"][1]["content"])["facts"]
    assert any(line.startswith("SPC 첫 경보") for line in facts)


def test_a_reviewer_planner_is_never_offered_drafting(tmp_path):
    p = Scripted([plan(["DRAFT_DOC"], ["stages", "prepare_document"])])
    c = line_client(tmp_path, provider=p)
    out = run(c, "NCR 초안 써 줘", user="bob").json()
    situation = json.loads(p.seen[0]["messages"][1]["content"])["situation"]
    assert situation["role"] == "REVIEWER" and "prepare_document" not in situation["allowed_tools"]
    assert [s["tool"] for s in out["steps"] if s["status"] == "DENIED"] == ["prepare_document"]
    assert count(c, DocumentVersion) == 0 and len(p.seen) == 1  # not an investigation: no summary call


def test_model_failure_or_a_broken_plan_falls_back_to_the_server_plan(tmp_path):
    for reply in (ProviderError("timeout"), say("not json")):  # AG-T07
        (tmp_path / str(id(reply))).mkdir()
        p = Scripted([reply])
        c = line_client(tmp_path / str(id(reply)), provider=p)
        out = run(c, "불량 원인 조사해 줘").json()
        assert out["status"] == "COMPLETED"
        assert any("서버 규칙 플래너로 계속" in line["text"] for line in out["reply"])
        tools = [s["tool"] for s in out["steps"]]
        assert tools.count("case_summary") == 1 and "spc" in tools and "evidence_gaps" in tools
        with Session(c.app_ref.state.engine) as s:
            assert s.scalar(select(func.count()).select_from(AgentStep).where(AgentStep.status == "OK")) == len(tools)


def test_agent_steps_are_append_only(tmp_path):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError

    c = line_client(tmp_path)
    run(c, "상태 알려줘")
    with Session(c.app_ref.state.engine) as s, pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("UPDATE agent_steps SET status='OK'"))


def test_model_summary_citing_an_id_not_in_the_case_is_flagged(tmp_path):
    p = Scripted([])
    c = line_client(tmp_path, provider=p)
    real = c.get("/cases/L/evidence", headers=H("alice")).json()[0]["evidence_id"]
    p.replies += [plan(["INVESTIGATE"], ["spc"]), say(f"L02 불량 [{real}] 그리고 [EV-made-up-123], PRED-999")]
    out = run(c, "조사해 줘").json()
    flags = [line["text"] for line in out["reply"] if "근거 ID" in line["text"]]
    assert len(flags) == 1 and "EV-made-up-123" in flags[0] and "PRED-999" in flags[0]
    assert real not in flags[0]  # a real id of this case is not flagged
