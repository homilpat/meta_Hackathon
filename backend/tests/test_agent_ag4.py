"""Agent-First AG4: documents, G9 human editing, approvals and G10 exports end to end (spec §22.5, §22.7 AG4, AG-T11).

`agent_scenario` takes any client with the TestClient interface, so scripts/e2e_http.py runs it over real HTTP too.
"""

from tests.test_agent_ag3 import GOAL, d0_d1
from tests.v5_util import H, line_client, ok


def agent(c, goal: str, user: str = "alice") -> dict:
    return ok(c.post("/agent/runs", json={"case_id": "L", "goal": goal}, headers=H(user)))


def answer(c, out: dict, **body) -> dict:
    return ok(c.post(f"/agent/runs/{out['run_id']}/resume", json={"token": out["pending"]["token"], "confirm": True,
                                                                    **body}, headers=H("alice")), 200)


def decide(c, kind: str, version: int, user: str) -> None:
    d = ok(c.get(f"/cases/L/{kind}/{version}", headers=H(user)), 200)
    ok(c.post(f"/cases/L/{kind}/{version}/decision", headers=H(user),
              json={"decision": "APPROVE", "comment": "checked", "content_sha256": d["content_sha256"]}), 200)


def step(out: dict, tool: str) -> dict:
    return next(s for s in reversed(out["steps"]) if s["tool"] == tool)


def agent_scenario(c) -> dict:
    """D0/D1 → agent drafts NCR → human edits it (G9) → agent validates the edited version and, after the user's
    confirmation, sends it → reviewer approves in the existing route → agent offers only the approved export."""
    d0_d1(c)
    first = agent(c, GOAL)
    assert first["pending"]["action"] == "request_review" and first["pending"]["version"] == 1
    v1 = ok(c.get("/cases/L/ncr/1", headers=H("alice")), 200)
    edit = ok(c.post("/cases/L/ncr/1/edits", headers=H("alice"), json={  # G9 human edit before sending
        "expected_sha256": v1["content_sha256"], "reason": "add open question",
        "add": [{"classification": "UNKNOWN", "text": "스텐실 개구부 직접 관찰 결과 대기", "value": None, "unit": None,
                 "evidence_ids": []}]}), 201)
    assert edit["version"] == 2
    second = agent(c, GOAL)  # the agent works on the edited version, not the stale v1
    assert second["pending"]["version"] == 2 and step(second, "validate_document")["args"]["version"] == 2
    stale = c.post(f"/agent/runs/{first['run_id']}/resume", headers=H("alice"),
                   json={"token": first["pending"]["token"], "confirm": True, "reviewer_id": "bob"}).json()
    assert stale["status"] == "BLOCKED"  # the old question about v1 cannot send anything
    sent = answer(c, second, reviewer_id="bob")
    assert sent["status"] == "COMPLETED" and next(x for x in sent["reply"] if "handoff" in x)["handoff"]["user_id"] == "bob"
    decide(c, "ncr", 2, "bob")  # approval stays a human decision (G9 needs the agent's fresh validation: it has one)
    out = agent(c, "NCR 승인본 PDF로 내보내 줘")
    exports = step(out, "exports")["result"]
    assert exports["documents"] == [{"kind": "ncr", "doc_type": "NCR", "version": 2,
                                     "path": "/cases/L/documents/ncr/export?version=2"}]
    assert exports["report"] is None  # the case is not CLOSED
    assert not any(s["tool"].startswith("export") and s["kind"] == "WRITE" for s in out["steps"])  # links only
    pdf = c.get(exports["documents"][0]["path"] + "&format=pdf", headers=H("alice"))
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # AG-T11: a DRAFT is never exported as approved, and the agent did not offer it
    nxt = agent(c, GOAL)
    assert nxt["pending"]["kind"] == "containment"
    assert c.get("/cases/L/documents/containment/export?format=pdf", headers=H("alice")).status_code == 409
    return {"ncr_version": 2, "containment_pending": nxt["pending"]["version"]}


def test_agent_scenario_in_process(tmp_path):
    c = line_client(tmp_path)
    assert agent_scenario(c) == {"ncr_version": 2, "containment_pending": 1}
    events = [e["event"] for e in c.get("/cases/L/timeline", headers=H("alice")).json()]
    assert {"DRAFT_CREATED", "VALIDATED", "REVIEW_REQUESTED", "APPROVE", "EXPORTED", "AGENT_RUN"} <= set(events)
    assert events.count("APPROVE") == 1  # bob's, in the existing route


def test_status_reports_d5_d8_closure_state_read_only(tmp_path):
    c = line_client(tmp_path)
    out = agent(c, "8D 진행 상태와 종료 가능 여부 알려줘")
    st = step(out, "stages")["result"]
    assert st["closure"]["ready"] is False and st["closure"]["blocks"]  # server's own reasons, not the model's
    assert {s["kind"] for s in out["steps"]} == {"READ"}


def test_only_an_explicit_ask_plans_a_write():
    from app.agent import intents_of, server_plan

    for goal in ("8D 진행 상태 알려줘", "NCR 승인본 PDF로 내보내 줘", "내 할 일 알려줘", "이번 불량 원인 조사해 줘"):
        assert "prepare_document" not in server_plan(intents_of(goal)), goal
    for goal in ("이번 LOT 불량을 조사하고 8D 보고서 초안을 준비해 줘.", "NCR 써 줘", "draft the NCR"):
        assert "prepare_document" in server_plan(intents_of(goal)), goal
