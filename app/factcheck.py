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


def lot_index(items: list[dict]) -> dict[str, str | None]:
    """evidence id -> lot, from the row itself or its panel (never guessed from the id text)."""
    panel_lot = {i["rec"]["panel_id"]: i["rec"]["lot_id"] for i in items
                 if i["type"] == "panels" and i["rec"].get("lot_id")}
    return {i["ev"]: i["rec"].get("lot_id") or panel_lot.get(i["rec"].get("panel_id")) for i in items}


def check_claims(session: Session, case_id: str, claims: list[dict]) -> list[str]:
    """Every violation as '<claim_id>: reason'; empty means the claims may be stored."""
    items = ncr._evidence(session, case_id)
    lots, kinds = lot_index(items), {i["ev"]: i["type"] for i in items}
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
    """D2 5W2H and IS / IS NOT computed from current source rows. Slots the data cannot fill are UNKNOWN."""
    items = ncr.current(ncr._evidence(session, case_id))
    lots = lot_index(items)
    aoi = [i for i in items if i["type"] == "aoi_inspections"]
    confirmed = [i for i in items if i["type"] == "human_verifications" and i["rec"]["result"] == "DEFECT_CONFIRMED"]
    boards = [i for i in items if i["type"] == "boards"]
    inspected = {(i["rec"]["panel_id"], i["rec"]["board_id"]) for i in aoi}
    uninspected = [b for b in boards if (b["rec"]["panel_id"], b["rec"]["board_id"]) not in inspected]
    all_lots = sorted({i["rec"]["lot_id"] for i in items if i["type"] == "lots"})
    is_lots = sorted({lots[i["ev"]] for i in confirmed} - {None})
    versions: dict[str, int] = {}
    for i in items:
        versions[i["type"]] = max(versions.get(i["type"], 0), i["version"])

    def slot(value, ids, known=True):
        return {"value": value, "evidence_ids": ids, "status": "KNOWN" if known and value not in (None, []) else
                "UNKNOWN"}

    times = sorted(i["rec"]["event_time"] for i in confirmed)
    return {
        "what": slot(f"{len(confirmed)} human-confirmed defects" if confirmed else None, [i["ev"] for i in confirmed]),
        "where": slot(is_lots, [i["ev"] for i in confirmed], bool(all_lots)),
        "when": slot({"first": times[0], "last": times[-1]} if times else None, [i["ev"] for i in confirmed]),
        "who_detected": slot("AOI inspection, then human verification" if aoi else None, [i["ev"] for i in aoi[:1]]),
        "how_many": slot({"confirmed": len(confirmed), "denominator_aoi_inspections": len(aoi),
                          "boards_without_aoi": len(uninspected)} if aoi else None, [i["ev"] for i in aoi]),
        "is": slot({"lots": is_lots}, [i["ev"] for i in confirmed], bool(all_lots)),
        "is_not": slot({"lots": sorted(set(all_lots) - set(is_lots))},
                       [i["ev"] for i in items if i["type"] == "lots" and i["rec"]["lot_id"] not in is_lots],
                       bool(all_lots)),
        "unknown_scope": [f"board {b['rec']['panel_id']}/{b['rec']['board_id']} has no AOI record"
                          for b in uninspected],
        "effective_source_versions": versions,
        "note": "Computed from current source rows. A count is a source-DB match, not physical ground truth.",
    }
