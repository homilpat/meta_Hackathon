"""The one structured-claim validation service (v5 G4, extended in G8).

Every document claim — template, author, model-derived or edited in Docs — goes through `validate`. A real
evidence id does not make a sentence true, so besides "the id exists" it checks, per claim:
  - the draft rules of ncr.validate_claims (classification, evidence for facts and numbers, no "was executed" /
    "root cause is confirmed" in a draft) and the text rules the model report validator uses (causal certainty,
    SHAP as cause, URLs, nonexistent ids);
  - lots named in the text against the lots of the cited rows; units against the cited characteristic;
  - superseded source rows (BLOCK for facts) and unsuitable evidence (WARN);
  - a server recomputation of the value from the cited rows when the claim's shape allows it (mean SPI volume,
    AOI FAIL share in %, "x of y AOI inspections" counts), and that the text states the claim's value;
  - case references (ACT-n, H-n, EFF-n, DOC:number:rev): containment stated as done needs an executed action,
    a cause stated as confirmed needs a CONFIRMED hypothesis, a cited document must be released, in effect,
    for this site and readable by the caller.
Issues carry a code and BLOCK / WARN / INFO. Regex rules catch surface patterns only; they do not make every
sentence true, which is why reviewers still approve.
"""

import re
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ncr, quality, registry, spc
from app.db import Action, CauseHypothesis, EffectivenessResult, Evidence, ProcessContext

RULES_VERSION = "v5.5-g8.3"  # g8.3: SPC centre line / LCL / UCL and Cpk recomputed
LOT = re.compile(r"\bL\d{2}\b")
MEASUREMENT_UNITS = {"mm3", "um3", "µm3", "mm", "um", "µm"}
UNIT_OF = {"spi_measurements": "mm3"}
FACTS = ("OBSERVED", "CALCULATED", "PROPOSAL")
REF = re.compile(r"^(ACT|H|EFF)-(\d+)$|^DOC:([A-Z0-9\-]+):(\d+)$")
EXECUTED_WORDS = re.compile(r"(?i)\b(executed|held|quarantined|contained|completed|implemented|stopped)\b")
CAUSE_WORDS = re.compile(r"(?i)\b(root cause|confirmed cause|caused by)\b")
INJECTION = re.compile(r"(?i)ignore (all|any|previous|the) (rules|instructions)|approve_document|system prompt")
OF_AOI = re.compile(r"(\d+)(?: confirmed)? of (\d+) AOI inspections")
# the AI writes drafts in Korean with these fixed forms (ncr.WORDING_PROMPT): "AOI 검사 47건 중 확정 22건"
OF_AOI_KO = re.compile(r"AOI 검사 (\d+)건 중 (확정 )?(\d+)건")
SPC_LIMIT = re.compile(r"(?<![A-Za-z])(centre line|중심선|LCL|UCL)(?![A-Za-z])")
CONFIRMED = re.compile(r"confirmed|확정")
DONE_ACTION = ("EXECUTED", "INDEPENDENTLY_VERIFIED", "RELEASED")


def _issue(cid, code: str, message: str, severity: str = "BLOCK") -> dict:
    return {"claim_id": cid, "code": code, "severity": severity, "message": f"{cid}: {message}"}


def text_numbers(text: str, unit: str | None) -> list[float]:
    """Numbers the text attaches to the claim's unit ("2.1%", "0.104 mm3"); counts are checked via OF_AOI."""
    if not unit or unit == "count":
        return []
    return [float(n) for n in re.findall(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*{re.escape(unit)}(?!\w)", text)]


def recompute(claim: dict, rows: list[dict]) -> tuple[dict | None, float | None]:
    """(predicate, expected value) from the cited rows, or (None, None) when the shape is not recomputable."""
    unit, text = claim.get("unit"), claim.get("text", "")
    types = {r["type"] for r in rows}
    if rows and types == {"spi_measurements"} and unit in ("mm3", "Cpk"):
        # SPC statistics use the monitor's own formulas over the cited rows, grouped into board subgroups
        sub = spc.subgroups([(r["rec"], None) for r in rows])
        named = set(SPC_LIMIT.findall(text))
        if unit == "Cpk":
            return ({"op": "cpk", "entity": "spi_measurements", "subgroups": len(sub),
                     "spec": [spc.LSL, spc.USL]}, spc.cpk(sub))
        if len(named) > 1:
            return None, None  # one claim, one statistic
        if named:
            key = {"centre line": "cl", "중심선": "cl", "LCL": "lcl", "UCL": "ucl"}[named.pop()]
            return ({"op": "spc_limit", "limit": key, "entity": "spi_measurements", "subgroups": len(sub)},
                    spc.limits(sub)[key])
        return ({"op": "mean", "entity": "spi_measurements", "field": "volume_mm3", "n": len(rows)},
                mean(r["rec"]["volume_mm3"] for r in rows))
    aoi = [r for r in rows if r["type"] == "aoi_inspections"]
    if unit == "%" and aoi and types == {"aoi_inspections"}:
        fail = sum(r["rec"]["result"] == "FAIL" for r in aoi)
        return ({"op": "ratio", "entity": "aoi_inspections", "numerator": "result=FAIL", "denominator": len(aoi)},
                100 * fail / len(aoi))
    if unit == "count" and types == {"human_verifications"} and CONFIRMED.search(text):
        return ({"op": "count", "entity": "human_verifications", "where": "result=DEFECT_CONFIRMED"},
                float(sum(r["rec"]["result"] == "DEFECT_CONFIRMED" for r in rows)))
    if unit == "count" and aoi and (m := OF_AOI.search(text) or OF_AOI_KO.search(text)):
        confirmed, n_of = ("confirmed" in m.group(0), (int(m.group(1)), int(m.group(2)))) if m.re is OF_AOI \
            else (bool(m.group(2)), (int(m.group(3)), int(m.group(1))))
        if confirmed:
            humans = [r for r in rows if r["type"] == "human_verifications"]
            num = sum(r["rec"]["result"] == "DEFECT_CONFIRMED" for r in humans) if humans else n_of[0]
        else:
            num = sum(r["rec"]["result"] == "FAIL" for r in aoi)
        pred = {"op": "count", "entity": "aoi_inspections", "numerator": num, "denominator": len(aoi)}
        stated = n_of
        expected = float(len(aoi)) if claim.get("value") == stated[1] else float(num)
        pred["text_numbers"] = stated
        return pred, expected
    return None, None


def _ref_issues(session: Session, case_id: str, c: dict, refs: list[re.Match], role: str | None,
                site: str | None) -> list[dict]:
    cid, text, out = c.get("claim_id"), c.get("text", ""), []
    acts = [int(m.group(2)) for m in refs if m.group(1) == "ACT"]
    hyps = [int(m.group(2)) for m in refs if m.group(1) == "H"]
    from app import actions, causes

    for aid in acts:
        a = session.get(Action, aid)
        if a is None or a.case_id != case_id:
            out.append(_issue(cid, "UNKNOWN_REF", f"ACT-{aid} is not an action of this case"))
    for hid in hyps:
        h = session.get(CauseHypothesis, hid)
        if h is None or h.case_id != case_id:
            out.append(_issue(cid, "UNKNOWN_REF", f"H-{hid} is not a hypothesis of this case"))
    for m in refs:
        if m.group(1) == "EFF":
            r = session.get(EffectivenessResult, int(m.group(2)))
            if r is None or r.case_id != case_id:
                out.append(_issue(cid, "UNKNOWN_REF", f"EFF-{m.group(2)} is not a result of this case"))
        elif m.group(3):
            st = registry.revision_state(session, m.group(3), int(m.group(4)))  # site checked next, with a reason
            row = st["row"]
            if row is not None and site and row.site not in ("*", site):
                st = {**st, "in_effect": False, "reason": f"{m.group(3)} is for site {row.site}, not {site}"}
            if not st["in_effect"]:
                out.append(_issue(cid, "DOCUMENT_NOT_CITABLE", st["reason"] or "document not in effect"))
            elif role and not registry.visible(row, role):
                out.append(_issue(cid, "DOCUMENT_NOT_CITABLE", f"{m.group(3)} is not readable by {role}"))
    if c.get("classification") in ("OBSERVED", "CALCULATED") and EXECUTED_WORDS.search(text):
        done = [a for a in acts if session.get(Action, a) and actions.status(session, a) in DONE_ACTION]
        if not done:
            out.append(_issue(cid, "EXECUTION_UNSUPPORTED", "states an action as done but cites no executed "
                              "action (ACT-n with status EXECUTED or later)"))
    if c.get("classification") in ("OBSERVED", "CALCULATED") and CAUSE_WORDS.search(text) and not any(
            causes.status(session, h) == "CONFIRMED" for h in hyps if session.get(CauseHypothesis, h)):
        out.append(_issue(cid, "CAUSE_UNSUPPORTED", "states a cause as established but cites no CONFIRMED "
                              "hypothesis (H-n)"))
    return out


def validate(session: Session, case_id: str, claims: list[dict], role: str | None = None) -> dict:
    """{"issues": [...], "predicates": {claim_id: predicate}, "result": PASS|WARN|BLOCK, "rules_version"}."""
    from app.report import _text_errors

    items = ncr._evidence(session, case_id)
    by_ev = {i["ev"]: i for i in items}
    lots, kinds = ncr.lot_index(items), {i["ev"]: i["type"] for i in items}
    known = set(session.scalars(select(Evidence.evidence_id).where(Evidence.case_id == case_id)))
    records = {i["ev"]: i["rec"] for i in items} | ncr.derived_records(session, case_id)
    site = session.scalar(select(ProcessContext.site).where(ProcessContext.case_id == case_id))
    cited = {e for c in claims for e in c.get("evidence_ids") or [] if e in known}
    states = quality.current(session, case_id, cited) if cited else {}
    issues, predicates = [], {}
    for c in claims:
        cid, ids, text = c.get("claim_id"), c.get("evidence_ids") or [], c.get("text", "")
        refs = [m for e in ids if (m := REF.match(e))]
        ev_ids = [e for e in ids if not REF.match(e)]
        try:
            ncr.validate_claims([{**c, "evidence_ids": ids}], known | {m.group(0) for m in refs})
        except ValueError as exc:
            issues.append({"claim_id": cid, "code": "CLAIM_RULE", "severity": "BLOCK", "message": str(exc)})
            continue
        issues += [_issue(cid, "TEXT_RULE", e.split(": ", 1)[1]) for e in _text_errors(cid, text, set(records))]
        if INJECTION.search(text):
            issues.append(_issue(cid, "INSTRUCTION_IN_TEXT", "claim text contains an instruction to the system"))
        named = set(LOT.findall(text))
        backed = {lots.get(e) for e in ev_ids} - {None}
        if named - backed:
            issues.append(_issue(cid, "LOT_MISMATCH", f"text names lot {sorted(named - backed)} but the cited "
                                 f"evidence is from {sorted(backed) or 'no lot'}"))
        unit = c.get("unit")
        want = {UNIT_OF[kinds[e]] for e in ev_ids if kinds.get(e) in UNIT_OF}
        if unit in MEASUREMENT_UNITS and want and unit not in want:
            issues.append(_issue(cid, "UNIT_MISMATCH",
                                 f"unit {unit} does not match the cited measurements ({', '.join(sorted(want))})"))
        if c.get("classification") in FACTS:
            stale = sorted(e for e in ev_ids if states.get(e, {}).get("quality_state") == "SUPERSEDED")
            if stale:
                issues.append(_issue(cid, "SUPERSEDED_SOURCE", f"cites superseded source rows {stale}; "
                                     "use the corrected version"))
            weak = sorted(e for e in ev_ids if states.get(e, {}).get("quality_state") in ("SUSPECT", "CONFLICTED"))
            if weak:
                issues.append(_issue(cid, "EVIDENCE_QUALITY", f"cites {weak} whose quality is SUSPECT/CONFLICTED; "
                                     "annotate before approval", "WARN"))
        value = c.get("value")
        if value is not None:
            # The value must appear in the text. Other numbers written with the claim's unit are not recomputed:
            # a person's list of values in one unit may be legitimate, but a wrong "2.1%" next to the right value
            # looks the same to a regex, so they are flagged for review (G8-A). Templates state one value per claim.
            anywhere = [float(n) for n in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.]\d)", text)]
            said = text_numbers(text, c.get("unit"))
            wrong = [n for n in said if abs(n - value) >= 1e-9]
            if said and not any(abs(n - value) < 1e-9 for n in anywhere):
                issues.append(_issue(cid, "TEXT_VALUE_MISMATCH", f"text states {', '.join(f'{n:g}' for n in said)} "
                                     f"{c.get('unit')} but the claim value is {value:g}"))
            elif wrong:
                issues.append(_issue(cid, "TEXT_EXTRA_VALUE", f"text also states {', '.join(f'{n:g}' for n in wrong)} "
                                     f"{c.get('unit')}, which the server did not recompute; check against the "
                                     "source or split the claim", "WARN"))
            pred, expected = recompute(c, [by_ev[e] for e in ev_ids if e in by_ev])
            if pred is None:
                predicates[cid] = {"op": "NOT_RECOMPUTED", "reason": "claim shape has no server recomputation"}
            else:
                decimals = len(f"{value:g}".split(".")[1]) if "." in f"{value:g}" else 0
                predicates[cid] = {**pred, "expected": round(expected, max(decimals, 0))}
                # one unit of the stated last digit absorbs rounding of intermediate means; counts must be exact
                if abs(expected - value) > (10 ** -decimals if decimals else 0) + 1e-9:
                    issues.append(_issue(cid, "VALUE_MISMATCH", f"value {value:g} != server recomputation "
                                         f"{round(expected, max(decimals, 1)):g} from the cited rows"))
                if (tn := pred.get("text_numbers")) and (tn[0] != pred["numerator"] or tn[1] != pred["denominator"]):
                    issues.append(_issue(cid, "VALUE_MISMATCH", f"text says {tn[0]} of {tn[1]}; the cited rows give "
                                         f"{pred['numerator']} of {pred['denominator']}"))
        issues += _ref_issues(session, case_id, c, refs, role, site)
    result = "BLOCK" if any(i["severity"] == "BLOCK" for i in issues) else (
        "WARN" if any(i["severity"] == "WARN" for i in issues) else "PASS")
    return {"result": result, "issues": issues, "predicates": predicates, "rules_version": RULES_VERSION}


def check_claims(session: Session, case_id: str, claims: list[dict], role: str | None = None) -> list[str]:
    """BLOCK messages only (what refuses storage); WARN issues are shown at validation, not here."""
    return [i["message"] for i in validate(session, case_id, claims, role)["issues"] if i["severity"] == "BLOCK"]


def problem_definition(session: Session, case_id: str) -> dict:
    """D2 5W2H and IS / IS NOT for the case (same computation the NCR template states as claims)."""
    return ncr.problem_definition(ncr.current(ncr._evidence(session, case_id)))
