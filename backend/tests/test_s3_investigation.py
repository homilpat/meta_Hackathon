import io
import json
import uuid
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, QualityCase, SourceEvent
from app.main import create_app
from app.model_provider import MODEL, EgressBlocked, MetaProvider, ProviderError
from app.synthetic import generate
from app.tools import EvidenceTools


class Scripted:
    """Test double. Declares itself; never labelled LIVE."""

    mode, model = "TEST_DOUBLE", "scripted-test-double"

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.seen.append(json.dumps(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {"message": reply, "usage": {"prompt_tokens": 100, "completion_tokens": 50}}


def tools_msg(*calls):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"t{i}", "type": "function",
         "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
        for i, (n, a) in enumerate(calls)]}


def final(report):
    return {"role": "assistant", "content": report if isinstance(report, str) else json.dumps(report)}


LOOKUP = tools_msg(("get_case_context", {}), ("get_manufacturing_events", {"entity_type": "aoi_inspections"}))


@pytest.fixture
def make(tmp_path):
    apps = []

    def build(provider):
        app = create_app(f"sqlite:///{tmp_path / f'case{len(apps)}.db'}", provider)
        Base.metadata.create_all(app.state.engine)
        apps.append(app)
        c = TestClient(app)
        h = {"X-User": "alice"}
        assert c.post("/cases", json={"case_id": "C1"}, headers=h).status_code == 201
        assert c.post("/cases/C1/sources", json=generate(7), headers=h).status_code == 201
        assert c.post("/cases/C1/assignments", json={"user_id": "bob"}, headers=h).status_code == 201
        c.app_ref = app
        return c

    yield build
    for app in apps:
        app.state.engine.dispose()


def run(c, user="alice", key=None):
    return c.post("/cases/C1/investigations", headers={"X-User": user, "Idempotency-Key": key or uuid.uuid4().hex})


def evidence(c):
    """{evidence_id: (entity_type, entity_key, record)} straight from the S1 API."""
    h = {"X-User": "alice"}
    events = {e["event_id"]: e for e in c.get("/cases/C1/events", headers=h).json()}
    return {v["evidence_id"]: (events[v["event_id"]]["entity_type"], events[v["event_id"]]["entity_key"],
                               events[v["event_id"]]["record"]) for v in c.get("/cases/C1/evidence", headers=h).json()}


def good_report(ev):
    aoi = [k for k, (t, _, _) in ev.items() if t == "aoi_inspections"]
    fail = [k for k in aoi if ev[k][2]["result"] == "FAIL"]
    spi = [k for k, (t, key, r) in ev.items()
           if t == "spi_measurements" and key[:2] == ["P02", "B01"]][:2]
    mean = sum(ev[k][2]["volume_mm3"] for k in spi) / len(spi)
    return {"summary": "Two AOI failures; one confirmed defect on P02/B01. Cause undetermined.",
            "findings": [
                {"classification": "OBSERVED", "text": "AOI A01 on P02/B01 reported FAIL.", "evidence_ids": fail[-1:]},
                {"classification": "CALCULATED", "text": "Share of AOI inspections that failed.",
                 "evidence_ids": aoi, "value": len(fail) / len(aoi), "unit": "ratio",
                 "calc": {"op": "ratio", "numerator_evidence_ids": fail, "denominator_evidence_ids": aoi}},
                {"classification": "CALCULATED", "text": "Mean SPI volume on P02/B01.", "evidence_ids": spi,
                 "value": round(mean, 6), "unit": "mm3", "calc": {"op": "mean", "field": "volume_mm3"}},
                {"classification": "HYPOTHESIS", "text": "Paste volume variation is a candidate to investigate.",
                 "evidence_ids": spi},
                {"classification": "UNKNOWN", "text": "Board P01/B02 has no AOI record; not a pass."}],
            "open_questions": ["Was the stencil inspected?"]}


def outcome(c, *replies):
    c.app_ref.state.provider.replies[:] = replies
    r = run(c)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def case(make):
    return make(Scripted())


def test_valid_report_is_validated_and_tool_calls_logged(case):
    out = outcome(case, LOOKUP, final(good_report(evidence(case))))
    assert out["status"] == "VALIDATED", out["validation_errors"]
    assert out["mode"] == "TEST_DOUBLE" and out["rounds"] == 2 and out["prompt_tokens"] == 200
    assert [c["tool_name"] for c in out["tool_calls"]] == ["get_case_context", "get_manufacturing_events"]
    assert all(c["ok"] and len(c["result_sha256"]) == 64 for c in out["tool_calls"])
    events = [t["event"] for t in case.get("/cases/C1/timeline", headers={"X-User": "alice"}).json()]
    assert "INVESTIGATION_RUN" in events


def test_fabricated_evidence_id_is_blocked(case):
    report = good_report(evidence(case))
    report["findings"][0]["evidence_ids"] = ["EV-" + "f" * 20]
    out = outcome(case, LOOKUP, final(report))
    assert out["status"] == "VALIDATION_FAILED" and "unknown evidence_id" in out["validation_errors"][0]


def test_fabricated_reference_inside_text_is_blocked(case):
    report = good_report(evidence(case))
    report["findings"][4]["text"] = "See EV-" + "a" * 20 + " for the pass record."
    out = outcome(case, LOOKUP, final(report))
    assert any("nonexistent" in e for e in out["validation_errors"])


@pytest.mark.parametrize("index,value", [(1, 0.75), (2, 0.5)])
def test_wrong_ratio_or_mean_is_blocked(case, index, value):
    report = good_report(evidence(case))
    report["findings"][index]["value"] = value
    out = outcome(case, LOOKUP, final(report))
    assert out["status"] == "VALIDATION_FAILED" and "recomputed" in out["validation_errors"][0]


@pytest.mark.parametrize("text", ["The root cause is stencil wear.", "Bridging was caused by excess paste.",
                                  "This definitely explains the failure."])
def test_causal_certainty_is_blocked(case, text):
    report = good_report(evidence(case))
    report["findings"][3]["text"] = text
    out = outcome(case, LOOKUP, final(report))
    assert any("causal certainty" in e for e in out["validation_errors"])


def test_confirmed_class_or_root_cause_field_is_rejected_by_schema(case):
    report = good_report(evidence(case))
    report["findings"][3]["classification"] = "CONFIRMED"
    assert outcome(case, LOOKUP, final(report))["status"] == "JSON_ERROR"
    report = good_report(evidence(case))
    report["root_cause"] = {"status": "CONFIRMED"}
    assert outcome(case, LOOKUP, final(report))["status"] == "JSON_ERROR"


def test_external_source_is_blocked(case):
    report = good_report(evidence(case))
    report["summary"] = "Per https://example.com/ipc the defect is typical."
    out = outcome(case, LOOKUP, final(report))
    assert any("external source" in e for e in out["validation_errors"])


def test_answer_without_tool_use_is_not_grounded(case):
    out = outcome(case, final(good_report(evidence(case))))
    assert out["status"] == "VALIDATION_FAILED" and "not grounded" in out["validation_errors"][-1]


def test_bad_tool_calls_are_logged_and_loop_continues(case):
    bad = tools_msg(("drop_tables", {}), ("get_evidence", {"evidence_ids": "x", "case_id": "C2"}),
                    ("get_evidence", "{not json"), ("get_evidence", {"evidence_ids": ["EV-nope"]}))
    out = outcome(case, bad, final(good_report(evidence(case))))
    assert [c["ok"] for c in out["tool_calls"]] == [False, False, False, True]
    assert out["status"] == "VALIDATED"


def test_round_limit(case):
    out = outcome(case, *[tools_msg(("get_case_context", {}))] * 6)
    assert out["status"] == "LIMIT_EXCEEDED" and out["rounds"] == 5
    assert len(case.app_ref.state.provider.seen) == 5


@pytest.mark.parametrize("exc", [ProviderError("timeout"), ProviderError("HTTP 500")])
def test_provider_failure_is_recorded_not_success(case, exc):
    out = outcome(case, LOOKUP, exc)
    assert out["status"] == "FAILED" and out["report"] is None and str(exc) in out["error"]


def test_non_json_answer(case):
    assert outcome(case, LOOKUP, final("The board looks fine."))["status"] == "JSON_ERROR"


def test_unapproved_data_never_reaches_the_model(case):
    with Session(case.app_ref.state.engine) as s, s.begin():
        ev = s.scalars(select(SourceEvent).where(SourceEvent.entity_type == "aoi_inspections")).first()
        ev.sensitivity, ev.raw_json = "CONFIDENTIAL", '{"note":"SECRET-MARKER-123"}'
    out = outcome(case, LOOKUP, final({"summary": "s", "findings": [{"classification": "UNKNOWN", "text": "t"}]}))
    denied = out["tool_calls"][1]
    assert not denied["ok"] and "denied" in denied["error"]
    assert not any("SECRET-MARKER-123" in m for m in case.app_ref.state.provider.seen)


def test_real_case_is_refused_before_any_call(case):
    with Session(case.app_ref.state.engine) as s, s.begin():
        s.get(QualityCase, "C1").data_origin = "REAL"
    assert run(case).status_code == 422
    assert case.app_ref.state.provider.seen == []


def test_no_provider_means_503_not_mock(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    app = create_app(f"sqlite:///{tmp_path / 'np.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    c.post("/cases", json={"case_id": "C1"}, headers={"X-User": "alice"})
    assert run(c).status_code == 503
    app.state.engine.dispose()


def test_roles_and_scope(case):
    assert run(case, user="bob").status_code == 403
    assert run(case, user="dave").status_code == 403
    assert case.get("/cases/C1/investigations", headers={"X-User": "carol"}).status_code == 403


def test_retry_does_not_rerun(case):
    case.app_ref.state.provider.replies[:] = [LOOKUP, final(good_report(evidence(case)))]
    a, b = run(case, key="same-key-123"), run(case, key="same-key-123")
    assert a.json() == b.json() and len(case.app_ref.state.provider.seen) == 2
    assert len(case.get("/cases/C1/investigations", headers={"X-User": "alice"}).json()) == 1


def test_drafts_only_from_validated_run_split_by_section(case):
    good = outcome(case, LOOKUP, final(good_report(evidence(case))))
    bad = outcome(case, final("nope"))
    h = {"X-User": "alice"}

    def draft(run_id, kind="ncr"):
        return case.post(f"/cases/C1/{kind}", json={"investigation_run_id": run_id},
                         headers={**h, "Idempotency-Key": uuid.uuid4().hex})

    assert draft(bad["run_id"]).status_code == 409
    assert draft(999).status_code == 404
    assert draft(good["run_id"], "rca").status_code == 409  # no NCR/containment draft to build on yet
    doc = draft(good["run_id"]).json()
    assert doc["builder"] == f"MODEL_TEST_DOUBLE:scripted-test-double:run{good['run_id']}"
    assert doc["claims"][-1]["classification"] == "UNKNOWN" and len(doc["claims"]) == 5
    assert "HYPOTHESIS" not in {c["classification"] for c in doc["claims"]}
    assert draft(good["run_id"], "containment").status_code == 422  # model gives no containment proposals
    case.post("/cases/C1/containment", json={}, headers={**h, "Idempotency-Key": uuid.uuid4().hex})
    rca = draft(good["run_id"], "rca").json()
    assert [c["classification"] for c in rca["claims"]] == ["HYPOTHESIS", "UNKNOWN"]
    assert "UNCONFIRMED" in rca["claims"][-1]["text"]
    page = case.get("/cases/C1/ncr/1/html", headers=h).text
    assert "ClaimValidator" in page and "no AI model used" not in page
    r = case.post("/cases/C1/ncr/1/request-review", json={"reviewer_id": "bob"},
                  headers={**h, "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 200


def test_tools_are_scoped_to_the_case(case):
    with Session(case.app_ref.state.engine) as s:
        tools = EvidenceTools(s, "OTHER-CASE")
        some_id = next(iter(evidence(case)))
        assert tools.get_evidence([some_id]) == {"evidence": [], "not_found": [some_id]}


# --- transport tests for the LIVE adapter (no network) ---

class Opener:
    def __init__(self, body=None, exc=None):
        self.body, self.exc, self.requests = body, exc, []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.exc:
            raise self.exc
        return io.BytesIO(json.dumps(self.body).encode())


MSGS = [{"role": "user", "content": "synthetic"}]


def test_live_adapter_sends_tools_and_parses_reply():
    opener = Opener({"model": MODEL, "choices": [{"message": {"role": "assistant", "content": "{}"}}],
                     "usage": {"prompt_tokens": 3}})
    out = MetaProvider("k" * 24, opener=opener).chat(MSGS, [{"type": "function"}])
    sent = json.loads(opener.requests[0].data)
    assert out["usage"]["prompt_tokens"] == 3 and sent["model"] == MODEL and sent["tools"]
    assert opener.requests[0].get_header("Authorization") == "Bearer " + "k" * 24


@pytest.mark.parametrize("content", ["key is KEY-abcdefghijklmnop", "Bearer abcdefgh12345", "MODEL_API_KEY=x"])
def test_secret_in_payload_is_blocked_before_sending(content):
    opener = Opener({})
    with pytest.raises(EgressBlocked):
        MetaProvider("KEY-abcdefghijklmnop", opener=opener).chat([{"role": "user", "content": content}], [])
    assert opener.requests == []


@pytest.mark.parametrize("opener,msg", [
    (Opener(exc=HTTPError("u", 500, "x", {}, None)), "HTTP 500"),
    (Opener(exc=TimeoutError()), "timeout"),
    (Opener(exc=URLError(OSError())), "network"),
    (Opener({"model": MODEL}), "malformed"),
    (Opener({"model": "other", "choices": []}), "unexpected model"),
])
def test_live_adapter_failures_raise(opener, msg):
    with pytest.raises(ProviderError, match=msg):
        MetaProvider("k" * 24, opener=opener).chat(MSGS, [])


def test_negated_certainty_is_careful_wording_and_an_assertion_is_still_refused():
    from app.report import asserts_certainty

    for ok in ("SPI/AOI values alone do not prove causation.", "No root cause is established.",
               "The data cannot prove that the stencil caused the defects.", "This is not proven; a candidate only."):
        assert not asserts_certainty(ok), ok
    for bad in ("The root cause is stencil wear.", "The defects were caused by low paste volume.",
                "SPI data is not complete. This proves the stencil was worn.", "Definitely a stencil problem."):
        assert asserts_certainty(bad), bad
