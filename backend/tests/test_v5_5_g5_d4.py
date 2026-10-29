"""G5: D4 hypotheses -> experiments -> causal decisions. Only a documented supporting experiment, reviewed by an
independent qualified person on VALID evidence, can confirm a cause."""

import pytest

from tests.v5_util import H, evidence, line_client


@pytest.fixture
def c(tmp_path):
    client = line_client(tmp_path)
    yield client
    client.app_ref.state.engine.dispose()


def valid(c, kind, **match):
    ok = {i["evidence_id"] for i in c.get("/cases/L/evidence-quality?state=VALID", headers=H("alice")).json()["items"]}
    return [e for e in evidence(c, "L", kind, **match) if e in ok]


def stencil_ev(c):
    return valid(c, "equipment_events")[:1] + valid(c, "lots", lot_id="L02")[:1]


def hyp(c, user="alice", **kw):
    body = {"cause_type": "OCCURRENCE", "category": "MACHINE", "evidence_ids": stencil_ev(c),
            "text": "Worn stencil STN-2 under-deposits paste in lot L02", **kw}
    r = c.post("/cases/L/hypotheses", json=body, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()["hypothesis_id"]


def exp(c, hid, result="SUPPORTS", user="alice", **kw):
    body = {"hypothesis_id": hid, "method": "Swap STN-2 for a fresh stencil, same paste lot, compare SPI volume",
            "controlled_conditions": ["paste lot unchanged", "same line SMT-1", "same SPI recipe"],
            "baseline": {"stencil": "STN-2", "lot": "L02"}, "intervention": {"stencil": "fresh"},
            "sample_size": 32, "acceptance_rule": "fresh-stencil mean SPI volume within 0.11-0.13 mm3",
            "evidence_ids": valid(c, "spi_measurements", panel_id="L02*")[:8], "result": result, **kw}
    r = c.post("/cases/L/experiments", json=body, headers=H(user))
    assert r.status_code == 201, r.text
    return r.json()["experiment_id"]


def decide(c, hid, decision="CONFIRMED", basis=(), user="frank", **kw):
    return c.post("/cases/L/causal-decisions", headers=H(user), json={
        "hypothesis_id": hid, "decision": decision, "basis_experiment_ids": list(basis),
        "rationale": "fresh-stencil run restored the SPI volume", **kw})


def hyps(c):
    return c.get("/cases/L/hypotheses", headers=H("alice")).json()


def test_valid_confirmed_cause_after_independent_supporting_experiment(c):
    h = hyp(c)
    e = exp(c, h)
    out = c.get("/cases/L/hypotheses", headers=H("alice")).json()["hypotheses"][0]
    assert out["status"] == "OPEN" and out["experiments"][0]["execution_mode"] == "SIMULATED"
    r = decide(c, h, basis=[e])
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "CONFIRMED" and r.json()["decision"]["actor_id"] == "frank"
    assert hyps(c)["confirmed"] == [h]
    assert decide(c, h, basis=[e]).status_code == 409  # already confirmed
    events = [e["event"] for e in c.get("/cases/L/timeline", headers=H("alice")).json()]
    assert {"D4_HYPOTHESIS", "D4_EXPERIMENT", "D4_CONFIRMED"} <= set(events)


def test_ai_shap_or_precedent_alone_cannot_confirm(c):
    for origin in ("SHAP", "AI_PROPOSED", "PRECEDENT"):
        h = hyp(c, origin=origin, text=f"{origin}: paste volume feature ranks highest for L02 boards")
        r = decide(c, h)
        assert r.status_code == 409 and "not an experiment" in r.json()["detail"]


def test_decision_needs_the_policy_role(c):
    h = hyp(c)
    e = exp(c, h)
    for user in ("alice", "bob", "erin"):
        assert decide(c, h, basis=[e], user=user).status_code == 403


def test_non_independent_reviewer_cannot_confirm_own_experiment(c):
    h = hyp(c)
    e = exp(c, h, user="frank")
    r = decide(c, h, basis=[e])
    assert r.status_code == 409 and "independent reviewer" in r.json()["detail"]


def test_missing_or_unknown_evidence_is_refused(c):
    r = c.post("/cases/L/hypotheses", headers=H("alice"), json={
        "cause_type": "OCCURRENCE", "category": "MACHINE", "text": "stencil wear", "evidence_ids": ["EV-nope"]})
    assert r.status_code == 422
    h = hyp(c)
    r = c.post("/cases/L/experiments", headers=H("alice"), json={
        "hypothesis_id": h, "method": "look at it closely", "controlled_conditions": [], "baseline": {},
        "intervention": {}, "sample_size": 1, "acceptance_rule": "it looks fine", "evidence_ids": [],
        "result": "SUPPORTS"})
    assert r.status_code == 422  # no controls, no baseline, n<2, no evidence: not a documented experiment


def test_counter_evidence_must_be_addressed(c):
    counter = valid(c, "spi_measurements", panel_id="L03*")[:2]
    h = hyp(c, counter_evidence_ids=counter)
    e = exp(c, h)
    r = decide(c, h, basis=[e])
    assert r.status_code == 409 and "not addressed" in r.json()["detail"]
    ok = decide(c, h, basis=[e], counter_evidence_response="L03 ran on STN-1; its slight drift is a WE4 false signal")
    assert ok.status_code == 201 and "counter evidence" in ok.json()["decision"]["rationale"]


def test_contradicting_experiment_blocks_confirmation_and_supports_rejection(c):
    h = hyp(c, category="MATERIAL", text="Paste lot PL-7 viscosity out of range caused low deposits in L02")
    e = exp(c, h, result="CONTRADICTS", intervention={"paste_lot": "fresh"})
    s = exp(c, h)
    r = decide(c, h, basis=[s])
    assert r.status_code == 409 and "contradict" in r.json()["detail"]
    assert decide(c, h, "REJECTED").status_code == 422  # a rejection rests on an experiment too
    assert decide(c, h, "REJECTED", basis=[e]).status_code == 201
    assert hyps(c)["hypotheses"][0]["status"] == "REJECTED"


def test_inconclusive_without_experiment_and_multiple_causes(c):
    occ = hyp(c)
    nd = hyp(c, cause_type="NON_DETECTION", category="MEASUREMENT",
             text="AOI threshold let low-volume joints pass on L02 boards")
    sys_ = hyp(c, cause_type="SYSTEMIC", category="METHOD", text="Stencil cleaning interval not enforced")
    assert decide(c, sys_, "INCONCLUSIVE").status_code == 201
    for h in (occ, nd):
        assert decide(c, h, basis=[exp(c, h)]).status_code == 201
    out = hyps(c)
    assert out["confirmed"] == [occ, nd]  # several causes may hold together
    assert [x["hypothesis_id"] for x in out["fishbone"]["MEASUREMENT"]] == [nd]
    assert out["fishbone"]["METHOD"][0]["status"] == "INCONCLUSIVE"


def test_suspect_evidence_cannot_prove_a_cause(c):
    h = hyp(c)
    e = exp(c, h)
    ev = stencil_ev(c)[0]
    r = c.post("/cases/L/evidence-quality", headers=H("bob"),
               json={"evidence_id": ev, "quality_state": "SUSPECT", "reason": "maintenance log entry unsigned"})
    assert r.status_code == 201
    r = decide(c, h, basis=[e])
    assert r.status_code == 409 and "not usable as ROOT_CAUSE" in r.json()["detail"]


def test_why_links_need_grounding_and_falsification(c):
    a, b = hyp(c), hyp(c, cause_type="SYSTEMIC", category="METHOD", text="Cleaning interval not enforced on STN-2")
    base = {"parent_id": a, "child_id": b, "falsification_criteria": "a cleaned STN-2 still under-deposits"}
    assert c.post("/cases/L/why-links", json={**base, "supporting_ids": []}, headers=H("alice")).status_code == 422
    assert c.post("/cases/L/why-links", json={**base, "supporting_ids": ["EV-x"]}, headers=H("alice")).status_code == 422
    r = c.post("/cases/L/why-links", json={**base, "supporting_ids": stencil_ev(c)[:1]}, headers=H("alice"))
    assert r.status_code == 201
    assert hyps(c)["why_links"][0]["child_id"] == b


def test_hypothesis_can_point_at_an_rca_draft_claim(c):
    for kind in ("ncr", "containment", "rca"):
        assert c.post(f"/cases/L/{kind}", json={}, headers=H("alice")).status_code == 201
    claims = c.get("/cases/L/rca/1", headers=H("alice")).json()["claims"]
    hc = next(x["claim_id"] for x in claims if x["classification"] == "HYPOTHESIS")
    oc = next(x["claim_id"] for x in claims if x["classification"] == "OBSERVED")
    assert hyp(c, origin="RCA_DRAFT", source_claim=f"RCA v1:{hc}")
    r = c.post("/cases/L/hypotheses", headers=H("alice"), json={
        "cause_type": "OCCURRENCE", "category": "MACHINE", "text": "an observation is not a hypothesis",
        "source_claim": f"RCA v1:{oc}"})
    assert r.status_code == 422
    assert c.get("/cases/L/rca/1", headers=H("alice")).json()["claims"] == claims  # the draft is untouched
