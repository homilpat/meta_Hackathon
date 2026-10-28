"""Claim-to-source checks beyond "the cited evidence id exists" (v5 G4; G8 extends to full predicates).

A real evidence id does not make a sentence true: lots named in the text must be lots of the cited rows,
measurement units must match the cited characteristic, and facts may not rest on superseded source rows.
"""

import re

from sqlalchemy.orm import Session

from app import ncr, quality

LOT = re.compile(r"\bL\d{2}\b")
MEASUREMENT_UNITS = {"mm3", "um3", "µm3", "mm", "um", "µm"}
UNIT_OF = {"spi_measurements": "mm3"}
FACTS = ("OBSERVED", "CALCULATED", "PROPOSAL")


def check_claims(session: Session, case_id: str, claims: list[dict]) -> list[str]:
    """Every violation as '<claim_id>: reason'; empty means the claims may be stored."""
    items = ncr._evidence(session, case_id)
    lots, kinds = ncr.lot_index(items), {i["ev"]: i["type"] for i in items}
    cited = {e for c in claims for e in c.get("evidence_ids") or []}
    states = quality.current(session, case_id, cited) if cited else {}
    errors = []
    for c in claims:
        cid, ids = c.get("claim_id"), c.get("evidence_ids") or []
        named = set(LOT.findall(c.get("text", "")))
        backed = {lots.get(e) for e in ids} - {None}
        if named - backed:
            errors.append(f"{cid}: text names lot {sorted(named - backed)} but the cited evidence is from "
                          f"{sorted(backed) or 'no lot'}")
        unit = c.get("unit")
        want = {UNIT_OF[kinds[e]] for e in ids if kinds.get(e) in UNIT_OF}
        if unit in MEASUREMENT_UNITS and want and unit not in want:
            errors.append(f"{cid}: unit {unit} does not match the cited measurements ({', '.join(sorted(want))})")
        if c.get("classification") in FACTS:
            stale = sorted(e for e in ids if states.get(e, {}).get("quality_state") == "SUPERSEDED")
            if stale:
                errors.append(f"{cid}: cites superseded source rows {stale}; use the corrected version")
    return errors


def problem_definition(session: Session, case_id: str) -> dict:
    """D2 5W2H and IS / IS NOT for the case (same computation the NCR template states as claims)."""
    return ncr.problem_definition(ncr.current(ncr._evidence(session, case_id)))
