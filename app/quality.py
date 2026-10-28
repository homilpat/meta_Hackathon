"""EvidenceQualityAssessment (v5 structure B): does evidence exist AND is it fit for the use it is put to.

Rule states come only from flags the system already records (source version, validity, data-quality issues,
derived vs measured). Anything those flags cannot establish stays UNVERIFIED, never silently VALID.
Calibration and time synchronisation are not in the synthetic sources, so the rules record them as NOT_IN_SOURCE.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import DataQualityIssue, Evidence, EvidenceQuality, SourceAsset, SourceEvent

STATES = ("VALID", "UNVERIFIED", "SUSPECT", "CONFLICTED", "SUPERSEDED")
RANK = {s: i for i, s in enumerate(STATES)}
CONFLICT_CODES = {"LOT_MISMATCH", "INVALID_REVISION_LINK", "INSPECTION_DISAGREEMENT"}
SUSPECT_CODES = {"DUPLICATE_ROW", "DUPLICATE_INSPECTION", "MISSING_PARENT", "MISSING_LOT",
                 "MISSING_AOI_REFERENCE", "MISSING_HUMAN_REFERENCE"}
USES = ("OBSERVATION", "ROOT_CAUSE", "EFFECTIVENESS")


def suitable(state: str, use: str) -> str:
    """PASS / WARN / BLOCK for one evidence state in one use. Only VALID may prove a cause or an effect."""
    if state == "VALID":
        return "PASS"
    if use == "OBSERVATION" and state != "SUPERSEDED":
        return "WARN"  # may be cited in D2 with an annotation
    return "BLOCK"


def effective(rule: str, manual: str | None) -> str:
    """A person may always downgrade; may upgrade only states the rules could not settle (UNVERIFIED/SUSPECT)."""
    if manual is None or RANK[manual] >= RANK[rule] or rule in ("UNVERIFIED", "SUSPECT"):
        return manual or rule
    return rule


def rule_states(session: Session, case_id: str) -> dict[str, tuple[str, str, dict]]:
    """evidence_id -> (state, reason, checks) from existing provenance/revision/data-quality flags."""
    rows = session.execute(
        select(Evidence.evidence_id, Evidence.validity, SourceEvent.event_id, SourceEvent.entity_type,
               SourceEvent.original_row_id, SourceAsset.source_version, SourceAsset.content_sha256)
        .outerjoin(SourceEvent, Evidence.source_event_id == SourceEvent.id)
        .outerjoin(SourceAsset, SourceEvent.source_asset_id == SourceAsset.id)
        .where(Evidence.case_id == case_id)).all()
    top: dict[tuple, int] = {}
    for r in rows:
        if r.event_id:
            k = (r.entity_type, r.original_row_id)
            top[k] = max(top.get(k, 0), r.source_version)
    issues: dict[str, list[str]] = {}
    for event_id, code in session.execute(select(DataQualityIssue.event_id, DataQualityIssue.code)
                                          .where(DataQualityIssue.case_id == case_id)):
        issues.setdefault(event_id, []).append(code)
    out = {}
    for r in rows:
        if r.event_id is None:
            out[r.evidence_id] = ("UNVERIFIED", "derived model output, not a measurement", {"derived": True})
            continue
        codes = sorted(issues.get(r.event_id, []))
        checks = {"source_version": r.source_version, "latest_version": top[(r.entity_type, r.original_row_id)],
                  "validity": r.validity, "issues": codes, "asset_sha256": r.content_sha256,
                  "calibration": "NOT_IN_SOURCE", "time_sync": "NOT_IN_SOURCE"}
        if r.source_version < checks["latest_version"]:
            out[r.evidence_id] = ("SUPERSEDED", f"source row corrected in v{checks['latest_version']}", checks)
        elif hit := CONFLICT_CODES.intersection(codes):
            out[r.evidence_id] = ("CONFLICTED", f"data-quality conflict {sorted(hit)}", checks)
        elif r.validity != "CHECKED" or (hit := SUSPECT_CODES.intersection(codes)):
            out[r.evidence_id] = ("SUSPECT", f"validity={r.validity} issues={sorted(hit or [])}", checks)
        else:
            out[r.evidence_id] = ("VALID", "current source version, checked, no data-quality issue", checks)
    return out


def _latest(session: Session, case_id: str, ids: set[str] | None) -> dict[str, dict[str, EvidenceQuality]]:
    """evidence_id -> {"rule": latest SYSTEM_RULES row, "manual": latest person row}."""
    q = select(EvidenceQuality).where(EvidenceQuality.case_id == case_id).order_by(EvidenceQuality.version)
    if ids is not None:
        q = q.where(EvidenceQuality.evidence_id.in_(ids))
    out: dict[str, dict[str, EvidenceQuality]] = {}
    for row in session.scalars(q):
        out.setdefault(row.evidence_id, {})["rule" if row.checked_by == "SYSTEM_RULES" else "manual"] = row
    return out


def _next_version(session: Session, case_id: str, evidence_id: str) -> int:
    return (session.scalar(select(func.max(EvidenceQuality.version)).where(
        EvidenceQuality.case_id == case_id, EvidenceQuality.evidence_id == evidence_id)) or 0) + 1


def current(session: Session, case_id: str, ids: set[str] | None = None) -> dict[str, dict]:
    """Effective state per evidence id; persists a new rule row whenever the rule state changed."""
    rules = rule_states(session, case_id)
    wanted = set(rules) if ids is None else ids & set(rules)
    stored = _latest(session, case_id, wanted)
    now = datetime.now(UTC).isoformat()
    out = {}
    for ev in sorted(wanted):
        state, reason, checks = rules[ev]
        rule_row, manual = stored.get(ev, {}).get("rule"), stored.get(ev, {}).get("manual")
        if rule_row is None or rule_row.quality_state != state:
            version = max((r.version for r in (rule_row, manual) if r is not None), default=0) + 1
            session.add(EvidenceQuality(case_id=case_id, evidence_id=ev, version=version,
                                        quality_state=state, reason=reason, measurements=checks,
                                        checked_by="SYSTEM_RULES", created_at=now))
        eff = effective(state, manual.quality_state if manual else None)
        out[ev] = {"evidence_id": ev, "quality_state": eff, "rule_state": state, "reason": reason,
                   "manual": None if manual is None else {"state": manual.quality_state, "by": manual.checked_by,
                                                          "reason": manual.reason, "at": manual.created_at},
                   "checks": checks}
    session.flush()
    for ev in sorted((ids or set()) - set(rules)):
        out[ev] = {"evidence_id": ev, "quality_state": "UNVERIFIED", "rule_state": "UNVERIFIED",
                   "reason": "evidence id not found in this case", "manual": None, "checks": {}}
    return out


def record(session: Session, case_id: str, evidence_id: str, state: str, reason: str, actor_id: str) -> dict:
    if state not in STATES:
        raise ValueError(f"quality_state must be one of {STATES}")
    if evidence_id not in rule_states(session, case_id):
        raise LookupError("unknown evidence id for this case")
    session.add(EvidenceQuality(case_id=case_id, evidence_id=evidence_id,
                                version=_next_version(session, case_id, evidence_id), quality_state=state,
                                reason=reason, measurements={}, checked_by=actor_id,
                                created_at=datetime.now(UTC).isoformat()))
    session.flush()
    return current(session, case_id, {evidence_id})[evidence_id]


def check_use(session: Session, case_id: str, ids: list[str], use: str) -> tuple[list[str], list[str]]:
    """(blocks, warns) for citing these evidence ids in `use`."""
    states = current(session, case_id, set(ids))
    blocks, warns = [], []
    for ev in ids:
        s = states[ev]["quality_state"]
        verdict = suitable(s, use)
        if verdict == "BLOCK":
            blocks.append(f"{ev} is {s}; not usable as {use} evidence")
        elif verdict == "WARN":
            warns.append(f"{ev} is {s}; cite only with an annotation")
    return blocks, warns
