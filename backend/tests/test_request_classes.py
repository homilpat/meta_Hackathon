"""Request classes and resume (implementation prompt §2, spec §22): supported, needs info, unsupported, human-only,
partial; "응" applies to the pending proposal only, a scope change invalidates it, cancel closes it, a repeated
answer runs nothing twice. The final DB state is re-read, not taken from the response."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import AgentStep, DocumentVersion
from tests.test_agent_ag2 import Scripted
from tests.test_agent_ag3 import run
from tests.v5_util import H, line_client


def steps(c, run_id=None) -> int:
    with Session(c.app_ref.state.engine) as s:
        q = select(func.count()).select_from(AgentStep)
        return s.scalar(q.where(AgentStep.run_id == run_id) if run_id else q)


def answer(c, out, confirm=True, text=None):
    return c.post(f"/agent/runs/{out['run_id']}/resume", headers=H("alice"),
                  json={"token": out["pending"]["token"], "confirm": confirm, "answer": text})


def test_unsupported_and_human_only_requests_touch_nothing_and_call_no_model(tmp_path):
    p = Scripted([])
    c = line_client(tmp_path, provider=p)
    mail = run(c, "고객에게 메일 보내줘").json()
    assert mail["status"] == "BLOCKED" and mail["request"]["class"] == "UNSUPPORTED"
    assert "메일" in mail["reply"][0]["text"] and "대안" in mail["reply"][0]["text"]
    approve = run(c, "NCR 승인해줘").json()
    assert approve["status"] == "BLOCKED" and approve["request"]["class"] == "HUMAN_ONLY"
    assert p.seen == [] and steps(c) == 0  # no planner call, no tool, no write
    with Session(c.app_ref.state.engine) as s:
        assert s.scalar(select(func.count()).select_from(DocumentVersion)) == 0


def test_a_partly_supported_request_shows_both_parts_and_runs_only_the_supported_one_after_yes(tmp_path):
    c = line_client(tmp_path)
    asked = run(c, "불량 조사하고 고객에게 메일 보내줘").json()
    assert asked["status"] == "NEEDS_HUMAN" and asked["pending"]["action"] == "confirm_partial"
    assert "불량 원인 조사" in asked["pending"]["question"] and "메일" in asked["pending"]["question"]
    assert steps(c, asked["run_id"]) == 0  # nothing runs before the answer
    done = answer(c, asked).json()
    assert done["status"] == "PARTIAL" and done["request"]["unsupported"] == ["메일·이메일 발송"]
    assert {s["kind"] for s in done["steps"]} == {"READ"}  # the investigation's reads, no write, no mail
    again = answer(c, asked)  # the same "응" again: the decision is already taken
    assert again.status_code == 409 and steps(c, asked["run_id"]) == len(done["steps"])


def test_a_generic_word_alone_does_not_start_an_investigation(tmp_path):
    c = line_client(tmp_path)
    out = run(c, "점심 메뉴 분석해줘").json()
    assert out["status"] == "NEEDS_HUMAN" and out["pending"]["action"] == "clarify" and steps(c) == 0
    assert out["request"]["class"] == "NEEDS_INFO"
    real = run(c, "L02 불량 분석해줘").json()  # with a quality word it is an investigation
    assert "INVESTIGATE" in real["intents"]


def test_a_scope_change_invalidates_the_earlier_confirmation_and_is_checked_again(tmp_path):
    c = line_client(tmp_path)
    asked = run(c, "L09 불량 원인 조사해 줘").json()  # this case has no L09
    assert asked["pending"]["action"] == "confirm_scope" and "L09" in asked["pending"]["question"]
    changed = answer(c, asked, text="아니 L03으로").json()
    assert "L09" not in changed["goal"] and "L03" in changed["goal"]
    assert any("범위 변경" in r["text"] and "무효" in r["text"] for r in changed["reply"])
    assert changed["status"] in ("COMPLETED", "NEEDS_HUMAN")
    assert not (changed["pending"] or {}).get("question", "").count("L09")


def test_cancel_closes_the_pending_work_and_says_nothing_ran(tmp_path):
    c = line_client(tmp_path)
    asked = run(c, "불량 조사하고 카톡으로 알려줘").json()
    out = answer(c, asked, confirm=False).json()
    assert out["status"] == "CANCELLED" and steps(c, asked["run_id"]) == 0
    assert all(i["status"] != "PENDING" for i in out["plan"])


def test_a_reviewer_asking_for_a_draft_is_told_why_before_the_route_refuses(tmp_path):
    c = line_client(tmp_path)
    out = run(c, "8D 초안 써 줘", user="bob").json()
    assert any(r.startswith("NO_PERMISSION") for r in out["request"]["reasons"])
    draft = next(s for s in out["steps"] if s["tool"] == "create_draft")
    assert draft["status"] == "DENIED"  # the server still checks; the label does not replace the check
