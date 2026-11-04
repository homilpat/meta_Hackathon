"""v5 D0-D8 engine routes. New decision entry points consult the versioned WorkflowPolicy; the S6 document
routes in workflow.py keep their own chain unchanged (backwards compatible)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import actions, causes, closure, effect, factcheck, ncr, policy, process, quality
from app.db import (
    Action,
    AffectedObject,
    Assignment,
    DocumentVersion,
    Evidence,
    ProcessContext,
    TeamEvent,
    TriageAssessment,
    WorkflowPolicy,
)
from app.fields import FreeText, OptionalText, text
from app.workflow import DEMO_USERS, KINDS, STEP, Actor, log, require_case, require_role


def now() -> str:
    return datetime.now(UTC).isoformat()


# --- derived case state ----------------------------------------------------------------------------------

def latest_triage(session: Session, case_id: str) -> TriageAssessment | None:
    return session.scalar(select(TriageAssessment).where(TriageAssessment.case_id == case_id)
                          .order_by(TriageAssessment.id.desc()).limit(1))


def case_ctx(session: Session, case_id: str) -> dict:
    pc = session.scalar(select(ProcessContext).where(ProcessContext.case_id == case_id))
    t = latest_triage(session, case_id)
    ctx = {"site": pc.site, "customer": pc.customer, "process_type": pc.process_type} if pc else {}
    return {**ctx, "severity": t.severity} if t else ctx


def active_policy(session: Session, case_id: str) -> WorkflowPolicy:
    return policy.active(session, case_ctx(session, case_id))


def route(session: Session, case_id: str) -> str | None:
    t = latest_triage(session, case_id)
    return t.route if t else None


def team(session: Session, case_id: str, body: dict) -> dict:
    """Current D1 team per responsibility, derived from the event log, plus what is still missing."""
    cur: dict[str, dict] = {}
    for e in session.scalars(select(TeamEvent).where(TeamEvent.case_id == case_id).order_by(TeamEvent.id)):
        if e.event == "ASSIGNED":
            cur[e.responsibility] = {"user_id": e.user_id, "status": "ASSIGNED", "due_at": e.due_at, "note": e.note}
        elif e.event in ("ACCEPTED", "DECLINED") and cur.get(e.responsibility, {}).get("user_id") == e.user_id:
            cur[e.responsibility] = {**cur[e.responsibility], "status": e.event, "note": e.note}
        elif e.event == "EXCEPTION":
            cur[e.responsibility] = {"user_id": None, "status": "EXCEPTION", "due_at": None, "note": e.note}
    at = now()
    for m in cur.values():
        m["overdue"] = m["status"] == "ASSIGNED" and bool(m["due_at"]) and m["due_at"] < at
    missing = [r for r in body["required_roles"] if cur.get(r, {}).get("status") not in ("ACCEPTED", "EXCEPTION")]
    return {"members": cur, "missing": missing, "complete": not missing}


def stage_state(session: Session, case_id: str, documents_only: bool = False) -> dict[str, str | None]:
    """Status per 8D stage. D2-D4 come from the S6 documents; later gates add their own entities.
    documents_only: D3 reads its document status (what a document approval builds on), not action completion."""
    state: dict[str, str | None] = dict.fromkeys(policy.STAGES)
    state["D0"] = "DONE" if latest_triage(session, case_id) else None
    if session.scalar(select(TeamEvent.id).where(TeamEvent.case_id == case_id).limit(1)):
        complete = team(session, case_id, active_policy(session, case_id).body)["complete"]
        state["D1"] = "DONE" if complete else "IN_PROGRESS"
    for doc_type in KINDS.values():
        doc = session.scalar(select(DocumentVersion).where(
            DocumentVersion.case_id == case_id, DocumentVersion.doc_type == doc_type)
            .order_by(DocumentVersion.version.desc()).limit(1))
        state[STEP[doc_type]] = doc.status if doc else None
    if state["D3"] == "APPROVED" and not documents_only:  # an approved plan is not containment done: every D3 action must be verified
        st = [actions.status(session, a.id) for a in session.scalars(
            select(Action).where(Action.case_id == case_id, Action.stage == "D3"))]
        live = [x for x in st if x != "CANCELLED"]
        done = live and all(x in ("INDEPENDENTLY_VERIFIED", "RELEASED") for x in live)
        state["D3"] = "DONE" if done else "PLAN_APPROVED"
    if state["D4"] == "APPROVED" and not documents_only:  # an approved hypothesis document is not a known cause
        state["D4"] = "DONE" if causes.confirmed(session, case_id) else "NO_CONFIRMED_CAUSE"
    state["D5"], state["D6"] = effect.stage_states(session, case_id)
    state["D7"], _ = closure.d7_state(session, case_id, active_policy(session, case_id).body)
    last = closure.latest_closure(session, case_id)
    state["D8"] = last.decision if last else None  # CLOSED / REOPENED
    return state


def approval_gate(session: Session, case_id: str, doc_type: str, actor: Actor,
                  author_id: str | None) -> tuple[policy.Verdict, WorkflowPolicy]:
    """The one approval decision for the D2-D4 documents, used by the S6 document routes and /gates alike.
    Under DEFAULT it equals the S6 chain (role per stage, upstream document APPROVED, no self-approval)."""
    p = active_policy(session, case_id)
    state = stage_state(session, case_id, documents_only=True)
    return policy.can_approve(p.body, STEP[doc_type], actor.role, actor.id, author_id, state), p


def approver_role(session: Session, case_id: str, doc_type: str) -> str:
    return active_policy(session, case_id).body["approval_gates"][STEP[doc_type]]["approver"]


def triage_out(t: TriageAssessment) -> dict:
    return {"triage_id": t.id, "signal_kind": t.signal_kind, "observed_defect": t.observed_defect,
            "risk_flags": t.risk_flags, "scope_lots": t.scope_lots, "route": t.route, "severity": t.severity,
            "rationale": t.rationale, "evidence_ids": t.evidence_ids, "assessor_id": t.assessor_id,
            "policy_hash": t.policy_hash, "created_at": t.created_at}


def confirmed_defect_evidence(session: Session, case_id: str, ids: list[str]) -> list[str]:
    """Cited human verifications that confirm a defect on a current source row. An SPC alarm never qualifies."""
    states = quality.current(session, case_id, set(ids))
    return [i["ev"] for i in ncr._evidence(session, case_id)
            if i["ev"] in ids and i["type"] == "human_verifications" and i["rec"].get("result") == "DEFECT_CONFIRMED"
            and states[i["ev"]]["quality_state"] != "SUPERSEDED"]


def get_action(session: Session, case_id: str, action_id: int) -> Action:
    a = session.get(Action, action_id)
    if a is None or a.case_id != case_id:
        raise HTTPException(404, "action not found")
    return a


# --- request bodies --------------------------------------------------------------------------------------

class PolicyIn(BaseModel):
    policy_id: str = Field(min_length=2, max_length=60, pattern=r"^[A-Z0-9_\-]+$")
    applicability: dict[str, str] = {}
    body: dict


class QualityIn(BaseModel):
    evidence_id: str
    quality_state: Literal["VALID", "UNVERIFIED", "SUSPECT", "CONFLICTED", "SUPERSEDED"]
    reason: FreeText


class ProcessIn(BaseModel):
    site: str = Field(min_length=1, max_length=40)
    customer: str = Field(default="DEFAULT", min_length=1, max_length=60)
    process_type: str = "PCB_SMT"


class TriageIn(BaseModel):
    signal_kind: Literal["SPC_SIGNAL", "AOI_FAIL", "CUSTOMER_COMPLAINT", "OTHER"]
    observed_defect: Literal["SIGNAL_ONLY", "DEFECT_CONFIRMED", "UNKNOWN"]
    risk_flags: dict[str, bool] = {}  # customer_impact, safety; shipped_in_scope is computed by the server
    scope_lots: list[str] = []
    route: Literal["NCR_ONLY", "FULL_8D", "EMERGENCY_FULL_8D"]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    rationale: FreeText
    evidence_ids: list[str] = Field(min_length=1)


class TeamIn(BaseModel):
    event: Literal["ASSIGN", "ACCEPT", "DECLINE", "EXCEPTION"]
    responsibility: Literal["LEAD", "QUALITY", "PRODUCTION", "PROCESS", "SUPPLIER", "CUSTOMER"]
    user_id: str | None = None
    due_at: str | None = None
    note: OptionalText = ""  # required for EXCEPTION


class ActionIn(BaseModel):
    action_type: Literal["HOLD", "SORT", "STOP_SHIP", "QUARANTINE", "CUSTOMER_NOTIFY_REQUEST", "OTHER",
                         "PROCESS_CHANGE", "EQUIPMENT_CHANGE", "INSPECTION_CHANGE", "TRAINING"]
    description: text(10, 1000)
    targets: list[str] = []  # D3/urgent: at least one affected object
    stage: Literal["D3", "D5"] = "D3"
    cause_ids: list[int] = []  # D5: cause hypotheses this corrective action addresses
    details: dict[str, str] = {}  # D5: feasibility, risk_analysis, side_effects


class ActionEventIn(BaseModel):
    event_type: Literal["PLAN_APPROVED", "EXECUTED", "INDEPENDENTLY_VERIFIED", "RELEASED", "NOT_EFFECTIVE",
                        "CANCELLED"]
    note: OptionalText = ""  # required for EXECUTED / NOT_EFFECTIVE / RELEASED
    evidence: list[str] = []


def _d3_plan_check(session: Session, a: Action, actor: Actor) -> None:
    """D3 plan approval: QA/Production, and the containment document the action came from is still APPROVED."""
    doc = session.get(DocumentVersion, a.document_version_id) if a.document_version_id else None
    if doc is None or doc.status != "APPROVED":
        raise HTTPException(409, f"containment plan must be APPROVED (is {doc.status if doc else 'missing'})")
    gate = active_policy(session, a.case_id).body["approval_gates"]["D3"]["approver"]
    if actor.role != gate:
        raise HTTPException(403, f"D3 계획 승인은 {policy.ROLE_KO.get(gate, gate)}만 할 수 있습니다")


# Stage-specific checks before PLAN_APPROVED. stage -> fn(session, action, actor).
PLAN_CHECKS: dict[str, Callable[[Session, Action, Actor], None]] = {"D3": _d3_plan_check,
                                                                    "D5": effect.d5_select_check}


def make_v5_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    # --- policy, evidence quality, process context (G2) ------------------------------------------------

    @router.get("/policies")
    def list_policies(actor: Who) -> list[dict]:
        with sessions.begin() as session:
            policy.ensure_default(session)
            return [{**policy.ref(p), "applicability": p.applicability, "effective_from": p.effective_from,
                     "approved_by": p.approved_by, "body": p.body}
                    for p in session.scalars(select(WorkflowPolicy).order_by(WorkflowPolicy.id))]

    @router.post("/policies", status_code=201)
    def publish_policy(body: PolicyIn, actor: Who) -> dict:
        require_role(actor, "REVIEWER")  # quality function owns the policy; new behaviour = new version
        unknown = set(body.applicability) - set(policy.DEFAULT_APPLICABILITY)
        if unknown:
            raise HTTPException(422, f"unknown applicability keys {sorted(unknown)}")
        with sessions.begin() as session:
            try:
                p = policy.publish(session, body.policy_id, body.applicability, body.body, actor.id)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return {**policy.ref(p), "applicability": p.applicability, "effective_from": p.effective_from}

    @router.get("/cases/{case_id}/gates")
    def gates(case_id: str, actor: Who) -> dict:
        """Every policy decision for this case, explained, for the calling user. Read-only."""
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            state, r = stage_state(session, case_id), route(session, case_id)
            body, docs = p.body, {STEP[t]: t for t in KINDS.values()}
            return {"policy": policy.ref(p), "state": state, "route": r,
                    "draft": {s: policy.can_draft(body, s, state).out() for s in body["draft_requirements"]},
                    "approve": {s: (approval_gate(session, case_id, docs[s], actor, None)[0] if s in docs else
                                    policy.can_approve(body, s, actor.role, actor.id, None, state)).out()
                                for s in body["approval_gates"]},
                    "urgent_containment": policy.can_execute_urgent(body, actor.role, state, r).out()}

    @router.get("/cases/{case_id}/evidence-quality")
    def evidence_quality(case_id: str, actor: Who, state: str | None = None) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            rows = quality.current(session, case_id)
            counts: dict[str, int] = {}
            for r in rows.values():
                counts[r["quality_state"]] = counts.get(r["quality_state"], 0) + 1
            items = [r for r in rows.values() if state is None or r["quality_state"] == state]
            return {"counts": counts, "items": items}

    @router.post("/cases/{case_id}/evidence-quality", status_code=201)
    def assess_evidence(case_id: str, body: QualityIn, actor: Who) -> dict:
        if actor.role not in ("REVIEWER", "PROCESS_ENGINEER"):
            raise HTTPException(403, "REVIEWER or PROCESS_ENGINEER role required")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            try:
                out = quality.record(session, case_id, body.evidence_id, body.quality_state, body.reason, actor.id)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
            log(session, case_id, actor, "EVIDENCE_QUALITY",
                f"{body.evidence_id} -> {body.quality_state} (effective {out['quality_state']}): {body.reason}")
            return out

    @router.post("/cases/{case_id}/process-context", status_code=201)
    def set_process_context(case_id: str, body: ProcessIn, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        adapter = process.ADAPTERS.get(body.process_type)
        if adapter is None:
            raise HTTPException(422, f"no adapter for process_type {body.process_type}")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            if session.scalar(select(ProcessContext.id).where(ProcessContext.case_id == case_id)):
                raise HTTPException(409, "process context already recorded for this case")
            ctx, objects = adapter.context(session, case_id), adapter.affected_objects(session, case_id)
            session.add(ProcessContext(case_id=case_id, site=body.site, customer=body.customer,
                                       config_hash=process.config_hash(ctx, objects), actor_id=actor.id,
                                       created_at=now(), **ctx))
            session.add_all(AffectedObject(case_id=case_id, **o) for o in objects)
            log(session, case_id, actor, "PROCESS_CONTEXT",
                f"{ctx['process_type']} {ctx['adapter_version']} site={body.site} objects={len(objects)}")
        return get_process_context(case_id, actor)

    @router.get("/cases/{case_id}/process-context")
    def get_process_context(case_id: str, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)
            pc = session.scalar(select(ProcessContext).where(ProcessContext.case_id == case_id))
            if pc is None:
                raise HTTPException(404, "no process context recorded")
            objs = session.scalars(select(AffectedObject).where(AffectedObject.case_id == case_id)
                                   .order_by(AffectedObject.id)).all()
            return {"site": pc.site, "customer": pc.customer, "process_type": pc.process_type,
                    "adapter_version": pc.adapter_version, "operation": pc.operation, "equipment": pc.equipment,
                    "recipe": pc.recipe, "config_hash": pc.config_hash,
                    "objects": [{"object_type": o.object_type, "object_id": o.object_id, "parent_id": o.parent_id,
                                 "location": o.location, "shipment_state": o.shipment_state,
                                 "identity_source": o.identity_source} for o in objs]}

    # --- D0 triage (G3) --------------------------------------------------------------------------------

    @router.post("/cases/{case_id}/triage", status_code=201)
    def triage(case_id: str, body: TriageIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            v = policy.can_approve(p.body, "D0", actor.role, actor.id, None, {})
            if v.result == "BLOCK":
                raise HTTPException(403, "; ".join(v.reasons))
            known = set(session.scalars(select(Evidence.evidence_id).where(Evidence.case_id == case_id)))
            if bad := sorted(set(body.evidence_ids) - known):
                raise HTTPException(422, f"unknown evidence {bad}")
            if body.observed_defect == "DEFECT_CONFIRMED" and not confirmed_defect_evidence(
                    session, case_id, body.evidence_ids):
                raise HTTPException(422, "DEFECT_CONFIRMED needs a cited human verification that confirms a defect; "
                                         "a statistical signal is not a confirmed defect")
            objs = session.scalars(select(AffectedObject).where(AffectedObject.case_id == case_id)).all()
            if body.scope_lots and not objs:
                raise HTTPException(409, "record the process context first; scope binds to its lots")
            if bad := sorted(set(body.scope_lots) - {o.object_id for o in objs if o.object_type == "LOT"}):
                raise HTTPException(422, f"unknown lots {bad}")
            shipped = any(o.parent_id in body.scope_lots and o.shipment_state == "SHIPPED" for o in objs)
            flags = {**body.risk_flags, "shipped_in_scope": shipped}
            if body.route == "NCR_ONLY" and body.observed_defect != "SIGNAL_ONLY" and (
                    shipped or flags.get("safety") or flags.get("customer_impact")):
                raise HTTPException(422, "NCR_ONLY is not allowed for a possible defect with shipped, customer or "
                                         "safety exposure; choose FULL_8D or EMERGENCY_FULL_8D")
            t = TriageAssessment(case_id=case_id, signal_kind=body.signal_kind, observed_defect=body.observed_defect,
                                 risk_flags=flags, scope_lots=body.scope_lots, route=body.route,
                                 severity=body.severity, rationale=body.rationale, evidence_ids=body.evidence_ids,
                                 assessor_id=actor.id, policy_hash=p.policy_hash, created_at=now())
            session.add(t)
            session.flush()
            log(session, case_id, actor, "TRIAGED", f"{body.signal_kind} observed={body.observed_defect} "
                f"route={body.route} severity={body.severity} shipped_in_scope={shipped}")
            return triage_out(t)

    @router.get("/cases/{case_id}/triage")
    def get_triage(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            return [triage_out(t) for t in session.scalars(select(TriageAssessment).where(
                TriageAssessment.case_id == case_id).order_by(TriageAssessment.id))]

    # --- D1 team (G3) ----------------------------------------------------------------------------------

    @router.post("/cases/{case_id}/team", status_code=201)
    def team_event(case_id: str, body: TeamIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            lead_role = p.body["required_roles"]["LEAD"]
            cur = team(session, case_id, p.body)["members"].get(body.responsibility)
            user = body.user_id
            if body.event in ("ASSIGN", "EXCEPTION") and actor.role != lead_role:
                raise HTTPException(403, f"only the {lead_role} (D1 lead role) assigns the team")
            if body.event == "EXCEPTION" and not body.note:
                raise HTTPException(422, "an exception needs a reason (missing skill, alternate plan)")
            if body.event == "ASSIGN":
                if user not in DEMO_USERS or not session.scalar(select(Assignment.id).where(
                        Assignment.case_id == case_id, Assignment.user_id == user)):
                    raise HTTPException(422, "assignee must be a user assigned to this case")
                need = p.body["required_roles"].get(body.responsibility)
                if need and DEMO_USERS[user][1] != need:
                    raise HTTPException(422, f"{body.responsibility} needs role {need}")
            elif body.event in ("ACCEPT", "DECLINE"):
                if cur is None or cur["user_id"] != actor.id or cur["status"] != "ASSIGNED":
                    raise HTTPException(409, "no open assignment of this responsibility to you")
                user = actor.id
            event = {"ASSIGN": "ASSIGNED", "ACCEPT": "ACCEPTED", "DECLINE": "DECLINED", "EXCEPTION": "EXCEPTION"}
            session.add(TeamEvent(case_id=case_id, responsibility=body.responsibility,
                                  user_id=None if body.event == "EXCEPTION" else user, event=event[body.event],
                                  due_at=body.due_at, note=body.note, actor_id=actor.id, created_at=now()))
            session.flush()
            log(session, case_id, actor, f"TEAM_{body.event}", f"{body.responsibility} {user or '-'} {body.note}")
            return team(session, case_id, p.body)

    @router.get("/cases/{case_id}/team")
    def get_team(case_id: str, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            return team(session, case_id, active_policy(session, case_id).body)

    # --- urgent containment and the shared action lifecycle (G3) ---------------------------------------

    @router.post("/cases/{case_id}/urgent-actions", status_code=201)
    def urgent_action(case_id: str, body: ActionIn, actor: Who) -> dict:
        """Emergency containment after D0, before D1/D2 are complete. Recorded as REQUESTED; execution and
        independent verification are separate events."""
        if not body.targets:
            raise HTTPException(422, "urgent containment needs at least one target")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            v = policy.can_execute_urgent(p.body, actor.role, stage_state(session, case_id), route(session, case_id))
            if v.result == "BLOCK":
                raise HTTPException(403, "; ".join(v.reasons))
            a = actions.create(session, case_id, "URGENT", body.action_type, body.description, body.targets,
                               actor.id, p.policy_hash)
            log(session, case_id, actor, "URGENT_ACTION_REQUESTED",
                f"#{a.id} {body.action_type} {','.join(body.targets)} gate={v.result} {'; '.join(v.reasons)}")
            return {**actions.out(session, a), "gate": v.out()}

    @router.post("/cases/{case_id}/actions", status_code=201)
    def containment_action(case_id: str, body: ActionIn, actor: Who) -> dict:
        """D3 containment action bound to the latest containment plan and to exact affected objects, or a D5
        corrective-action option tied to cause hypotheses (selection is a separate PLAN_APPROVED event)."""
        if body.stage == "D5":
            return corrective_option(case_id, body, actor)
        require_role(actor, "AUTHOR")
        if not body.targets:
            raise HTTPException(422, "a D3 action needs at least one target")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = session.scalar(select(DocumentVersion).where(
                DocumentVersion.case_id == case_id, DocumentVersion.doc_type == "CONTAINMENT")
                .order_by(DocumentVersion.version.desc()).limit(1))
            if doc is None or doc.status in ("REJECTED", "SUPERSEDED"):
                raise HTTPException(409, "D3 actions need a live containment plan document")
            p = active_policy(session, case_id)
            a = actions.create(session, case_id, "D3", body.action_type, body.description, body.targets, actor.id,
                               p.policy_hash, document_version_id=doc.id)
            log(session, case_id, actor, "D3_ACTION_PROPOSED",
                f"#{a.id} {body.action_type} {','.join(body.targets)} from CONTAINMENT v{doc.version}")
            return actions.out(session, a)

    def corrective_option(case_id: str, body: ActionIn, actor: Actor) -> dict:
        if actor.role not in ("AUTHOR", "PROCESS_ENGINEER"):
            raise HTTPException(403, "AUTHOR or PROCESS_ENGINEER role required")
        if not body.cause_ids:
            raise HTTPException(422, "a D5 corrective action must name the cause hypotheses it addresses")
        if missing := [k for k in effect.D5_DETAILS if len(body.details.get(k, "").strip()) < 5]:
            raise HTTPException(422, f"a D5 option needs {missing} (alternatives are compared on them)")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            for h in body.cause_ids:
                causes.get_hypothesis(session, case_id, h)
            p = active_policy(session, case_id)
            a = actions.create(session, case_id, "D5", body.action_type, body.description, body.targets, actor.id,
                               p.policy_hash, cause_ids=body.cause_ids, details=body.details)
            log(session, case_id, actor, "D5_OPTION_PROPOSED",
                f"#{a.id} {body.action_type} for H{','.join(map(str, body.cause_ids))}: {body.description[:120]}")
            return actions.out(session, a)

    @router.get("/cases/{case_id}/problem-definition")
    def problem_definition(case_id: str, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            return factcheck.problem_definition(session, case_id)

    @router.get("/cases/{case_id}/actions")
    def list_actions(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            return [actions.out(session, a) for a in session.scalars(
                select(Action).where(Action.case_id == case_id).order_by(Action.id))]

    @router.post("/cases/{case_id}/actions/{action_id}/events", status_code=201)
    def action_event(case_id: str, action_id: int, body: ActionEventIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            a = get_action(session, case_id, action_id)
            if body.event_type == "PLAN_APPROVED":
                check = PLAN_CHECKS.get(a.stage)
                if check is None:
                    raise HTTPException(422, f"{a.stage} actions have no plan approval step")
                check(session, a, actor)
            if body.event_type == "EXECUTED" and a.stage == "D5":
                effect.d6_execute_check(session, a)
            actions.record(session, a, body.event_type, actor.id, actor.role, active_policy(session, case_id),
                           body.note, body.evidence)
            log(session, case_id, actor, f"ACTION_{body.event_type}",
                f"#{a.id} {a.stage} {a.action_type} (SIMULATED) {body.note[:120]}")
            return actions.out(session, a)

    return router
