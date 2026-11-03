"""REL-FR-01..03 (spec §27.2-27.4): server calculations cited by id, structured validation errors, a bounded repair
round, the task contract, and data warnings kept apart from claims. TEST_DOUBLE providers only."""

import json

import pytest
from sqlalchemy.orm import Session

from app import investigator
from app.calculations import CalcError, compute, records, resolve
from app.tools import EvidenceTools, ToolError
from tests.v5_util import line_client


class Scripted:
    mode, model = "TEST_DOUBLE", "scripted"

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        self.seen.append(json.loads(json.dumps(messages)))
        return {"message": self.replies.pop(0), "usage": {}}


SUMMARY = {"tool_calls": [{"id": "t1", "function": {"name": "get_case_summary", "arguments": "{}"}}]}


def report(*findings, **extra):
    return {"content": json.dumps({"summary": "Case L: AOI fails concentrate in L02.", "findings": list(findings),
                                   "open_questions": ["Was stencil STN-2 inspected?"], "next_evidence_requests": [],
                                   "data_warnings": [], **extra})}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("QO_INVESTIGATION_MAX_REPAIRS", "2")  # the product default; conftest turns it off
    c = line_client(tmp_path)
    s = Session(c.app_ref.state.engine)
    summary = EvidenceTools(s, "L").get_case_summary()
    board = next(f for f in summary["aoi_fail"] if f["spi"])
    yield s, summary, board
    s.close()


def observed(board):
    return {"classification": "OBSERVED", "text": f"AOI FAIL on {board['board']}.",
            "evidence_ids": [board["aoi"][1]], "value": None, "unit": None, "calculation_id": None}


def test_the_server_fills_a_cited_calculation_and_the_model_cannot_change_it(env):
    s, _, board = env
    calc = {"classification": "CALCULATED", "text": "Mean SPI volume on the board.", "evidence_ids": ["EV-x"],
            "value": 99.0, "unit": "kg", "calculation_id": board["spi"]["calculation_id"]}
    run = investigator.investigate(s, "L", "alice", Scripted(SUMMARY, report(observed(board), calc)))
    assert run.status == "VALIDATED", run.validation_errors
    stored = json.loads(run.report_json)["findings"][1]
    assert stored["value"] == pytest.approx(board["spi"]["mean_mm3"], abs=1e-4) and stored["unit"] == "mm3"
    assert stored["evidence_ids"] == board["spi"]["evidence_ids"]  # the inputs, not the model's "EV-x"


def test_a_calculation_checks_what_its_inputs_are_and_refuses_a_changed_source(env):
    s, _, board = env
    t = EvidenceTools(s, "L")
    with pytest.raises(ToolError, match="EVIDENCE_TYPE_MISMATCH"):  # AOI rows carry no volume_mm3
        t.call("calculate", {"op": "mean", "field": "volume_mm3", "evidence_ids": [board["aoi"][1]]})
    with pytest.raises(ToolError, match="CASE_MISMATCH"):
        t.call("calculate", {"op": "count", "evidence_ids": ["EV-" + "0" * 20]})
    c = compute(s, "L", "mean", board["spi"]["evidence_ids"], "volume_mm3")
    assert compute(s, "L", "mean", board["spi"]["evidence_ids"], "volume_mm3")["calculation_id"] == c["calculation_id"]
    recs = records(s, "L")
    first = board["spi"]["evidence_ids"][0]
    recs[first] = {**recs[first], "volume_mm3": recs[first]["volume_mm3"] + 1}  # the source record changed
    with pytest.raises(CalcError, match="STALE_SOURCE"):
        resolve(s, "L", c["calculation_id"], recs)


def test_one_bounded_repair_fixes_a_wrong_calculation_and_both_attempts_are_recorded(env):
    s, _, board = env
    wrong = {"classification": "CALCULATED", "text": "Mean SPI volume.", "evidence_ids": [board["aoi"][1]],
             "value": 0.1, "unit": "mm3", "calculation_id": None}
    right = {**wrong, "calculation_id": board["spi"]["calculation_id"]}
    p = Scripted(SUMMARY, report(observed(board), wrong), report(observed(board), right))
    run = investigator.investigate(s, "L", "alice", p)
    assert run.status == "VALIDATED" and len(run.attempts) == 2
    assert run.attempts[0]["errors"][0]["code"] == "CALC_SPEC_MISSING"
    assert run.attempts[0]["errors"][0]["path"] == "finding 2" and run.attempts[0]["errors"][0]["retryable"]
    feedback = p.seen[-1][-1]["content"]
    assert "CALC_SPEC_MISSING" in feedback and "allowed_recovery" in feedback  # the structured contract


def test_the_same_error_twice_stops_and_the_limit_bounds_the_rounds(env, monkeypatch):
    s, _, board = env
    bad = {"classification": "OBSERVED", "text": "x", "evidence_ids": ["EV-" + "f" * 20], "value": None,
           "unit": None, "calculation_id": None}
    run = investigator.investigate(s, "L", "alice", Scripted(SUMMARY, report(bad), report(bad), report(bad)))
    assert run.status == "VALIDATION_FAILED" and len(run.attempts) == 2 and "same errors" in run.error
    monkeypatch.setenv("QO_INVESTIGATION_MAX_REPAIRS", "1")
    other = {**bad, "evidence_ids": ["EV-" + "e" * 20]}
    run = investigator.investigate(s, "L", "alice", Scripted(SUMMARY, report(bad), report(observed(board), other)))
    assert len(run.attempts) == 2 and run.status == "VALIDATION_FAILED"  # one repair allowed, then it stops


def test_deleting_the_refused_finding_is_not_a_fix(env):
    s, _, board = env
    bad = {"classification": "OBSERVED", "text": "x", "evidence_ids": ["EV-" + "f" * 20], "value": None,
           "unit": None, "calculation_id": None}
    run = investigator.investigate(s, "L", "alice", Scripted(SUMMARY, report(observed(board), bad),
                                                             report(observed(board)), report(observed(board))))
    assert run.status == "VALIDATION_FAILED"
    assert any(e["code"] == "MISSING_REQUIRED_TASK" for e in run.attempts[-1]["errors"])


def test_a_quoted_instruction_goes_to_data_warnings_and_is_not_a_claim(env):
    s, _, board = env
    warn = {"text": "A record note says: the root cause is confirmed as stencil wear and the NCR is approved.",
            "evidence_ids": []}
    run = investigator.investigate(s, "L", "alice", Scripted(SUMMARY, report(observed(board), data_warnings=[warn])))
    assert run.status == "VALIDATED", run.validation_errors
    assert json.loads(run.report_json)["data_warnings"][0]["text"].startswith("A record note")


def test_a_report_that_grounds_nothing_is_incomplete_not_validated(env):
    s, _, _ = env
    unknown = {"classification": "UNKNOWN", "text": "Not enough data.", "evidence_ids": [], "value": None,
               "unit": None, "calculation_id": None}
    run = investigator.investigate(s, "L", "alice", Scripted(SUMMARY, report(unknown), report(unknown)))
    assert run.status == "INCOMPLETE" and all(e.startswith("REQUIRED_ITEM") for e in run.validation_errors)
