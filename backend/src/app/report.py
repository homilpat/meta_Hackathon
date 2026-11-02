"""InvestigationReport schema and the independent ClaimValidator (never trusts the model's math)."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.ncr import _evidence, derived_records

CAUSAL_CERTAINTY = re.compile(
    r"(?i)\b(root cause (is|was|has been)|(is|was|are|were) caused by|caused by|proves?|proven|"
    r"definitely|certainly|confirmed (as )?(the )?(root )?cause)\b")
EVIDENCE_REF = re.compile(r"\b(?:EV-[0-9a-f]{20}|PRED-\d+|XAI-\d+)\b")
SHAP_AS_CAUSE = re.compile(r"(?i)\b(shap|attribution|contribution)s?\b[^.]*\b(caused|causes|due to|"
                           r"responsible for|led to|because)\b")
URL = re.compile(r"(?i)https?://|www\.")
PRECEDENT_REF = re.compile(r"\bH\d{2}\b")
TOLERANCE = 1e-4


class Calc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["mean", "sum", "count", "ratio"]
    field: str | None = None
    numerator_evidence_ids: list[str] = []
    denominator_evidence_ids: list[str] = []


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no root_cause / source / url fields can sneak in
    classification: Literal["OBSERVED", "CALCULATED", "HYPOTHESIS", "UNKNOWN"]
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = []
    value: float | None = None
    unit: str | None = None
    calc: Calc | None = None


class NextCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = []
    precedent_ids: list[str] = []
    discriminates: list[str] = []


class InvestigationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=800)
    findings: list[Finding] = Field(min_length=1, max_length=30)
    open_questions: list[str] = []
    next_evidence_requests: list[NextCheck] = Field(default=[], max_length=8)


def _expected(calc: Calc, finding: Finding, records: dict[str, dict]) -> float:
    if calc.op == "count":
        return float(len(set(finding.evidence_ids)))
    if calc.op == "ratio":
        num, den = set(calc.numerator_evidence_ids), set(calc.denominator_evidence_ids)
        if not den or not num <= den or not (num | den) <= set(finding.evidence_ids):
            raise ValueError("ratio needs numerator within denominator, both cited in evidence_ids")
        return len(num) / len(den)
    values = []
    for ev in finding.evidence_ids:
        v = records[ev].get(calc.field or "")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise TypeError(f"{ev} has no numeric field {calc.field!r}")
        values.append(float(v))
    return sum(values) if calc.op == "sum" else sum(values) / len(values)


def validate_report(session: Session, case_id: str, report: InvestigationReport,
                    precedents: list[dict] | None = None) -> list[str]:
    """Return every rule violation; an empty list means the report may be used.

    precedents: the eligible precedents the model was shown (None = history OFF, none may be cited)."""
    from app.history import recommends_failed_action
    allowed = {p["historical_case_id"] for p in precedents or []}
    records = {i["ev"]: i["rec"] for i in _evidence(session, case_id)} | derived_records(session, case_id)
    errors: list[str] = []
    for n, f in enumerate(report.findings, 1):
        tag = f"finding {n}"
        if missing := sorted(set(f.evidence_ids) - set(records)):
            errors.append(f"{tag}: unknown evidence_id {missing}")
            continue
        if f.classification in ("OBSERVED", "CALCULATED") and not f.evidence_ids:
            errors.append(f"{tag}: {f.classification} needs evidence_ids")
        if f.value is not None and not f.evidence_ids:
            errors.append(f"{tag}: numeric value needs evidence_ids")
        if f.classification == "CALCULATED":
            if f.calc is None or f.value is None:
                errors.append(f"{tag}: CALCULATED needs calc and value")
            else:
                try:
                    want = _expected(f.calc, f, records)
                    if abs(f.value - want) > TOLERANCE * (1 + abs(want)):
                        errors.append(f"{tag}: value {f.value} != recomputed {round(want, 6)}")
                except (ValueError, TypeError) as exc:
                    errors.append(f"{tag}: {exc}")
        elif f.calc is not None:
            errors.append(f"{tag}: calc only allowed on CALCULATED")
        errors += _text_errors(tag, f.text, records)
        if f.classification in ("OBSERVED", "CALCULATED") and PRECEDENT_REF.search(f.text):
            errors.append(f"{tag}: a precedent is not evidence about this case; cite it in a next check")
    errors += _text_errors("summary", report.summary, records)
    for n, c in enumerate(report.next_evidence_requests, 1):
        tag = f"next check {n}"
        if not c.evidence_ids:  # a recommendation rests on this case's data; precedents alone only support it
            errors.append(f"{tag}: needs evidence_ids from this case")
        if missing := sorted(set(c.evidence_ids) - set(records)):
            errors.append(f"{tag}: unknown evidence_id {missing}")
        texts = f"{c.check} {c.reason}"
        cited = set(c.precedent_ids) | set(PRECEDENT_REF.findall(texts))
        if bad := sorted(cited - allowed):
            errors.append(f"{tag}: precedent {bad} was not retrieved as eligible for this case")
        if hit := recommends_failed_action(texts, precedents or []):
            errors.append(f"{tag}: recommends {hit}, which failed before")
        errors += _text_errors(tag, texts, records)
    for t in [report.summary, *(f.text for f in report.findings)]:
        if bad := sorted(set(PRECEDENT_REF.findall(t)) - allowed):
            errors.append(f"precedent {bad} cited but not eligible/retrieved")
    return errors


NEGATION = re.compile(r"(?i)\b(no|not|never|cannot|without|nor|neither)\b|n't\b")


def asserts_certainty(text: str) -> bool:
    """A causal-certainty phrase counts unless the words just before it in the same sentence negate it: "SPI values
    alone do not prove causation" and "No root cause is established" are the careful wording the prompt asks for
    (LIVE 2026-11-02: both were refused before this check, in 4 of 4 server-rejected reports)."""
    for m in CAUSAL_CERTAINTY.finditer(text):
        before = re.split(r"[.;!?]", text[:m.start()])[-1].split()[-6:]
        if not NEGATION.search(" ".join(before)):
            return True
    return False


def _text_errors(tag: str, text: str, records: dict[str, dict]) -> list[str]:
    errors = []
    if asserts_certainty(text):
        errors.append(f"{tag}: causal certainty is not allowed")
    if SHAP_AS_CAUSE.search(text):
        errors.append(f"{tag}: SHAP attribution is not causal evidence")
    if URL.search(text):
        errors.append(f"{tag}: external source reference is not allowed")
    errors += [f"{tag}: text cites nonexistent {ref}" for ref in sorted(set(EVIDENCE_REF.findall(text)) - set(records))]
    return errors
