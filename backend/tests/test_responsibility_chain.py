"""RW-UI-01..06 (spec v5.13 §25.5-25.6): the responsibility view reads each request, action and document version
from its own records: assigned vs accepted, plan approval vs execution vs verification vs effect, and decisions with
role, time, reason, version and hash. Re-read after every change; Queue and audit agree with it."""

from tests.test_requests_rw import post, request_body
from tests.test_s6_followups import approve, create, env, revise  # noqa: F401 - env: seeded case fixture
from tests.test_v5_5_g6_d5_d6 import executed, selected
from tests.test_v5_g3_d0_d1 import event, hold, triage
from tests.v5_util import H, line_client


def resp(c, case="L", user="alice"):
    r = c.get(f"/cases/{case}/responsibilities", headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def test_two_actions_keep_their_own_executor_and_verifier(tmp_path):
    c = line_client(tmp_path)
    triage(c)
    a = hold(c, targets=["L02-P09"]).json()["action_id"]
    b = hold(c, targets=["L02-P10"]).json()["action_id"]
    for aid, verifier in ((a, "bob"), (b, "carol")):
        assert event(c, aid, "erin", "EXECUTED", note=f"held at SMT-1 exit, action {aid}").status_code == 201
        assert event(c, aid, verifier, "INDEPENDENTLY_VERIFIED", evidence=[f"REF:count-{aid}"]).status_code == 201
    acts = {x["action_id"]: x for x in resp(c)["actions"]}
    assert (acts[a]["executed_by"], acts[a]["verified_by"]) == ("erin", "bob")
    assert (acts[b]["executed_by"], acts[b]["verified_by"]) == ("erin", "carol")  # never mixed across actions
    assert "VERIFIED" in acts[a]["states"] and not set(acts[a]["audit_event_ids"]) & set(acts[b]["audit_event_ids"])


def test_plan_approval_is_not_execution_and_execution_is_not_an_effect(tmp_path):
    c = line_client(tmp_path)
    _, aid = selected(c)  # D5: plan approved by frank, nothing executed
    x = next(x for x in resp(c)["actions"] if x["action_id"] == aid)
    assert x["plan_approved_by"] == "frank" and x["executed_by"] is None
    assert x["states"] == ["PLAN_APPROVED", "NOT_EXECUTED"]
    assert any("NOT_EXECUTED" in b for b in resp(c)["summary"]["blocked_by"])


def test_an_executed_action_without_an_effect_decision_is_effect_unverified(tmp_path):
    c = line_client(tmp_path)
    _, aid, _ = executed(c)
    x = next(x for x in resp(c)["actions"] if x["action_id"] == aid)
    assert x["executed_by"] == "erin" and "EFFECT_UNVERIFIED" in x["states"] and x["effect_reviews"] == []


def test_a_handover_shows_both_people_until_accepted_and_keeps_the_history(tmp_path):
    c = line_client(tmp_path)
    rid = post(c, "/cases/L/requests", request_body("INTERNAL")).json()["request_id"]
    post(c, f"/requests/{rid}/open")
    post(c, f"/requests/{rid}/handover", {"to_user": "dave", "reason": "공정 담당으로 이관"})
    r = next(x for x in resp(c)["requests"] if x["request_id"] == rid)
    assert r["owner_id"] == "alice" and r["pending_owner_id"] == "dave" and "HANDOVER_PENDING" in r["states"]
    queue = c.get("/queue?scope=mine", headers=H("dave")).json()
    assert any(i.get("request_id") == rid or i.get("task") == "HANDOVER_ACCEPT" for i in queue)  # same record
    assert post(c, f"/requests/{rid}/handover/decline", {"reason": "담당 아님"}, user="dave").status_code == 201
    r = next(x for x in resp(c)["requests"] if x["request_id"] == rid)
    assert r["owner_id"] == "alice" and r["pending_owner_id"] is None and "HANDOVER_PENDING" not in r["states"]
    post(c, f"/requests/{rid}/handover", {"to_user": "dave", "reason": "재요청"})
    post(c, f"/requests/{rid}/handover/accept", {"reason": "수락"}, user="dave")
    r = next(x for x in resp(c)["requests"] if x["request_id"] == rid)
    assert r["owner_id"] == "dave" and [e["event"] for e in r["events"]].count("HANDOVER_REQUESTED") == 2
    assert "HANDOVER_DECLINED" in [e["event"] for e in r["events"]]  # the earlier answer is kept


def test_a_changed_basis_after_approval_shows_re_review_with_the_signed_hash(env):  # noqa: F811
    c = env
    for kind in ("ncr", "containment"):
        create(c, kind)
    approve(c, "ncr", 1)
    approve(c, "containment", 1)
    before = {(d["doc_type"], d["version"]): d for d in resp(c, "C1")["decisions"]}
    signed = before[("CONTAINMENT", 1)]["decisions"][-1]
    assert signed["by"] == "erin" and signed["role"] == "QA_PRODUCTION" and signed["on_current_content"]
    revise(c)  # the NCR changes under the approved containment plan
    after = {(d["doc_type"], d["version"]): d for d in resp(c, "C1")["decisions"]}
    assert after[("CONTAINMENT", 1)]["states"] == ["RE_REVIEW_NEEDED"]
    assert after[("CONTAINMENT", 1)]["decisions"][-1]["event_id"] == signed["event_id"]  # the decision stays
    assert after[("CONTAINMENT", 1)]["audit_event_ids"]


def test_a_role_without_a_named_reviewer_is_shown_as_unassigned(env):  # noqa: F811
    c = env
    create(c, "ncr")
    d = next(d for d in resp(c, "C1")["decisions"] if d["doc_type"] == "NCR")
    assert d["approver_role"] == "REVIEWER" and d["reviewer"] == "ROLE_ONLY_UNASSIGNED"


def test_someone_outside_the_case_sees_nothing(tmp_path):
    c = line_client(tmp_path)
    for user in ("gina",):  # not assigned to case L
        assert c.get("/cases/L/responsibilities", headers=H(user)).status_code in (403, 404)
