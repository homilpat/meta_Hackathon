"""D7 prevention (controlled-document revisions put in effect) and D8 closure (G7).

D7 counts only a revision that is in the registry, released by someone other than its author, in effect, raised
by this case and still the current revision, with every in-scope operator trained and every sister line decided.
A sentence saying "SOP updated" is not evidence. D8 re-evaluates everything in one transaction: the policy route,
every stage, open actions, effectiveness and cause evidence, D7, customer notification, residual risk and the
team's acknowledgements, then archives the snapshot it closed on. Reopening appends; nothing is overwritten.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import actions, causes, effect, experience, policy, quality, registry
from app.db import (
    Action,
    Closure,
    ClosureAck,
    ControlledDocument,
    DocumentVersion,
    EffectivenessPlan,
    EffectivenessResult,
    PreventionDeployment,
    ProcessContext,
)
from app.workflow import Actor, log, require_case

OPEN_ACTION = ("REQUESTED", "PLAN_APPROVED", "EXECUTED")


def now() -> str:
    return datetime.now(UTC).isoformat()


def site_of(session: Session, case_id: str) -> str | None:
    return session.scalar(select(ProcessContext.site).where(ProcessContext.case_id == case_id))


def latest_closure(session: Session, case_id: str) -> Closure | None:
    return session.scalar(select(Closure).where(Closure.case_id == case_id).order_by(Closure.id.desc()).limit(1))


# --- D7 -----------------------------------------------------------------------------------------------------

def d7_state(session: Session, case_id: str, body: dict) -> tuple[str | None, list[str]]:
    deps = session.scalars(select(PreventionDeployment).where(PreventionDeployment.case_id == case_id)
                           .order_by(PreventionDeployment.id)).all()
    if not deps:
        return None, []
    latest = {d.doc_number: d for d in deps}
    site, reasons = site_of(session, case_id), []
    for kind in body.get("prevention_required", ["FMEA", "SOP"]):
        if not any(d.kind == kind for d in latest.values()):
            reasons.append(f"no {kind} revision deployed")
    for d in latest.values():
        st = registry.revision_state(session, d.doc_number, d.new_revision, site)
        if not st["in_effect"]:
            reasons.append(st["reason"])
        trained = {t["operator_id"] for t in d.training}
        if untrained := sorted(set(d.operators_in_scope) - trained):
            reasons.append(f"{d.doc_number} rev {d.new_revision}: operators {untrained} not trained")
    return ("DONE" if not reasons else "IN_PROGRESS"), reasons


# --- D8 -----------------------------------------------------------------------------------------------------

def _acks(session: Session, case_id: str) -> list[ClosureAck]:
    last = latest_closure(session, case_id)
    since = last.created_at if last is not None and last.decision == "REOPENED" else ""
    return list(session.scalars(select(ClosureAck).where(ClosureAck.case_id == case_id,
                                                          ClosureAck.created_at > since).order_by(ClosureAck.id)))


def readiness(session: Session, case_id: str) -> dict:
    from app.eightd import active_policy, latest_triage, route, stage_state, team

    p = active_policy(session, case_id)
    state, r = stage_state(session, case_id), route(session, case_id)
    v = policy.can_close(p.body, state, r)
    blocks = list(v.reasons) if v.result == "BLOCK" else []
    for a in session.scalars(select(Action).where(Action.case_id == case_id).order_by(Action.id)):
        st = actions.status(session, a.id)
        if st in OPEN_ACTION:
            blocks.append(f"action #{a.id} ({a.stage} {a.action_type}) is still {st}")
        if a.stage == "D5" and st == "INDEPENDENTLY_VERIFIED":
            res = session.scalar(select(EffectivenessResult).where(
                EffectivenessResult.action_id == a.id, EffectivenessResult.decision == "EFFECTIVE")
                .order_by(EffectivenessResult.id.desc()).limit(1))
            computed, _, why = effect.evaluate(session, session.get(EffectivenessPlan, res.plan_id))
            if computed != "MEETS_CRITERIA":
                blocks.append(f"action #{a.id}: effectiveness no longer holds on current data ({computed}: "
                              f"{'; '.join(why)})")
    for h in causes.confirmed(session, case_id):
        ids = list(dict.fromkeys([*h.evidence_ids, *(i for e in causes.experiments(session, h.id)
                                                       for i in e.evidence_ids if e.result == "SUPPORTS")]))
        unfit, _ = quality.check_use(session, case_id, ids, "ROOT_CAUSE")
        blocks += [f"H{h.id}: {u}" for u in unfit]
    _, d7_reasons = d7_state(session, case_id, p.body)
    blocks += [f"D7: {x}" for x in d7_reasons]
    t = latest_triage(session, case_id)
    notify = bool(t and (t.risk_flags.get("shipped_in_scope") or t.risk_flags.get("customer_impact")))
    accepted = {m["user_id"]: resp for resp, m in team(session, case_id, p.body)["members"].items()
                if m["status"] == "ACCEPTED"}
    acked = {a.user_id for a in _acks(session, case_id)}
    if missing := sorted(set(accepted) - acked):
        blocks.append(f"team members {missing} have not acknowledged the result")
    last = latest_closure(session, case_id)
    if last is not None and last.decision == "CLOSED":
        blocks.append("case is already CLOSED; reopen it first")
    return {"policy": policy.ref(p), "route": r, "state": state, "blocks": blocks,
            "needs_customer_notification": notify, "acknowledged": sorted(acked), "team": accepted,
            "ready": not blocks}


def snapshot(session: Session, case_id: str, ready: dict) -> dict:
    docs = session.scalars(select(DocumentVersion).where(DocumentVersion.case_id == case_id)
                           .order_by(DocumentVersion.id)).all()
    acts = session.scalars(select(Action).where(Action.case_id == case_id).order_by(Action.id)).all()
    deps = session.scalars(select(PreventionDeployment).where(PreventionDeployment.case_id == case_id)
                           .order_by(PreventionDeployment.id)).all()
    return {"case_id": case_id, "policy": ready["policy"], "route": ready["route"], "state": ready["state"],
            "documents": [{"doc_type": d.doc_type, "version": d.version, "status": d.status,
                           "content_sha256": d.content_sha256} for d in docs],
            "actions": [{"action_id": a.id, "stage": a.stage, "type": a.action_type,
                         "status": actions.status(session, a.id)} for a in acts],
            "confirmed_causes": [h.id for h in causes.confirmed(session, case_id)],
            "effectiveness": [{"result_id": x.id, "action_id": x.action_id, "decision": x.decision,
                               "computed": x.computed} for x in session.scalars(
                select(EffectivenessResult).where(EffectivenessResult.case_id == case_id)
                .order_by(EffectivenessResult.id))],
            "prevention": [{"doc_number": d.doc_number, "revision": d.new_revision} for d in deps],
            "acknowledged": ready["acknowledged"], "data_origin": "SYNTHETIC"}


def sha(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def closure_out(c: Closure) -> dict:
    return {"closure_id": c.id, "decision": c.decision, "snapshot_sha256": c.snapshot_sha256,
            "snapshot": c.snapshot, "residual_risks": c.residual_risks,
            "customer_notification_ref": c.customer_notification_ref, "comment": c.comment,
            "actor_id": c.actor_id, "policy_hash": c.policy_hash, "at": c.created_at}


# --- request bodies -----------------------------------------------------------------------------------------

class RevisionIn(BaseModel):
    doc_number: str = Field(min_length=3, max_length=40, pattern=r"^[A-Z0-9\-]+$")
    kind: str
    base_revision: int = Field(ge=0)  # 0 for a new document
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    site: str = "SITE-A"
    process_type: str = "PCB_SMT"
    customer: str = "*"
    acl_roles: list[str] = ["*"]
    case_id: str


class ReleaseIn(BaseModel):
    effective_from: datetime | None = None
    reason: str = Field(min_length=5, max_length=500)


class Training(BaseModel):
    operator_id: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=3)


class SisterLine(BaseModel):
    line: str
    applies: bool
    reason: str = Field(min_length=5)


class PreventionIn(BaseModel):
    doc_number: str
    new_revision: int
    scopes: list[str] = Field(min_length=1)
    operators_in_scope: list[str] = []
    training: list[Training] = []
    sister_lines: list[SisterLine] = []
    exceptions: str = Field(default="", max_length=1000)


class AckIn(BaseModel):
    contribution: str = Field(min_length=5, max_length=500)


class Risk(BaseModel):
    risk: str = Field(min_length=5)
    mitigation: str = Field(min_length=5)
    owner: str = Field(min_length=2)


class ClosureIn(BaseModel):
    residual_risks: list[Risk] = Field(min_length=1)
    customer_notification_ref: str | None = None
    comment: str = Field(min_length=5, max_length=1000)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


def make_d7_d8_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    from app.eightd import active_policy, team

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.get("/controlled-documents")
    def list_documents(actor: Who, kind: str | None = None) -> list[dict]:
        """Registry rows the caller's role may read, with whether each revision is in effect (any site)."""
        with sessions.begin() as session:
            out = []
            for r in registry.rows(session):
                if (kind and r.kind != kind) or not registry.visible(r, actor.role):
                    continue
                st = registry.revision_state(session, r.doc_number, r.revision, None if r.site == "*" else r.site)
                out.append({**registry.out(r), "in_effect": st["in_effect"] and st["row"].id == r.id,
                            "effect_reason": st["reason"]})
            return out

    @router.post("/controlled-documents/revisions", status_code=201)
    def draft_revision(body: RevisionIn, actor: Who) -> dict:
        if actor.role not in ("AUTHOR", "PROCESS_ENGINEER"):
            raise HTTPException(403, "AUTHOR or PROCESS_ENGINEER role required")
        if body.kind not in registry.KINDS:
            raise HTTPException(422, f"kind must be one of {registry.KINDS}")
        with sessions.begin() as session:
            require_case(session, body.case_id, actor)
            mine = registry.rows(session, body.doc_number)
            if mine and mine[-1].kind != body.kind:
                raise HTTPException(422, f"{body.doc_number} is a {mine[-1].kind}")
            top = session.scalar(select(func.max(ControlledDocument.revision)).where(
                ControlledDocument.doc_number == body.doc_number)) or 0
            released = max((r.revision for r in mine if r.status == "RELEASED"), default=0)
            if body.base_revision != released:
                raise HTTPException(409, f"base_revision must be the latest released revision ({released})")
            rev = top + 1
            row = ControlledDocument(
                doc_number=body.doc_number, kind=body.kind, revision=rev, status="DRAFT", title=body.title,
                body=body.body, site=body.site, process_type=body.process_type, customer=body.customer,
                effective_from=now(), effective_to=None, acl_roles=body.acl_roles,
                content_sha256=registry.body_sha256(body.doc_number, rev, body.title, body.body),
                authored_by=actor.id, released_by=None, case_id=body.case_id, created_at=now())
            session.add(row)
            session.flush()
            log(session, body.case_id, actor, "D7_REVISION_DRAFTED", f"{body.doc_number} rev {rev} "
                f"(base {body.base_revision}) {row.content_sha256}")
            return registry.out(row)

    @router.post("/controlled-documents/{number}/revisions/{rev}/release", status_code=201)
    def release(number: str, rev: int, body: ReleaseIn, actor: Who) -> dict:
        if actor.role != "REVIEWER":
            raise HTTPException(403, "REVIEWER role required to release a controlled document")
        with sessions.begin() as session:
            mine = [r for r in registry.rows(session, number) if r.revision == rev]
            if not mine:
                raise HTTPException(404, "revision not found")
            draft = mine[-1]
            if draft.status != "DRAFT":
                raise HTTPException(409, f"{number} rev {rev} is {draft.status}")
            if draft.authored_by == actor.id:
                raise HTTPException(403, "the author cannot release their own revision")
            if draft.case_id:
                require_case(session, draft.case_id, actor)
            at = (body.effective_from or datetime.now(UTC)).isoformat()
            row = ControlledDocument(**{c.key: getattr(draft, c.key) for c in ControlledDocument.__table__.columns
                                        if c.key not in ("id", "status", "released_by", "effective_from",
                                                         "created_at")},
                                     status="RELEASED", released_by=actor.id, effective_from=at, created_at=now())
            session.add(row)
            session.flush()
            if draft.case_id:
                log(session, draft.case_id, actor, "D7_REVISION_RELEASED",
                    f"{number} rev {rev} effective {at}: {body.reason}")
            return registry.out(row)

    @router.post("/cases/{case_id}/prevention", status_code=201)
    def prevention(case_id: str, body: PreventionIn, actor: Who) -> dict:
        if actor.role not in ("AUTHOR", "PROCESS_ENGINEER"):
            raise HTTPException(403, "AUTHOR or PROCESS_ENGINEER role required")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            st = registry.revision_state(session, body.doc_number, body.new_revision, site_of(session, case_id))
            if not st["in_effect"]:
                raise HTTPException(422, f"not revision evidence: {st['reason']}")
            row = st["row"]
            if row.case_id != case_id:
                raise HTTPException(422, f"{body.doc_number} rev {body.new_revision} was not revised for this case; "
                                         "an existing revision is not a D7 change")
            old = max((r.revision for r in registry.rows(session, body.doc_number)
                       if r.status == "RELEASED" and r.revision < body.new_revision), default=0)
            d = PreventionDeployment(case_id=case_id, doc_number=body.doc_number, kind=row.kind, old_revision=old,
                                     new_revision=body.new_revision, scopes=body.scopes,
                                     operators_in_scope=body.operators_in_scope,
                                     training=[t.model_dump() for t in body.training],
                                     sister_lines=[s.model_dump() for s in body.sister_lines],
                                     exceptions=body.exceptions, recorded_by=actor.id, created_at=now())
            session.add(d)
            session.flush()
            log(session, case_id, actor, "D7_DEPLOYED", f"{body.doc_number} rev {old} -> {body.new_revision} "
                f"scopes={body.scopes} trained={len(body.training)}/{len(body.operators_in_scope)}")
            return get_prevention(case_id, actor, session)

    def get_prevention(case_id: str, actor: Actor, session: Session) -> dict:
        state, reasons = d7_state(session, case_id, active_policy(session, case_id).body)
        deps = session.scalars(select(PreventionDeployment).where(PreventionDeployment.case_id == case_id)
                               .order_by(PreventionDeployment.id)).all()
        return {"state": state, "reasons": reasons, "deployments": [
            {"id": d.id, "doc_number": d.doc_number, "kind": d.kind, "old_revision": d.old_revision,
             "new_revision": d.new_revision, "scopes": d.scopes, "operators_in_scope": d.operators_in_scope,
             "training": d.training, "sister_lines": d.sister_lines, "exceptions": d.exceptions,
             "recorded_by": d.recorded_by, "at": d.created_at} for d in deps]}

    @router.get("/cases/{case_id}/prevention")
    def read_prevention(case_id: str, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            return get_prevention(case_id, actor, session)

    @router.post("/cases/{case_id}/closure/acknowledgements", status_code=201)
    def acknowledge(case_id: str, body: AckIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            members = team(session, case_id, active_policy(session, case_id).body)["members"]
            resp = next((r for r, m in members.items() if m["user_id"] == actor.id and m["status"] == "ACCEPTED"),
                        None)
            if resp is None:
                raise HTTPException(403, "only accepted D1 team members acknowledge the result")
            if actor.id in {a.user_id for a in _acks(session, case_id)}:
                raise HTTPException(409, "already acknowledged")
            session.add(ClosureAck(case_id=case_id, user_id=actor.id, responsibility=resp,
                                   contribution=body.contribution, created_at=now()))
            log(session, case_id, actor, "D8_ACKNOWLEDGED", f"{resp}: {body.contribution[:120]}")
            return {"user_id": actor.id, "responsibility": resp}

    @router.get("/cases/{case_id}/closure")
    def closure_status(case_id: str, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            hist = session.scalars(select(Closure).where(Closure.case_id == case_id).order_by(Closure.id)).all()
            return {**readiness(session, case_id), "history": [closure_out(c) for c in hist]}

    @router.post("/cases/{case_id}/closure", status_code=201)
    def close(case_id: str, body: ClosureIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            need = p.body["approval_gates"]["D8"]["approver"]
            if actor.role != need:
                raise HTTPException(403, f"D8 closure needs role {need}")
            ready = readiness(session, case_id)
            blocks = list(ready["blocks"])
            if ready["needs_customer_notification"] and len((body.customer_notification_ref or "").strip()) < 5:
                blocks.append("shipped or customer-impacting case: customer_notification_ref is required")
            if blocks:
                raise HTTPException(409, "; ".join(blocks))
            snap = snapshot(session, case_id, ready)
            c = Closure(case_id=case_id, decision="CLOSED", snapshot=snap, snapshot_sha256=sha(snap),
                        residual_risks=[r.model_dump() for r in body.residual_risks],
                        customer_notification_ref=body.customer_notification_ref, comment=body.comment,
                        actor_id=actor.id, policy_hash=p.policy_hash, created_at=now())
            session.add(c)
            session.flush()
            log(session, case_id, actor, "D8_CLOSED", f"snapshot {c.snapshot_sha256} policy {p.policy_hash} "
                f"residual risks={len(body.residual_risks)}")
            keys = experience.index_case(session, case_id, c.id)  # verified outcome becomes searchable experience
            log(session, case_id, actor, "EXPERIENCE_INDEXED", f"{keys} (recurrence NOT_YET_OBSERVED)")
            return closure_out(c)

    @router.post("/cases/{case_id}/closure/reopen", status_code=201)
    def reopen(case_id: str, body: ReopenIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            need = p.body["approval_gates"]["D8"]["approver"]
            if actor.role != need:
                raise HTTPException(403, f"reopening needs role {need}")
            last = latest_closure(session, case_id)
            if last is None or last.decision != "CLOSED":
                raise HTTPException(409, "case is not CLOSED")
            snap = snapshot(session, case_id, readiness(session, case_id))
            c = Closure(case_id=case_id, decision="REOPENED", snapshot=snap, snapshot_sha256=sha(snap),
                        residual_risks=[], customer_notification_ref=None, comment=body.reason, actor_id=actor.id,
                        policy_hash=p.policy_hash, created_at=now())
            session.add(c)
            session.flush()
            revoked = experience.revoke_case(session, case_id, f"case reopened: {body.reason[:200]}")
            log(session, case_id, actor, "D8_REOPENED", f"{body.reason[:200]} (closed snapshot "
                f"{last.snapshot_sha256} kept); experience revoked {revoked}")
            return closure_out(c)

    return router
