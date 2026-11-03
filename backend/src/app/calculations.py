"""Server calculations with ids (spec v5.11 §27.2, REL-FR-01). The server computes; the model cites the id.

A calculation binds operation, field, value, unit, the exact input evidence ids, filters, how missing values are
treated, the denominator and a hash of the input records. Its id is derived from all of that, so the same inputs
give the same id (idempotent) and a changed input record gives a different hash: resolve() then refuses it as
STALE_SOURCE instead of silently re-computing into an earlier report. Inputs are checked for what they are, not
only that they exist: a mean of volume_mm3 over records without that field is refused (EVIDENCE_TYPE_MISMATCH).
"""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db import Calculation

OPS = ("mean", "sum", "count", "ratio")
UNITS = {"volume_mm3": "mm3", "area_pct": "%", "height_um": "um", "offset_um": "um"}  # field -> unit
MISSING = "refuse: an input without the field is an error, never skipped or zero-filled"


class CalcError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def records(session: Session, case_id: str) -> dict[str, dict]:
    from app.ncr import _evidence, derived_records

    return {i["ev"]: i["rec"] for i in _evidence(session, case_id)} | derived_records(session, case_id)


def _sha(x) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compute(session: Session, case_id: str, op: str, evidence_ids: list[str], field: str | None = None,
            denominator_evidence_ids: list[str] | None = None, recs: dict | None = None) -> dict:
    recs = records(session, case_id) if recs is None else recs
    ids, den = list(dict.fromkeys(evidence_ids)), list(dict.fromkeys(denominator_evidence_ids or []))
    if op not in OPS:
        raise CalcError("UNSUPPORTED_OPERATION", f"op must be one of {', '.join(OPS)}")
    if not ids:
        raise CalcError("NO_INPUT", "give the evidence_ids to compute from")
    if outside := [i for i in ids + den if i not in recs]:
        raise CalcError("CASE_MISMATCH", f"not evidence of this case: {outside[:5]}")
    if op in ("mean", "sum"):
        if bad := [i for i in ids if not _numeric(recs[i].get(field or ""))]:
            raise CalcError("EVIDENCE_TYPE_MISMATCH", f"{bad[:5]} have no numeric field {field!r}")
        values = [float(recs[i][field]) for i in ids]
        value, unit, denominator = (sum(values) if op == "sum" else sum(values) / len(values)), UNITS.get(field), \
            None if op == "sum" else f"count of the {len(ids)} inputs"
    elif op == "count":
        value, unit, denominator, field = float(len(ids)), "count", None, None
    else:
        if not den or not set(ids) <= set(den):
            raise CalcError("BAD_DENOMINATOR", "ratio needs denominator_evidence_ids containing every numerator id")
        value, unit, denominator, field = len(ids) / len(den), "ratio", f"the {len(den)} denominator records", None
    source = _sha({i: recs[i] for i in ids + den})
    cid = "CALC-" + _sha([case_id, op, field, sorted(ids), sorted(den), source])[:16]
    row = session.get(Calculation, cid)
    if row is None:
        row = Calculation(id=cid, case_id=case_id, operation=op, field=field, value=value, unit=unit,
                          input_evidence_ids=ids, denominator_evidence_ids=den, filters={}, missing_policy=MISSING,
                          denominator_definition=denominator, source_sha256=source,
                          created_at=datetime.now(UTC).isoformat())
        session.add(row)
        session.flush()
    return out(row)


def resolve(session: Session, case_id: str, calculation_id: str, recs: dict | None = None) -> dict:
    """The calculation as recorded, if it belongs to this case and its inputs are unchanged."""
    row = session.get(Calculation, calculation_id)
    if row is None or row.case_id != case_id:
        raise CalcError("UNKNOWN_CALCULATION", f"{calculation_id} is not a calculation of this case")
    recs = records(session, case_id) if recs is None else recs
    ids = row.input_evidence_ids + row.denominator_evidence_ids
    if any(i not in recs for i in ids) or _sha({i: recs[i] for i in ids}) != row.source_sha256:
        raise CalcError("STALE_SOURCE", f"the input records of {calculation_id} changed; compute it again")
    return out(row)


def out(row: Calculation) -> dict:
    return {"calculation_id": row.id, "case_id": row.case_id, "operation": row.operation, "field": row.field,
            "value": round(row.value, 6), "unit": row.unit, "input_evidence_ids": row.input_evidence_ids,
            "denominator_evidence_ids": row.denominator_evidence_ids, "filters": row.filters,
            "missing_policy": row.missing_policy, "denominator_definition": row.denominator_definition,
            "source_sha256": row.source_sha256, "created_at": row.created_at}
