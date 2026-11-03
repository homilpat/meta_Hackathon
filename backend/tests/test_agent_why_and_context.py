"""A: every refused request is recorded by one handler, and the agent answers "왜 안 돼?" from the user's own records.
B: the planner sees the user's recent turns on the case, and "그거 뭐야?" explains the previous answer.
Server rule planner (no model) unless a scripted provider is given."""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import RequestError
from tests.v5_util import H, line_client, ok


def run(c, goal, user="alice"):
    return ok(c.post("/agent/runs", json={"case_id": "L", "goal": goal}, headers=H(user)))


def test_a_refused_request_is_recorded_and_the_agent_says_why(tmp_path):
    c = line_client(tmp_path)
    r = c.post("/cases/L/ncr/9/request-review", json={"reviewer_id": "bob"}, headers=H("alice"))
    assert r.status_code == 404
    assert c.post("/cases/L/ncr/9/request-review", json={"reviewer_id": "bob"}, headers=H("carol")).status_code in (403, 404)
    assert c.post("/limits/MAX_FILES_PER_UPLOAD", json={"value": "x"}, headers=H("alice")).status_code == 422
    with Session(c.app_ref.state.engine) as s:
        rows = s.scalars(select(RequestError).order_by(RequestError.id)).all()
    mine = [x for x in rows if x.user_id == "alice"]
    assert mine[0].route == "/cases/{case_id}/{kind:doc}/{version}/request-review" and mine[0].status == 404
    assert mine[0].case_id == "L" and "not found" in mine[0].detail.lower()
    assert any(x.route == "/limits/{name}" and "reason" in x.detail for x in mine)  # the validation list, kept

    out = run(c, "아까 검토 요청 왜 안 돼?")
    assert out["intents"] == ["WHY_FAILED"] and [s["tool"] for s in out["steps"]] == ["errors"]
    text = json.dumps(out["reply"], ensure_ascii=False)
    assert "검토 요청" in text and "not found" in text.lower()  # the action in words and the server's own reason
    assert "carol" not in json.dumps(out["steps"], ensure_ascii=False)  # only the asking user's own errors


def test_that_thing_is_explained_from_the_previous_answer(tmp_path):
    c = line_client(tmp_path)
    first = run(c, "진행 상태 알려줘")
    out = run(c, "그거 무슨 뜻이야?")
    assert out["intents"] == ["EXPLAIN"] and [s["tool"] for s in out["steps"]] == ["previous_answer"]
    prev = out["steps"][0]["result"]["previous"]
    assert prev["goal"] == "진행 상태 알려줘" and prev["answer"] == [x["text"][:200] for x in first["reply"][:3]]


class Planner:
    """Scripted planner: records the situation it was given and resolves 그거 from recent_turns."""
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self):
        self.situations = []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        body = json.loads(messages[-1]["content"])
        if "situation" not in body:  # the summary call of an investigation: not needed here
            return {"message": {"content": json.dumps({"lines": []})}, "usage": {}}
        self.situations.append(body["situation"])
        turns = body["situation"]["recent_turns"]
        intents = ["STATUS"] if body["goal"].startswith("그럼") and turns else ["STATUS"] if "상태" in body["goal"] else []
        return {"message": {"content": json.dumps({"intents": intents, "clarify": "" if intents else "무엇을요?"})},
                "usage": {}}


def test_the_model_planner_sees_the_recent_turns(tmp_path):
    p = Planner()
    c = line_client(tmp_path, provider=p)
    run(c, "진행 상태 알려줘")
    out = run(c, "그럼 다음은?")
    assert p.situations[0]["recent_turns"] == []
    assert p.situations[1]["recent_turns"][0]["goal"] == "진행 상태 알려줘"  # the earlier turn, for 그거/그럼
    assert out["intents"] == ["STATUS"]
