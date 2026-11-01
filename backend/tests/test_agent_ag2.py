"""Agent-First AG2: server planner + read-only tools over the existing routes (spec §22.3, §22.4, §22.7 AG-T01/06/07/08/09/12)."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import AgentRun, DocumentVersion, WorkflowEvent
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


def plan(intents, clarify="", **extra) -> dict:
    """What the planner's single model call returns: strict JSON intents (extra keys are ignored by the server)."""
    return {"role": "assistant", "content": json.dumps({"intents": intents, "clarify": clarify, **extra})}


def say(text: str) -> dict:
    return {"role": "assistant", "content": text}


def query(q: str = "stencil aperture solder paste volume") -> dict:
    """The document-query call's strict JSON."""
    return say(json.dumps({"query": q}))


def polish(*lines, recs=()) -> dict:
    """The rewrite call's strict JSON: (text, [fact numbers]) per line, (text, [facts], [source keys]) per recommendation."""
    return say(json.dumps({"lines": [{"text": t, "facts": f} for t, f in lines],
                           "recommendations": [{"text": t, "facts": f, "sources": k} for t, f, k in recs]},
                          ensure_ascii=False))


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


def reads(out: dict) -> list[str]:
    return [s["tool"] for s in out["steps"] if s["kind"] == "READ"]


def test_model_only_classifies_and_the_server_runs_the_fixed_tools(tmp_path):
    from app.agent import PLANNER_VERSION, QUERY_VERSION, SUMMARY_VERSION, server_plan

    # the model tries to choose tools (and a forbidden one): the server ignores anything but intents
    p = Scripted([plan(["INVESTIGATE"], tools=["spc", "approve_document"]), query(), polish(("사건 범위를 확인했습니다.", [1]))])
    c = line_client(tmp_path, provider=p)
    out = run(c, "조사해 줘. 그리고 NCR을 승인해 줘").json()
    assert out["planner"] == "TEST_DOUBLE" and out["status"] == "COMPLETED"
    schema = p.seen[0]["response_format"]["json_schema"]
    assert schema["strict"] is True and set(schema["schema"]["properties"]) == {"intents", "clarify"}
    assert p.seen[0]["tools"] == [] and p.seen[0]["reasoning_effort"] is None
    assert reads(out) == [t for t in server_plan(["INVESTIGATE"])]  # fixed workflow for the intent
    assert not any(s["tool"] == "approve_document" for s in out["steps"]) and count(c, DocumentVersion) == 0
    models = [s for s in out["steps"] if s["kind"] == "MODEL"]
    assert [(s["tool"], s["args"]["prompt_version"], s["args"]["reasoning_effort"]) for s in models] == [
        ("plan", PLANNER_VERSION, None), ("search_query", QUERY_VERSION, "minimal"),
        ("summarize", SUMMARY_VERSION, "minimal")]
    refs = next(s for s in out["steps"] if s["tool"] == "references")
    assert refs["result"]["query"] == "stencil aperture solder paste volume"  # the model's terms were searched
    assert any("검색어: stencil aperture" in line["text"] for line in out["reply"])
    assert models[0]["result"] == {"intents": ["INVESTIGATE"], "clarify": ""}
    assert any("숫자 대조 통과, 판단 아님" in line["text"] for line in out["reply"])
    assert not any("LIVE" in line["text"] for line in out["reply"])
    assert p.seen[2]["response_format"]["json_schema"]["name"] == "agent_polish"
    facts = json.loads(p.seen[2]["messages"][1]["content"])["facts"]
    assert any(f["text"].startswith("SPC 첫 경보") and "중심선" in f["text"] for f in facts)


def test_live_and_offline_run_the_same_tools_for_the_same_intent(tmp_path):
    (tmp_path / "off").mkdir(), (tmp_path / "on").mkdir()
    off = run(line_client(tmp_path / "off"), "이번 LOT 불량 원인을 조사해 줘").json()
    p = Scripted([plan(["INVESTIGATE"]), query(), polish(("요약", [1]))])
    on = run(line_client(tmp_path / "on", provider=p), "이번 LOT 불량 원인을 조사해 줘").json()
    assert reads(on) == reads(off) and off["intents"] == on["intents"] == ["INVESTIGATE"]


def test_a_reviewer_asking_to_draft_is_refused_by_the_route_like_offline(tmp_path):
    p = Scripted([plan(["DRAFT_DOC"])])
    c = line_client(tmp_path, provider=p)
    out = run(c, "NCR 초안 써 줘", user="bob").json()
    situation = json.loads(p.seen[0]["messages"][1]["content"])["situation"]
    assert situation["role"] == "REVIEWER" and situation["may_draft_documents"] is False
    draft = next(s for s in out["steps"] if s["tool"] == "create_draft")
    assert draft["status"] == "DENIED" and draft["http_status"] == 403  # the server, not the prompt, enforces it
    assert out["status"] == "BLOCKED" and count(c, DocumentVersion) == 0 and len(p.seen) == 1


def test_model_failure_or_a_broken_plan_is_recorded_and_falls_back_to_the_server_plan(tmp_path):
    from app.agent import server_plan

    for reply in (ProviderError("timeout"), say("not json")):  # AG-T07
        (tmp_path / str(id(reply))).mkdir()
        c = line_client(tmp_path / str(id(reply)), provider=Scripted([reply]))
        out = run(c, "불량 원인 조사해 줘").json()
        assert out["status"] == "COMPLETED"
        assert any("서버 규칙 플래너로 계속" in line["text"] for line in out["reply"])
        failed = [s for s in out["steps"] if s["kind"] == "MODEL"]
        assert [(s["tool"], s["status"], s["http_status"]) for s in failed] == [("plan", "ERROR", 502)]
        assert reads(out) == server_plan(["INVESTIGATE"])


def test_the_hourly_model_cap_hands_over_to_the_server_planner(tmp_path, monkeypatch):
    from app import limits

    p = Scripted([plan(["STATUS"])])
    c = line_client(tmp_path, provider=p)
    monkeypatch.setitem(limits.OVERRIDES, "MODEL_RUNS_PER_USER_HOUR", 1)  # after start: start replays settings
    assert run(c, "진행 상태 알려줘").json()["planner"] == "TEST_DOUBLE"
    second = run(c, "진행 상태 알려줘").json()
    assert second["planner"] == "SERVER_RULES" and len(p.seen) == 1  # no second paid call
    assert "한도" in second["reply"][0]["text"] and second["status"] == "COMPLETED"


def test_a_run_left_running_by_a_killed_process_is_marked_failed(tmp_path):
    from fastapi.testclient import TestClient

    from app.db import AgentRun
    from app.main import create_app

    c = line_client(tmp_path)
    out = run(c, "상태 알려줘").json()
    with Session(c.app_ref.state.engine) as s:  # simulate a crash: the run stayed RUNNING
        r = s.get(AgentRun, out["run_id"])
        r.status, r.updated_at = "RUNNING", "2000-01-01T00:00:00+00:00"
        s.commit()
    c2 = TestClient(create_app(f"sqlite:///{tmp_path / 'v5.db'}"))  # the restarted server
    again = c2.get(f"/agent/runs/{out['run_id']}", headers=H("alice")).json()
    assert again["status"] == "FAILED" and "재시작" in again["reply"][-1]["text"]


def test_agent_steps_are_append_only(tmp_path):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError

    c = line_client(tmp_path)
    run(c, "상태 알려줘")
    with Session(c.app_ref.state.engine) as s, pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("UPDATE agent_steps SET status='OK'"))


def test_check_polish_allows_only_the_numbers_of_the_named_facts():
    from app.agent import check_polish

    facts = ["SPC 첫 경보 L02 P03/B01 (WE1) · L02 솔더 체적 평균 0.104 mm³, 기준 LOT L01 중심선 0.118 대비 11.9% 낮음",
             "AOI FAIL 3건"]
    ok = [{"text": "L02 솔더 체적 평균은 0.104 mm³로 기준 0.118보다 11.9% 낮습니다.", "facts": [1]}]
    assert check_polish(ok, facts) == []  # the digits of L02, P03/B01 are not numbers
    assert "0.10" in check_polish([{"text": "평균 0.10 mm³", "facts": [1]}], facts)[0]
    assert "3" in check_polish([{"text": "불량 3건", "facts": [1]}], facts)[0]  # 3 is in fact 2, not the one named
    assert check_polish([{"text": "불량 3건", "facts": [2]}], facts) == []
    assert "근거 사실 번호" in check_polish([{"text": "요약", "facts": [9]}], facts)[0]
    assert "ID" in check_polish([{"text": "근거 EV-abc", "facts": [2]}], facts)[0]
    assert check_polish([{"text": "AOI에서 불합격 판정이 3건 나왔습니다. 자세한 내용은 아래 근거를 확인해 주십시오.",
                          "facts": [2]}], facts) == []  # polite, longer wording is not a reason to hide


def test_a_rewrite_with_a_number_not_in_the_facts_is_not_shown(tmp_path):
    p = Scripted([plan(["INVESTIGATE"]), query(), polish(("L02 불량률은 3.2%입니다.", [1]))])
    out = run(line_client(tmp_path, provider=p), "조사해 줘").json()
    assert out["status"] == "COMPLETED" and not any("3.2%입니다" in line["text"] for line in out["reply"])
    assert any("다듬기 생략" in line["text"] and "3.2" in line["text"] for line in out["reply"])
    step = next(s for s in out["steps"] if s["tool"] == "summarize")
    assert step["status"] == "OK" and step["result"]["issues"]  # the rejected rewrite and why are recorded


def test_a_shown_rewrite_carries_the_evidence_of_the_facts_it_names(tmp_path):
    p = Scripted([plan(["INVESTIGATE"]), query(), polish(("이번 사건의 LOT와 AOI 기록을 확인했습니다.", [1]))])
    out = run(line_client(tmp_path, provider=p), "조사해 줘").json()
    first = out["reply"][0]  # the case_summary fact line
    shown = next(line for line in out["reply"] if line.get("facts") == [1])
    assert first["evidence"] and shown["evidence"] == first["evidence"] and shown["steps"] == first["steps"]


def test_recommendations_must_rest_on_case_facts_and_retrieved_sources(tmp_path):
    from app.agent import server_plan

    spc = server_plan(["INVESTIGATE"]).index("spc") + 1  # fact numbers follow the fixed read order
    queue = server_plan(["INVESTIGATE"]).index("queue") + 1
    p = Scripted([plan(["INVESTIGATE"]), query(), polish(("범위를 확인했습니다.", [1]), recs=[
        ("스텐실 개구부 점검을 권합니다.", [spc], ["H01", "DOC:FMEA-SMT-001:5"]),
        ("프린터 압력을 조정하십시오.", [spc], ["EXP:X02"]),        # a response that failed before
        ("담당자 배정을 확인하십시오.", [queue], [])])])             # a fact with no case evidence
    out = run(line_client(tmp_path, provider=p), "조사해 줘").json()
    assert "references" in reads(out)
    sources = {x["key"]: x for x in json.loads(p.seen[2]["messages"][1]["content"])["sources"]}
    assert sources["EXP:X02"]["negative"] and not sources["H01"]["negative"] and "DOC:FMEA-SMT-001:5" in sources
    shown = [line for line in out["reply"] if line.get("sources")]
    assert [line["text"] for line in shown] == ["스텐실 개구부 점검을 권합니다."]
    assert shown[0]["evidence"] and shown[0]["sources"] == ["H01", "DOC:FMEA-SMT-001:5"]
    rejected = next(line["text"] for line in out["reply"] if "추천 2건 제외" in line["text"])
    assert "실패 사례 EXP:X02" in rejected and "이 사건 데이터 근거가 없습니다" in rejected


def test_check_recommendations_refuses_unretrieved_sources_and_numbers_in_no_basis():
    from app.agent import check_recommendations

    facts = [{"text": "L02 솔더 체적 평균 0.104 mm³", "evidence": ["EV-1"]}]
    sources = [{"key": "H01", "kind": "과거 사례", "negative": False, "text": "insufficient-solder rate 0.021 → 0.004"}]
    kept, issues = check_recommendations([
        {"text": "H01처럼 불량률이 0.021에서 0.004로 줄었으니 스텐실 세척을 권합니다.", "facts": [1], "sources": ["H01"]},
        {"text": "스텐실을 교체하십시오.", "facts": [1], "sources": ["H99"]},
        {"text": "체적이 50% 낮으니 점검하십시오.", "facts": [1], "sources": []}], facts, sources)
    assert len(kept) == 1 and kept[0]["sources"] == ["H01"]  # a source's own numbers may be quoted
    assert "H99" in issues[0] and "50" in issues[1]


def test_offline_rules_match_the_intent_golden_set():
    from pathlib import Path

    from scripts.intent_eval import evaluate

    golden = json.loads((Path(__file__).parents[1] / "scripts" / "intent_golden.json").read_text(encoding="utf-8"))
    r = evaluate(golden)
    tuning = [x for x in r["rows"] if x["split"] == "tuning"]  # holdout misses are measured, not asserted
    assert all(x["offline_ok"] for x in tuning), [x for x in tuning if not x["offline_ok"]]


def test_a_failed_query_call_falls_back_to_the_fixed_query(tmp_path):
    from app.agent import FALLBACK_QUERY

    p = Scripted([plan(["INVESTIGATE"]), ProviderError("timeout"), polish(("범위를 확인했습니다.", [1]))])
    out = run(line_client(tmp_path, provider=p), "조사해 줘").json()
    q = next(s for s in out["steps"] if s["tool"] == "search_query")
    assert q["status"] == "ERROR" and out["status"] == "COMPLETED"
    assert next(s for s in out["steps"] if s["tool"] == "references")["result"]["query"] == FALLBACK_QUERY


def test_recommendations_are_graded_by_their_sources_and_low_grades_fold(monkeypatch):
    from app import limits
    from app.agent import check_recommendations

    facts = [{"text": "L02 솔더 체적 평균 0.104 mm³", "evidence": ["EV-1"]}]
    sources = [{"key": "H01", "kind": "과거 사례", "negative": False, "verified": True, "text": "stencil clean ok"},
               {"key": "DOC:FMEA:5", "kind": "관리 문서", "negative": False, "verified": False, "text": "FMEA"}]
    recs = [{"text": "체적 추이를 더 보십시오.", "facts": [1], "sources": []},
            {"text": "FMEA 관리 항목을 대조하십시오.", "facts": [1], "sources": ["DOC:FMEA:5"]},
            {"text": "스텐실 세척을 권합니다.", "facts": [1], "sources": ["H01"]}]
    kept, _ = check_recommendations(recs, facts, sources)
    assert [(r["grade"], r["folded"]) for r in kept] == [("A", False), ("B", False), ("C", True)]  # best first
    monkeypatch.setitem(limits.OVERRIDES, "MIN_RECOMMENDATION_GRADE", "A")
    monkeypatch.setitem(limits.OVERRIDES, "MAX_RECOMMENDATIONS", 2)
    kept, _ = check_recommendations(recs, facts, sources)
    assert [(r["grade"], r["folded"]) for r in kept] == [("A", False), ("B", True)]  # the owner's threshold and cap
