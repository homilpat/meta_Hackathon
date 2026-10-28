"""v5 D0-D8 engine routes. New decision entry points consult the versioned WorkflowPolicy; the S6 document
routes in workflow.py keep their own chain unchanged (backwards compatible)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import policy, process, quality
from app.db import AffectedObject, DocumentVersion, ProcessContext, WorkflowPolicy
from app.workflow import KINDS, STEP, Actor, log, require_case, require_role


def now() -> str:
    return datetime.now(UTC).isoformat()


def stage_state(session: Session, case_id: str) -> dict[str, str | None]:
    """Status per 8D stage. D2-D4 come from the S6 documents; later gates add their own entities."""
    state: dict[str, str | None] = dict.fromkeys(policy.STAGES)
    for doc_type in KINDS.values():
        doc = session.scalar(select(DocumentVersion).where(
            DocumentVersion.case_id == case_id, DocumentVersion.doc_type == doc_type)
            .order_by(DocumentVersion.version.desc()).limit(1))
        state[STEP[doc_type]] = doc.status if doc else None
    return state


def case_ctx(session: Session, case_id: str) -> dict:
    pc = session.scalar(select(ProcessContext).where(ProcessContext.case_id == case_id))
    return {"site": pc.site, "customer": pc.customer, "process_type": pc.process_type} if pc else {}


class PolicyIn(BaseModel):
    policy_id: str = Field(min_length=2, max_length=60, pattern=r"^[A-Z0-9_\-]+$")
    applicability: dict[str, str] = {}
    body: dict


class QualityIn(BaseModel):
    evidence_id: str
    quality_state: Literal["VALID", "UNVERIFIED", "SUSPECT", "CONFLICTED", "SUPERSEDED"]
    reason: str = Field(min_length=5, max_length=500)


class ProcessIn(BaseModel):
    site: str = Field(min_length=1, max_length=40)
    customer: str = Field(default="DEFAULT", min_length=1, max_length=60)
    process_type: str = "PCB_SMT"


def make_v5_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

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
            p = policy.active(session, case_ctx(session, case_id))
            state = stage_state(session, case_id)
            body = p.body
            return {"policy": policy.ref(p), "state": state,
                    "draft": {s: policy.can_draft(body, s, state).out() for s in body["draft_requirements"]},
                    "approve": {s: policy.can_approve(body, s, actor.role, actor.id, None, state).out()
                                for s in body["approval_gates"]},
                    "urgent_containment": policy.can_execute_urgent(body, actor.role, state, None).out()}

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

    return router
