"""Experience Memory with the AI (user decision 2026-11-03): the AI reads only the entries that match the case's
conditions but share no word with it and picks by server id; its comparison is checked against the server's own
conditions, and the mode stays the server's. TEST_DOUBLE only."""

import json

from sqlalchemy.orm import Session

from app import experience
from app.model_provider import ProviderError
from scripts.experience_eval import CASES, COMMON, GOOD
from tests.v5_util import H, line_client


class Scripted:
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self, pick, review=None, fail=False):
        self.pick, self.review, self.fail, self.sent = pick, review, fail, []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        body = json.loads(messages[-1]["content"])
        self.sent.append(body)
        if self.fail:
            raise ProviderError("timeout")
        if "conditions" not in body["earlier"][0]:
            return {"message": {"content": json.dumps({"same_problem": [
                {"entry_key": k, "reason": "same"} for k in self.pick]})}, "usage": {}}
        return {"message": {"content": json.dumps({"cases": self.review(body["earlier"])})}, "usage": {}}


def seeded(tmp_path, provider, cases=CASES, a1=False):
    c = line_client(tmp_path, provider=provider)
    with Session(c.app_ref.state.engine) as s:
        experience.ensure_entries(s)
        for key, sym, cause, act, over, _ in cases:
            experience._add(s, key, "EVAL", key, **{**COMMON, **GOOD, "symptom_text": sym, "cause_text": cause,
                                                    "action_code": "EVAL", "action_text": act,
                                                    "recurrence_note": "", **over})
        if a1:
            experience._add(s, "EVAL:A1", "EVAL", "EVAL:A1", **{  # similar, but its condition does not hold now
                **COMMON, **GOOD, "symptom_text": "땜이 덜 묻어나옴", "cause_text": "스퀴지 날 닳음",
                "action_code": "EVAL", "action_text": "스퀴지 교체", "recurrence_note": "",
                "applicability": [{"key": "equipment_condition", "expected": "SQUEEGEE_WEAR"}]})
        s.commit()
    return c


def review_all_known(earlier):  # claims every condition holds and every case is KNOWN, plus a made-up case
    return [{"entry_key": e["entry_key"], "same": [c["check"] for c in e["conditions"]], "different": [],
             "proposed_mode": "KNOWN", "note": "same"} for e in earlier] + \
        [{"entry_key": "EVAL:NOPE", "same": [], "different": [], "proposed_mode": "KNOWN", "note": "x"}]


def test_the_ai_picks_among_word_misses_and_the_server_keeps_the_mode(tmp_path):
    p = Scripted(["EVAL:K1", "EVAL:K2", "EVAL:K4", "EVAL:N1", "EVAL:D1", "EXP:X99"], review_all_known)
    c = seeded(tmp_path, p)
    r = c.post("/cases/L/experience/retrievals", json={"ai": True}, headers=H("alice"))
    assert r.status_code == 201, r.text
    out = r.json()
    read = set(out["ai"]["read"])
    assert {"EVAL:K1", "EVAL:K2", "EVAL:K4", "EVAL:N1"} <= read and "EVAL:D1" not in read  # factor gate first
    assert "EVAL:K5" not in read  # rules found it: the AI is not asked about it
    assert out["ai"]["picked"] == ["EVAL:K1", "EVAL:K2", "EVAL:K4", "EVAL:N1"]  # D1 and a made-up id dropped
    by = {m["entry_key"]: m for m in out["matches"]}
    assert {k for k, m in by.items() if m["found_by"] == "AI_MATCH"} == {"EVAL:K1", "EVAL:K2", "EVAL:K4", "EVAL:N1"}
    assert by["EVAL:K5"]["found_by"] == "RULES" and "EVAL:D1" not in by
    n1 = by["EVAL:N1"]
    assert n1["role"] == "NEGATIVE_PRECEDENT" and n1["mode"] == "ANALOGICAL"  # the AI said KNOWN; records decide
    assert any("ANALOGICAL" in d for d in n1["ai_review"]["disagreements"])
    assert out["ai"]["review"]["dropped"] == 1  # the made-up case id
    assert "EVAL:K5" not in json.dumps(p.sent[0])  # the first call sees only the entries the words missed


def test_a_model_failure_leaves_the_rule_result(tmp_path):
    c = seeded(tmp_path, Scripted([], fail=True))
    out = c.post("/cases/L/experience/retrievals", json={"ai": True}, headers=H("alice")).json()
    assert out["ai"]["status"] == "FAILED" and "EVAL:K1" not in {m["entry_key"] for m in out["matches"]}
    assert out["mode"] == c.post("/cases/L/experience/retrievals", json={}, headers=H("alice")).json()["mode"]


def test_a_condition_the_ai_calls_the_same_is_checked_against_the_record(tmp_path):
    c = seeded(tmp_path, Scripted(["EVAL:A1"], review_all_known), cases=[], a1=True)
    out = c.post("/cases/L/experience/retrievals", json={"ai": True}, headers=H("alice")).json()
    a1 = next(m for m in out["matches"] if m["entry_key"] == "EVAL:A1")
    assert a1["found_by"] == "AI_MATCH" and a1["mode"] == "ANALOGICAL"
    assert any("equipment_condition: AI 같음, 기록 FAIL" in d for d in a1["ai_review"]["disagreements"])
