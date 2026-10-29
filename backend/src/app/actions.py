"""Action lifecycle shared by urgent containment, D3 containment and D5/D6 corrective actions.

PROPOSED/approved plans, executions and independent verification are separate append-only events, so a plan can
never read as done. Every EXECUTED event here is SIMULATED: no real inventory, shipment or ERP state changes.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import policy
from app.db import Action, ActionEvent, AffectedObject, Evidence, WorkflowPolicy

HOLD_TYPES = {"HOLD", "SORT", "STOP_SHIP", "QUARANTINE"}  # physical in-plant actions
# event -> statuses it may follow, per stage
TRANSITIONS = {
    "PLAN_APPROVED": {"D3": ("REQUESTED",), "D5": ("REQUESTED",)},
    "EXECUTED": {"URGENT": ("REQUESTED",), "D3": ("PLAN_APPROVED",), "D5": ("PLAN_APPROVED",)},
    "INDEPENDENTLY_VERIFIED": {"URGENT": ("EXECUTED",), "D3": ("EXECUTED",), "D5": ("EXECUTED",)},
    "RELEASED": {"URGENT": ("INDEPENDENTLY_VERIFIED",), "D3": ("INDEPENDENTLY_VERIFIED",)},
    "NOT_EFFECTIVE": {s: ("EXECUTED", "INDEPENDENTLY_VERIFIED") for s in ("URGENT", "D3", "D5")},
    "CANCELLED": {s: ("REQUESTED", "PLAN_APPROVED") for s in ("URGENT", "D3", "D5")},
}
EXECUTE_PERMISSION = {"URGENT": "URGENT_CONTAINMENT", "D3": "D3_EXECUTE", "D5": "D6_EXECUTE"}
VERIFY_PERMISSION = {"URGENT": "D3_VERIFY", "D3": "D3_VERIFY", "D5": "D6_VERIFY"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def events(session: Session, action_id: int) -> list[ActionEvent]:
    return list(session.scalars(select(ActionEvent).where(ActionEvent.action_id == action_id)
                                .order_by(ActionEvent.id)))


def status(session: Session, action_id: int) -> str:
    evs = events(session, action_id)
    return evs[-1].event_type if evs else "MISSING"


def bind_targets(session: Session, case_id: str, stage: str, action_type: str, targets: list[str]) -> list[dict]:
    """Targets must be affected objects of this case; shipped product cannot be held in the plant."""
    objs = {o.object_id: o for o in session.scalars(select(AffectedObject).where(AffectedObject.case_id == case_id))}
    if not objs and targets:
        raise HTTPException(409, "record the process context first; targets bind to its affected objects")
    if unknown := sorted(set(targets) - set(objs)):
        raise HTTPException(422, f"unknown target objects {unknown}")
    if action_type in HOLD_TYPES:
        shipped = sorted(t for t in targets if objs[t].shipment_state == "SHIPPED")
        if shipped:
            raise HTTPException(422, f"{action_type} cannot act on SHIPPED objects {shipped}; "
                                     "use CUSTOMER_NOTIFY_REQUEST for shipped product")
    return [{"object_id": t, "object_type": objs[t].object_type, "shipment_state": objs[t].shipment_state,
             "identity_source": objs[t].identity_source} for t in targets]


def create(session: Session, case_id: str, stage: str, action_type: str, description: str, targets: list[str],
           actor_id: str, policy_hash: str, cause_ids: list[int] | None = None,
           document_version_id: int | None = None, details: dict | None = None) -> Action:
    snap = bind_targets(session, case_id, stage, action_type, targets)
    a = Action(case_id=case_id, stage=stage, action_type=action_type, description=description, targets=targets,
               target_snapshot=snap, cause_ids=cause_ids or [], document_version_id=document_version_id, details=details,
               created_by=actor_id, created_at=now())
    session.add(a)
    session.flush()
    session.add(ActionEvent(action_id=a.id, event_type="REQUESTED", actor_id=actor_id, occurred_at=now(),
                            evidence=[], note="", synthetic=True, policy_hash=policy_hash))
    session.flush()
    return a


def record(session: Session, a: Action, event_type: str, actor_id: str, role: str, pol: WorkflowPolicy, note: str,
           evidence: list[str]) -> ActionEvent:
    """Validate one lifecycle event against the transition table and the policy, then append it."""
    body = pol.body
    allowed = TRANSITIONS.get(event_type, {}).get(a.stage)
    if allowed is None:
        raise HTTPException(422, f"{event_type} is not a {a.stage} action event")
    evs = events(session, a.id)
    current = evs[-1].event_type if evs else "MISSING"
    if current not in allowed:
        raise HTTPException(409, f"{event_type} needs the action to be {' or '.join(allowed)} (is {current})")
    if event_type == "EXECUTED":
        v = policy.can_execute(body, EXECUTE_PERMISSION[a.stage], role)
        if v.result == "BLOCK":
            raise HTTPException(403, "; ".join(v.reasons))
    if event_type == "INDEPENDENTLY_VERIFIED":
        v = policy.can_execute(body, VERIFY_PERMISSION[a.stage], role)
        if v.result == "BLOCK":
            raise HTTPException(403, "; ".join(v.reasons))
        executor = next(e.actor_id for e in reversed(evs) if e.event_type == "EXECUTED")
        if body["independent_verification"] and executor == actor_id:
            raise HTTPException(403, "verifier must be independent of the executor")
        if not evidence:
            raise HTTPException(422, "independent verification needs verification evidence")
    if event_type in ("EXECUTED", "NOT_EFFECTIVE", "RELEASED") and len(note) < 10:
        raise HTTPException(422, f"{event_type} needs a note of at least 10 characters (what was done, where)")
    known = set(session.scalars(select(Evidence.evidence_id).where(Evidence.case_id == a.case_id)))
    if bad := sorted(e for e in evidence if e.startswith("EV-") and e not in known):
        raise HTTPException(422, f"unknown evidence {bad}")
    ev = ActionEvent(action_id=a.id, event_type=event_type, actor_id=actor_id, occurred_at=now(), evidence=evidence,
                     note=note, synthetic=True, policy_hash=pol.policy_hash)
    session.add(ev)
    session.flush()
    return ev


def out(session: Session, a: Action) -> dict:
    evs = events(session, a.id)
    return {"action_id": a.id, "case_id": a.case_id, "stage": a.stage, "action_type": a.action_type,
            "description": a.description, "targets": a.targets, "target_snapshot": a.target_snapshot,
            "cause_ids": a.cause_ids, "details": a.details, "document_version_id": a.document_version_id, "created_by": a.created_by,
            "created_at": a.created_at, "status": evs[-1].event_type if evs else "MISSING",
            "execution_mode": "SIMULATED",  # synthetic demo: nothing physical happened
            "events": [{"event_type": e.event_type, "actor_id": e.actor_id, "at": e.occurred_at,
                        "evidence": e.evidence, "note": e.note, "synthetic": e.synthetic} for e in evs]}
