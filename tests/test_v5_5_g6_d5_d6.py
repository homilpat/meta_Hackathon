"""G6: D5 corrective-action selection needs confirmed causes; D6 effectiveness is computed by the server against
criteria registered before execution, and only a reviewer can call it EFFECTIVE when those criteria are met."""

import pytest

from tests.v5_util import H, confirmed_cause, line_client

DETAILS = {"feasibility": "spare stencil in stock, 30 min change", "risk_analysis": "new stencil needs first-article",
           "side_effects": "none expected on other components"}


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def option(c, causes, user="alice", **kw):
    body = {"stage": "D5", "action_type": "EQUIPMENT_CHANGE", "cause_ids": list(causes), "details": DETAILS,
            "description": "Replace stencil STN-2 and enforce the cleaning interval", **kw}
    return c.post("/cases/L/actions", json=body, headers=H(user))


def event(c, aid, user, event_type, note="", evidence=()):
    return c.post(f"/cases/L/actions/{aid}/events", headers=H(user),
                  json={"event_type": event_type, "note": note, "evidence": list(evidence)})


def plan(c, aid, user="bob", **kw):
    body = {"action_id": aid, "metric": "SPI_MEAN_VOLUME_MM3", "baseline_lots": ["L02"], "min_sample": 50,
            "acceptance": {"op": ">=", "value": 0.115}, "inspection_conditions": {"inspection_id": "S01"},
            "monitoring": "SPI mean per lot for the next lot after the change", **kw}
    return c.post("/cases/L/effectiveness-plans", json=body, headers=H(user))


def selected(c):
    h = confirmed_cause(c)
    aid = option(c, [h]).json()["action_id"]
    assert event(c, aid, "frank", "PLAN_APPROVED", "fresh stencil trial passed first-article").status_code == 201
    return h, aid


def executed(c, effective=True, **plan_kw):
    h, aid = selected(c)
    p = plan(c, aid, **plan_kw)
    assert p.status_code == 201, p.text
    assert event(c, aid, "erin", "EXECUTED", "stencil STN-2 replaced on SMT-1 (simulated)").status_code == 201
    r = c.post("/cases/L/synthetic/post-window", json={"action_id": aid, "effective": effective}, headers=H("alice"))
    assert r.status_code == 201, r.text
    return h, aid, p.json()["plan_id"]


def judge(c, plan_id, decision, user="bob"):
    return c.post("/cases/L/effectiveness", headers=H(user),
                  json={"plan_id": plan_id, "decision": decision, "note": "reviewed SPI comparison for L04"})


def state(c):
    return c.get("/cases/L/gates", headers=H("alice")).json()["state"]


def test_d5_option_needs_causes_and_risk_analysis(c):
    h = confirmed_cause(c)
    assert option(c, []).status_code == 422
    assert option(c, [h], details={"feasibility": "ok"}).status_code == 422
    assert option(c, [h], user="erin").status_code == 403
    assert option(c, [9999]).status_code == 404


def test_unconfirmed_cause_cannot_be_selected(c):
    h = c.post("/cases/L/hypotheses", headers=H("alice"), json={
        "cause_type": "OCCURRENCE", "category": "MATERIAL", "text": "Paste lot viscosity drift"}).json()["hypothesis_id"]
    aid = option(c, [h]).json()["action_id"]
    r = event(c, aid, "frank", "PLAN_APPROVED", "looks right")
    assert r.status_code == 409 and "CONFIRMED" in r.json()["detail"]
    assert event(c, aid, "bob", "PLAN_APPROVED").status_code in (403, 409)


def test_selected_is_not_implemented_and_execution_needs_a_precommitted_plan(c):
    _, aid = selected(c)
    assert state(c)["D5"] == "DONE" and state(c)["D6"] is None  # chosen, not done
    r = event(c, aid, "erin", "EXECUTED", "stencil replaced (simulated)")
    assert r.status_code == 409 and "precommitted" in r.json()["detail"]
    pid = plan(c, aid).json()["plan_id"]
    r = judge(c, pid, "EFFECTIVE")
    assert r.status_code == 409 and "EXECUTED" in r.json()["detail"]  # never-executed action


def test_valid_synthetic_success(c):
    _, aid, pid = executed(c)
    assert judge(c, pid, "EFFECTIVE", user="frank").status_code == 403  # D6 decision belongs to the reviewer
    r = judge(c, pid, "EFFECTIVE")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["computed"] == "MEETS_CRITERIA" and out["data_origin"] == "SYNTHETIC"
    obs = out["observed"]
    assert obs["post"]["mean"] >= 0.115 > obs["baseline"]["mean"] and obs["difference"]["ci95"][0] > 0
    assert obs["post"]["n"] >= 50 and obs["baseline"]["lots"] == ["L02"]
    a = next(x for x in c.get("/cases/L/actions", headers=H("alice")).json() if x["action_id"] == aid)
    assert a["status"] == "INDEPENDENTLY_VERIFIED" and a["events"][-1]["evidence"] == [f"EFF-{out['result_id']}"]
    assert state(c)["D6"] == "DONE"


def test_sample_insufficiency_is_inconclusive(c):
    _, _, pid = executed(c, min_sample=100000)
    r = judge(c, pid, "EFFECTIVE")
    assert r.status_code == 409 and "sample too small" in r.json()["detail"]
    assert judge(c, pid, "INCONCLUSIVE").json()["computed"] == "INCONCLUSIVE"
    assert state(c)["D6"] == "IN_PROGRESS"


def test_changed_inspection_rule_is_inconclusive(c):
    _, _, pid = executed(c, inspection_conditions={"inspection_id": "S02"})
    r = judge(c, pid, "EFFECTIVE")
    assert r.status_code == 409 and "inspection condition" in r.json()["detail"]


def test_criteria_cannot_be_registered_after_execution_or_results(c):
    _, aid, pid = executed(c)
    r = plan(c, aid, acceptance={"op": ">=", "value": 0.05})  # loosen the bar after seeing data
    assert r.status_code == 409 and "before execution" in r.json()["detail"]
    judge(c, pid, "EFFECTIVE")
    assert plan(c, aid).status_code == 409


def test_negative_outcome_reopens_d4_and_keeps_history(c):
    h, _, pid = executed(c, effective=False)
    r = judge(c, pid, "EFFECTIVE")
    assert r.status_code == 409 and "FAILS_CRITERIA" in r.json()["detail"]
    r = judge(c, pid, "NOT_EFFECTIVE")
    assert r.status_code == 201 and r.json()["computed"] == "FAILS_CRITERIA"
    hyp = c.get("/cases/L/hypotheses", headers=H("alice")).json()["hypotheses"][0]
    assert hyp["status"] == "OPEN" and hyp["decision"]["decision"] == "REOPENED"
    s = state(c)
    assert s["D6"] == "NOT_EFFECTIVE" and s["D5"] != "DONE"
    events = [e["event"] for e in c.get("/cases/L/timeline", headers=H("alice")).json()]
    assert events.index("D4_CONFIRMED") < events.index("D6_NOT_EFFECTIVE")  # failure kept, nothing rewritten
    assert "D4_REOPENED" in events
    old = hyp["experiments"][0]["experiment_id"]
    r = c.post("/cases/L/causal-decisions", headers=H("frank"), json={
        "hypothesis_id": h, "decision": "CONFIRMED", "basis_experiment_ids": [old], "rationale": "same as before"})
    assert r.status_code == 409 and "reopened" in r.json()["detail"]


def test_post_window_needs_an_executed_action(c):
    _, aid = selected(c)
    r = c.post("/cases/L/synthetic/post-window", json={"action_id": aid}, headers=H("alice"))
    assert r.status_code == 409
