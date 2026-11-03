"""The customer's statement in the investigation (2026-11-03): the summary carries it (masked when protected), it
is cited only as REPORTED, and an internal OBSERVED finding cannot rest on it. TEST_DOUBLE only."""

import json

from sqlalchemy.orm import Session

from app.egress import Masker
from app.report import InvestigationReport, validate_report
from app.tools import EvidenceTools
from tests.test_masked_investigation import SECRET_LOT, protected_case  # noqa: F401 (fixture)


def report(classification, ids):
    return InvestigationReport.model_validate({"summary": "s", "open_questions": ["q"], "next_evidence_requests": [],
                                              "data_warnings": [], "findings": [
        {"classification": classification, "text": "The customer reports this LOT.", "evidence_ids": ids}]})


def test_the_summary_carries_the_customer_statement_masked(protected_case):  # noqa: F811
    c, case, ids = protected_case
    with Session(c.app.state.engine) as s:
        summary = EvidenceTools(s, case, masker=Masker()).get_case_summary()
    rows = {r[0]: r for r in summary["customer_reports"]}
    assert rows["lot"][2] in ids and SECRET_LOT not in json.dumps(summary)  # the value goes as a token
    assert "REPORTED" in summary["legend"]


def test_reported_only_for_customer_statements(protected_case):  # noqa: F811
    c, case, ids = protected_case
    with Session(c.app.state.engine) as s:
        assert validate_report(s, case, report("REPORTED", ids[:1])) == []
        errs = validate_report(s, case, report("OBSERVED", ids[:1]))
        assert any("classify them REPORTED" in e for e in errs)  # never promoted to an internal fact
        assert any("REPORTED cites only" in e for e in validate_report(s, case, report("REPORTED", [])))


def test_a_next_check_may_name_the_customer_statement(protected_case):  # noqa: F811
    c, case, ids = protected_case
    r = InvestigationReport.model_validate({"summary": "s", "open_questions": [], "data_warnings": [], "findings": [
        {"classification": "UNKNOWN", "text": "Internal records for this LOT are not in the case."}],
        "next_evidence_requests": [{"check": "Pull the inspection records of the reported LOT", "reason": "r",
                                    "evidence_ids": ids[:1], "precedent_ids": [], "discriminates": ["H1"]}]})
    with Session(c.app.state.engine) as s:
        assert not [e for e in validate_report(s, case, r) if "unknown evidence_id" in e]
