"""Hybrid planner follow-ups: asking back, the 8D-report note, "fill it?" for D0, and the simple NCR route closing
early with its own report (spec §22.3, §22.4; D0-D8 policy routes)."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import DocumentVersion, TriageAssessment
from tests.test_agent_ag2 import Scripted, plan
from tests.test_g10_export import opened, squash
from tests.v5_util import H, acknowledge_all, act, approve_doc, evidence, line_client, ok


def run(c, goal: str, user: str = "alice") -> dict:
    return ok(c.post("/agent/runs", json={"case_id": "L", "goal": goal}, headers=H(user)))


def answer(c, out: dict, user: str = "alice", **body):
    return c.post(f"/agent/runs/{out['run_id']}/resume", json={"token": out["pending"]["token"], "confirm": True, **body},
                  headers=H(user))


def count(c, model) -> int:
    with Session(c.app_ref.state.engine) as s:
        return s.scalar(select(func.count()).select_from(model))


def test_a_vague_goal_is_asked_back_and_the_answer_is_planned(tmp_path):
    c = line_client(tmp_path)
    out = run(c, "이거 좀 처리해 줘")
    assert out["status"] == "NEEDS_HUMAN" and out["pending"]["action"] == "clarify" and out["steps"] == []
    done = ok(answer(c, out, answer="불량 원인 조사"), 200)
    assert done["status"] == "COMPLETED" and "spc" in [s["tool"] for s in done["steps"]]
    assert done["goal"] == "이거 좀 처리해 줘 / 불량 원인 조사" and count(c, DocumentVersion) == 0
    assert answer(c, out, answer="again").status_code == 409  # the question was already answered


def test_asking_for_the_8d_report_explains_when_it_exists(tmp_path):
    c = line_client(tmp_path)
    out = run(c, "8D 리포트 보여줘")
    assert out["reply"][0]["text"].startswith("최종 8D 리포트는 D8 종료가 승인될 때")
    assert {"stages", "exports"} <= {s["tool"] for s in out["steps"]} and count(c, DocumentVersion) == 0


def test_model_planner_asks_back_through_its_clarify_field(tmp_path):
    p = Scripted([plan([], [], "어떤 LOT의 어떤 문제를 볼까요?"), plan(["STATUS"], ["stages"])])
    c = line_client(tmp_path, provider=p)
    out = run(c, "도와줘")
    assert out["pending"]["action"] == "clarify" and out["pending"]["question"] == "어떤 LOT의 어떤 문제를 볼까요?"
    done = ok(answer(c, out, answer="L02 진행 상태"), 200)
    assert done["status"] == "COMPLETED" and "stages" in [s["tool"] for s in done["steps"]]
    assert json.loads(p.seen[1]["messages"][1]["content"])["goal"] == "도와줘 / L02 진행 상태"


def test_d0_is_offered_first_and_filled_only_after_yes_and_only_a_person_submits(tmp_path):
    c = line_client(tmp_path)
    offer = run(c, "이번 SPC 경보, 8D로 가야 할지 판정해 줘")
    assert offer["status"] == "NEEDS_HUMAN" and offer["pending"]["action"] == "offer_fill"
    assert "채워 드릴까요" in offer["pending"]["question"]
    no = ok(c.post(f"/agent/runs/{offer['run_id']}/resume", json={"token": offer["pending"]["token"],
                                                                  "confirm": False}, headers=H("alice")), 200)
    assert no["status"] == "COMPLETED" and not any(s["tool"] == "fill_triage" for s in no["steps"])
    offer = run(c, "8D로 가야 할지 판정해 줘")
    filled = ok(answer(c, offer), 200)
    step = next(s for s in filled["steps"] if s["tool"] == "fill_triage")
    assert step["kind"] == "PROPOSE" and step["status"] == "OK"
    form = step["result"]
    assert form["fields"]["route"] in ("NCR_ONLY", "FULL_8D", "EMERGENCY_FULL_8D") and form["fields"]["evidence_ids"]
    assert form["submit"] == {"path": "/cases/L/triage", "role": "REVIEWER", "can_submit": False}  # alice
    assert count(c, TriageAssessment) == 0  # filling stored nothing
    # the filled form passes the server's own D0 rules when the right person submits it unchanged
    t = ok(c.post("/cases/L/triage", json=form["fields"], headers=H("bob")))
    assert t["route"] == form["fields"]["route"] and count(c, TriageAssessment) == 1
    again = run(c, "8D로 가야 할지 판정해 줘")  # already decided: no second offer
    assert again["status"] == "COMPLETED" and "이미 기록" in " ".join(line["text"] for line in again["reply"])


def test_simple_ncr_route_closes_after_d3_with_its_own_report(tmp_path):
    c = line_client(tmp_path)
    spc = evidence(c, "L", "spi_measurements", panel_id="L02-P02", board_id="B2")
    ok(c.post("/cases/L/triage", headers=H("bob"), json={  # a signal only, no shipped exposure: simple route
        "signal_kind": "SPC_SIGNAL", "observed_defect": "SIGNAL_ONLY", "scope_lots": ["L03"], "route": "NCR_ONLY",
        "severity": "LOW", "risk_flags": {}, "rationale": "statistical signal, no defect, L03 not shipped",
        "evidence_ids": spc}))
    for resp, user in (("LEAD", "alice"), ("QUALITY", "bob"), ("PRODUCTION", "erin"), ("PROCESS", "frank")):
        ok(c.post("/cases/L/team", headers=H("alice"), json={"event": "ASSIGN", "responsibility": resp, "user_id": user}))
        ok(c.post("/cases/L/team", headers=H(user), json={"event": "ACCEPT", "responsibility": resp}))
    approve_doc(c, "L", "ncr", "bob")
    approve_doc(c, "L", "containment", "erin")
    d3 = ok(c.post("/cases/L/actions", headers=H("alice"), json={
        "action_type": "HOLD", "description": "Hold unshipped panel L02-P09 at SMT-1 exit", "targets": ["L02-P09"]}))
    act(c, "L", d3["action_id"], "erin", "PLAN_APPROVED")
    act(c, "L", d3["action_id"], "erin", "EXECUTED", "panels held at SMT-1 exit (simulated)")
    act(c, "L", d3["action_id"], "bob", "INDEPENDENTLY_VERIFIED", "hold tag checked", ["REF:HOLD-TAG-1"])
    # the agent knows the simple route: nothing more to draft, no RCA
    out = run(c, "NCR 초안 써 줘")
    note = next(s for s in out["plan"] if s["tool"] == "prepare_document")["note"]
    assert "단순 처리 경로" in note and count(c, DocumentVersion) == 2
    acknowledge_all(c)
    ready = ok(c.get("/cases/L/closure", headers=H("bob")), 200)
    assert ready["ready"], ready["blocks"]
    ok(c.post("/cases/L/closure", headers=H("bob"), json={"residual_risks": [{"risk": "signal may recur on L03", "mitigation": "keep SPC watch on SMT-1", "owner": "frank"}],
                                                       "customer_notification_ref": "CN-2026-0099", "comment": "closed on NCR_ONLY"}))
    r = c.get("/cases/L/report/export?format=pdf", headers=H("bob"))
    text = squash(opened(r, "pdf"))
    assert "NCR_closure_report" in r.headers["content-disposition"]
    assert all(squash(x) in text for x in ("NCR closure report", "Route NCR_ONLY", "N/A (NCR_ONLY)"))
    assert squash("D4 confirmed causes") not in text  # an empty, not-required section is left out
    links = run(c, "종료 보고서 내보내 줘")
    assert next(s for s in links["steps"] if s["tool"] == "exports")["result"]["report"] == "/cases/L/report/export"
