"""AI-CFG-04 (spec v5.14 §29): Meta proposes operating-limit changes from run statistics, the server checks each value
and replays it on the recorded runs, and only AGENT_ADMIN's approval changes the setting (the same path and
append-only history as POST /limits). TEST_DOUBLE only."""

import json

from sqlalchemy.orm import Session

from app import limits
from app.db import LimitSetting, ModelRun
from tests.v5_util import H, line_client


class Proposer:
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self, proposals):
        self.proposals, self.sent = proposals, []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.sent.append(messages[-1]["content"])
        return {"message": {"content": json.dumps({"proposals": self.proposals})}, "usage": {}}


def run(status, rounds, repairs, t0="2026-11-03T10:00:00+00:00", t1="2026-11-03T10:00:40+00:00"):
    return ModelRun(case_id="L", requested_by="alice", model="m", mode="LIVE", status=status, rounds=rounds,
                    prompt_tokens=20000, completion_tokens=1500, error=None, report_json=None, validation_errors=[],
                    attempts=[{}] * (repairs + 1), started_at=t0, finished_at=t1)


def seeded(tmp_path, proposals):
    p = Proposer(proposals)
    c = line_client(tmp_path, provider=p)
    with Session(c.app_ref.state.engine) as s:
        s.add_all([run("VALIDATED", 3, 0) for _ in range(6)] + [run("VALIDATION_FAILED", 4, 2) for _ in range(3)]
                  + [run("LIMIT_EXCEEDED", 5, 0) for _ in range(2)])
        s.commit()
    return c, p


def K(user="gina"):
    return {**H(user)}


def test_proposals_are_checked_and_replayed_and_only_an_admin_applies_one(tmp_path, monkeypatch):
    monkeypatch.setenv("QO_INVESTIGATION_MAX_REPAIRS", "2")  # the product default (the suite pins it to 0)
    c, p = seeded(tmp_path, [
        {"name": "INVESTIGATION_MAX_REPAIRS", "value": 3, "reason": "3 runs failed at the repair cap"},
        {"name": "INVESTIGATION_MAX_ROUNDS", "value": 2, "reason": "most runs use few rounds"},
        {"name": "INVESTIGATION_MAX_TOOL_CALLS", "value": -1, "reason": "x"},
        {"name": "INVESTIGATION_DEADLINE_S", "value": limits.get("INVESTIGATION_DEADLINE_S"), "reason": "same"},
        {"name": "MODEL_API_KEY", "value": 1, "reason": "not tunable"}])
    assert c.post("/limit-proposals", headers=H("alice")).status_code == 403
    r = c.post("/limit-proposals", headers=K())
    assert r.status_code == 201, r.text
    out = {x["name"]: x for x in r.json()}
    sent = json.loads(p.sent[0])
    assert sent["statistics"]["runs"] == 11 and sent["statistics"]["status"]["VALIDATION_FAILED"] == 3
    stopped = sent["statistics"]["stopped_by_cap"]  # only runs a cap ended, not every failure that used a lot
    assert stopped["INVESTIGATION_MAX_REPAIRS"] == 3 and stopped["INVESTIGATION_MAX_ROUNDS"] == 2
    assert '"L"' not in json.dumps(sent) and "case_id" not in json.dumps(sent)  # counts only, no case content

    rep = out["INVESTIGATION_MAX_REPAIRS"]
    assert rep["status"] == "PROPOSED" and rep["current"] == "2" and rep["proposed"] == "3"
    assert rep["comparison"]["stopped_at_current_cap"] == 3 and rep["comparison"]["would_cut"] == 0
    rounds = out["INVESTIGATION_MAX_ROUNDS"]
    assert rounds["comparison"]["would_cut"] == 11 and rounds["comparison"]["would_cut_validated"] == 6  # a warning
    assert out["INVESTIGATION_MAX_TOOL_CALLS"]["status"] == "INVALID"  # the limit's own rule refuses it
    assert out["INVESTIGATION_DEADLINE_S"]["status"] == "INVALID" and "같습니다" in out["INVESTIGATION_DEADLINE_S"]["issue"]
    assert "MODEL_API_KEY" not in out
    assert limits.get("INVESTIGATION_MAX_REPAIRS") == 2  # nothing changes before a person approves

    pid = rep["proposal_id"]
    body = {"decision": "APPROVED", "reason": "수리 상한에 걸린 실패 3건"}
    assert c.post(f"/limit-proposals/{pid}/decision", json=body, headers=H("alice")).status_code == 403
    d = c.post(f"/limit-proposals/{pid}/decision", json=body, headers=K())
    assert d.status_code == 201, d.text
    assert d.json()["status"] == "APPROVED" and limits.get("INVESTIGATION_MAX_REPAIRS") == 3
    with Session(c.app_ref.state.engine) as s:
        hist = s.query(LimitSetting).filter_by(name="INVESTIGATION_MAX_REPAIRS").all()
    assert hist[-1].value == "3" and f"제안 #{pid}" in hist[-1].reason and hist[-1].actor_id == "gina"
    assert c.post(f"/limit-proposals/{pid}/decision", json=body, headers=K()).status_code == 409  # once only

    rid = rounds["proposal_id"]
    c.post("/limits/INVESTIGATION_MAX_ROUNDS", json={"value": "6", "reason": "직접 변경"}, headers=K())
    r = c.post(f"/limit-proposals/{rid}/decision", json={"decision": "APPROVED", "reason": "x"}, headers=K())
    assert r.status_code == 409 and "현재값이 바뀌었습니다" in r.text  # proposed against a value no longer current
    assert c.post(f"/limit-proposals/{rid}/decision", json={"decision": "REJECTED", "reason": "근거 부족"},
                  headers=K()).json()["status"] == "REJECTED"
