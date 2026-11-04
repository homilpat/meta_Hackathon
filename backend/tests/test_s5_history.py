import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import history
from app.db import Base, Evidence
from app.main import create_app
from app.report import InvestigationReport, validate_report
from app.synthetic import generate
from app.tools import EvidenceTools, ToolError
from scripts.history_compare import QUERIES
from tests.test_s3_investigation import Scripted, final, tools_msg

A = {"X-User": "alice"}


@pytest.fixture
def env(tmp_path):
    provider = Scripted()
    app = create_app(f"sqlite:///{tmp_path / 'h.db'}", provider)
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": "C1"}, headers=A)
    c.post("/cases/C1/sources", json=generate(7), headers=A)
    c.post("/cases/C1/assignments", json={"user_id": "bob"}, headers=A)
    with Session(app.state.engine) as s:
        yield c, s, provider
    app.state.engine.dispose()


def prof(*boards, as_of="2026-01-03T09:00:00+00:00"):
    return history.Profile(as_of=as_of, boards={f"X/B{i}": {"spi": sp, "aoi": ao, "evidence": []}
                                                for i, (sp, ao) in enumerate(boards, 1)})


def ids(found):
    return [p["historical_case_id"] for p in found["precedents"]]


def test_asof_filter_excludes_records_not_yet_available(env):
    _, s, _ = env
    early = history.retrieve(s, prof(("SPI_VOLUME_LOW", "AOI_FAIL_CONFIRMED")))
    late = history.retrieve(s, prof(("SPI_VOLUME_LOW", "AOI_FAIL_CONFIRMED"), as_of="2026-03-01T00:00:00+00:00"))
    assert "H12" not in ids(early) and early["excluded"]["NOT_YET_AVAILABLE"] == 1
    assert "H12" in ids(late)


def test_draft_retracted_cross_site_confidential_and_wrong_process_excluded(env):
    _, s, _ = env
    found = history.retrieve(s, prof(("SPI_VOLUME_LOW", "AOI_FAIL_CONFIRMED"), ("SPI_VOLUME_SCATTER", "AOI_FALSE_ALARM"),
                                     ("NORMAL", "AOI_FAIL_CONFIRMED")))
    assert not {"H07", "H09", "H10", "H11", "H13"} & set(ids(found))
    assert "H08" in ids(found)  # the revision of retracted H07 is eligible
    assert found["excluded"] == {"NOT_APPROVED_OR_SUPERSEDED": 2, "CROSS_SITE": 1, "NOT_APPROVED_FOR_EXTERNAL": 1,
                                 "NOT_YET_AVAILABLE": 1, "PROCESS_MISMATCH": 1}
    assert "CONFIDENTIAL-MARKER" not in json.dumps(found)


def test_failed_action_is_a_warning_never_a_recommendation(env):
    _, s, _ = env
    p = prof(("SPI_VOLUME_LOW", "AOI_FALSE_ALARM"))
    plan = history.plan_next_evidence(p, history.retrieve(s, p))
    assert any("PRINTER_PRESSURE_ADJUST" in w["text"] and "쓰지 마세요" in w["text"] for w in plan["warnings"])
    assert "printer pressure" not in json.dumps(plan["next_checks"]).lower()
    assert any("already answered" in k["text"] for k in plan["known"])  # adjudication is not re-requested


def test_unknown_or_unverified_outcomes_are_not_ranked_as_success(env):
    _, s, _ = env
    p = prof(("SPI_VOLUME_LOW", "AOI_MISSING"))
    plan = history.plan_next_evidence(p, history.retrieve(s, p))
    assert [c["check"] for c in plan["next_checks"]] == ["AOI_RERUN"]
    assert all("success" not in c["reason"].lower() for c in plan["next_checks"])
    insufficient = history.plan_next_evidence(prof(("NORMAL", "AOI_FALSE_ALARM")),
                                              history.retrieve(s, prof(("NORMAL", "AOI_FALSE_ALARM"))))
    assert any("INSUFFICIENT" in w["text"] for w in insufficient["warnings"])


def test_partial_match_does_not_drive_a_check(env):
    _, s, _ = env
    p = prof(("SPI_VOLUME_LOW", "AOI_FAIL_UNVERIFIED"))  # looks like H01/H02 but has no operator verdict
    plan = history.plan_next_evidence(p, history.retrieve(s, p))
    assert [c["check"] for c in plan["next_checks"]] == ["OPERATOR_ADJUDICATION"] and not plan["precedents_used"]


def test_no_relevant_precedent(env):
    _, s, _ = env
    p = prof(("NORMAL", "AOI_PASS"))
    found = history.retrieve(s, p)
    plan = history.plan_next_evidence(p, found)
    assert found["status"] == "NO_RELEVANT_PRECEDENT" and found["precedents"] == []
    assert plan["next_checks"] == [] and plan["unknown"]


def test_eval_queries_are_disjoint_from_the_bank():
    families = {h["family"] for h in history.bank()}
    assert not families & {q[1] for q in QUERIES} and len(QUERIES) >= 20


def test_validator_precedent_rules(env):
    _, s, _ = env
    precedents = history.retrieve(s, history.case_profile(s, "C1"))["precedents"]
    ev = s.scalar(select(Evidence.evidence_id))

    def check(next_checks, findings=None, allowed=precedents):
        r = InvestigationReport(summary="s", findings=findings or [{"classification": "UNKNOWN", "text": "t"}],
                                next_evidence_requests=next_checks)
        return validate_report(s, "C1", r, allowed)

    ok = {"check": "Operator adjudication of the AOI call", "reason": "H02 showed false calls; do not repeat "
          "the printer pressure change", "evidence_ids": [ev], "precedent_ids": ["H02"]}
    assert check([ok]) == []
    assert any("not retrieved as eligible" in e for e in check([{**ok, "precedent_ids": ["H12"]}]))
    assert any("not retrieved as eligible" in e for e in check([{**ok, "precedent_ids": ["H99"]}]))
    assert any("failed before" in e for e in check([{**ok, "reason": "Adjust printer pressure like H02"}]))
    assert any("not retrieved" in e for e in check([ok], allowed=None))  # history OFF: nothing citable
    assert any("needs evidence_ids" in e for e in check([{**ok, "evidence_ids": []}]))  # a precedent alone is not enough
    bad = check([], findings=[{"classification": "OBSERVED", "text": "Same as H01.", "evidence_ids": [ev]}])
    assert any("not evidence about this case" in e for e in bad)


def test_history_off_hides_tools_and_records_flag(env):
    c, s, provider = env
    assert "retrieve_historical_cases" not in json.dumps(EvidenceTools(s, "C1").specs())
    with pytest.raises(ToolError):
        EvidenceTools(s, "C1").call("retrieve_historical_cases", {})
    provider.replies[:] = [tools_msg(("get_case_context", {})), final({"summary": "s", "findings": [
        {"classification": "UNKNOWN", "text": "t"}]})]
    run = c.post("/cases/C1/investigations", json={"use_history": False},
                 headers={**A, "Idempotency-Key": uuid.uuid4().hex}).json()
    # an UNKNOWN-only report keeps every rule but grounds nothing: INCOMPLETE under the task contract (§27.4)
    assert run["history"] == "OFF" and run["status"] == "INCOMPLETE"
    assert "retrieve_historical_cases" not in provider.seen[0]


def test_history_on_tool_flow_and_egress(env):
    c, _, provider = env
    ev = c.get("/cases/C1/evidence", headers=A).json()[0]["evidence_id"]  # a next check rests on case data
    provider.replies[:] = [tools_msg(("retrieve_historical_cases", {}), ("get_historical_case_outcome",
                                                                         {"historical_case_id": "H11"})),
                           final({"summary": "s", "findings": [{"classification": "UNKNOWN", "text": "t"}],
                                  "next_evidence_requests": [{"check": "Rerun AOI on P01/B02",
                                                              "reason": "no AOI record", "evidence_ids": [ev],
                                                              "precedent_ids": []}]})]
    run = c.post("/cases/C1/investigations", json={"use_history": True},
                 headers={**A, "Idempotency-Key": uuid.uuid4().hex}).json()
    # rules kept, a next check proposed, but nothing grounded: insufficient evidence documented, not complete
    assert run["history"] == "ON" and run["status"] == "INCOMPLETE", run["validation_errors"]
    assert all(e.startswith("REQUIRED_ITEM") for e in run["validation_errors"])
    assert [t["ok"] for t in run["tool_calls"]] == [True, False]  # H11 is not eligible
    sent = "".join(provider.seen)
    assert "H02" in sent and "CONFIDENTIAL-MARKER" not in sent and '"H10"' not in sent


def test_api_scope_links_and_demo_plan(env):
    c, _, _ = env
    assert c.get("/cases/C1/history", headers={"X-User": "carol"}).status_code == 403
    on = c.get("/cases/C1/next-evidence?history_mode=on", headers=A).json()
    off = c.get("/cases/C1/next-evidence?history_mode=off", headers=A).json()
    assert off["history"] == "OFF" and off["warnings"] == [] and on["warnings"]
    bad = c.post("/cases/C1/history/links", json={"historical_case_id": "H10", "decision": "ACCEPTED"}, headers=A)
    assert bad.status_code == 422
    assert c.post("/cases/C1/history/links", json={"historical_case_id": "H02", "decision": "ACCEPTED"},
                  headers={"X-User": "bob"}).status_code == 403
    assert c.post("/cases/C1/history/links", json={"historical_case_id": "H02", "decision": "ACCEPTED",
                                                   "note": "use as warning"}, headers=A).status_code == 201
    events = [t["event"] for t in c.get("/cases/C1/timeline", headers=A).json()]
    assert "PRECEDENT_ACCEPTED" in events
