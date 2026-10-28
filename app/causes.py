"""D4 root cause as Hypothesis -> Experiment -> Decision (v5 structure C).

Hypotheses carry their 4M/6M branch and cause type (occurrence, non-detection, systemic), supporting and
counter evidence. Only a qualified person may record CONFIRMED, and only on a documented experiment that supports
the hypothesis, performed by someone else, on evidence fit to prove a cause. A SHAP ranking, a precedent, a model
claim or a statistical association never confirms a cause by itself: none of them is an experiment.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import quality
from app.db import (
    CausalDecision,
    CauseHypothesis,
    DocumentClaim,
    DocumentVersion,
    Evidence,
    Experiment,
    WhyLink,
)
from app.workflow import Actor, log, require_case

CATEGORIES = ("MAN", "MACHINE", "MATERIAL", "METHOD", "MEASUREMENT", "ENVIRONMENT")  # 6M; 4M = first four
CAUSE_TYPES = ("OCCURRENCE", "NON_DETECTION", "SYSTEMIC")


def now() -> str:
    return datetime.now(UTC).isoformat()


def latest_decision(session: Session, hypothesis_id: int) -> CausalDecision | None:
    return session.scalar(select(CausalDecision).where(CausalDecision.hypothesis_id == hypothesis_id)
                          .order_by(CausalDecision.id.desc()).limit(1))


def status(session: Session, hypothesis_id: int) -> str:
    d = latest_decision(session, hypothesis_id)
    return "OPEN" if d is None or d.decision == "REOPENED" else d.decision


def confirmed(session: Session, case_id: str) -> list[CauseHypothesis]:
    hs = session.scalars(select(CauseHypothesis).where(CauseHypothesis.case_id == case_id)
                         .order_by(CauseHypothesis.id)).all()
    return [h for h in hs if status(session, h.id) == "CONFIRMED"]


def experiments(session: Session, hypothesis_id: int) -> list[Experiment]:
    return list(session.scalars(select(Experiment).where(Experiment.hypothesis_id == hypothesis_id)
                                .order_by(Experiment.id)))


def get_hypothesis(session: Session, case_id: str, hypothesis_id: int) -> CauseHypothesis:
    h = session.get(CauseHypothesis, hypothesis_id)
    if h is None or h.case_id != case_id:
        raise HTTPException(404, "hypothesis not found")
    return h


def _known(session: Session, case_id: str, ids: list[str]) -> None:
    known = set(session.scalars(select(Evidence.evidence_id).where(Evidence.case_id == case_id)))
    if bad := sorted(set(ids) - known):
        raise HTTPException(422, f"unknown evidence {bad}")


def confirm_blocks(session: Session, h: CauseHypothesis, basis: list[Experiment], actor: Actor,
                   counter_response: str) -> list[str]:
    """Why CONFIRMED may not be recorded; empty means it may."""
    blocks = []
    if not basis:
        blocks.append("CONFIRMED needs at least one documented experiment; association, SHAP, a precedent or a "
                      "model claim is not an experiment")
    for e in basis:
        if e.result != "SUPPORTS":
            blocks.append(f"experiment #{e.id} result is {e.result}, not SUPPORTS")
        if e.performed_by == actor.id:
            blocks.append(f"experiment #{e.id} was performed by {actor.id}; the decision needs an independent reviewer")
    last = latest_decision(session, h.id)
    if last is not None and last.decision == "REOPENED" and not any(e.created_at > last.created_at for e in basis):
        blocks.append(f"H{h.id} was reopened ({last.rationale}); re-confirming needs an experiment run after that")
    against = [e.id for e in experiments(session, h.id) if e.result == "CONTRADICTS"]
    if against:
        blocks.append(f"experiments {against} contradict this hypothesis; record REJECTED or INCONCLUSIVE, or "
                      "test a narrower hypothesis")
    if h.counter_evidence_ids and len(counter_response.strip()) < 20:
        blocks.append(f"counter evidence {h.counter_evidence_ids} is not addressed (counter_evidence_response)")
    ids = list(dict.fromkeys([*h.evidence_ids, *(i for e in basis for i in e.evidence_ids)]))
    unfit, _ = quality.check_use(session, h.case_id, ids, "ROOT_CAUSE")
    return blocks + unfit


def hypothesis_out(session: Session, h: CauseHypothesis) -> dict:
    d = latest_decision(session, h.id)
    return {"hypothesis_id": h.id, "cause_type": h.cause_type, "category": h.category, "text": h.text,
            "evidence_ids": h.evidence_ids, "counter_evidence_ids": h.counter_evidence_ids, "origin": h.origin,
            "source_claim": h.source_claim, "created_by": h.created_by, "created_at": h.created_at,
            "status": status(session, h.id),
            "decision": None if d is None else {"decision": d.decision, "actor_id": d.actor_id,
                                                "basis_experiment_ids": d.basis_experiment_ids,
                                                "rationale": d.rationale, "at": d.created_at},
            "experiments": [experiment_out(e) for e in experiments(session, h.id)]}


def experiment_out(e: Experiment) -> dict:
    return {"experiment_id": e.id, "hypothesis_id": e.hypothesis_id, "method": e.method,
            "controlled_conditions": e.controlled_conditions, "baseline": e.baseline,
            "intervention": e.intervention, "sample_size": e.sample_size, "acceptance_rule": e.acceptance_rule,
            "evidence_ids": e.evidence_ids, "result": e.result, "performed_by": e.performed_by,
            "execution_mode": "SIMULATED" if e.synthetic else "RECORDED", "created_at": e.created_at}


class HypothesisIn(BaseModel):
    cause_type: Literal[CAUSE_TYPES]
    category: Literal[CATEGORIES]
    text: str = Field(min_length=10, max_length=1000)
    evidence_ids: list[str] = []
    counter_evidence_ids: list[str] = []
    origin: Literal["HUMAN", "RCA_DRAFT", "AI_PROPOSED", "SHAP", "PRECEDENT"] = "HUMAN"
    source_claim: str | None = Field(default=None, pattern=r"^RCA v\d+:C\d+$")


class WhyIn(BaseModel):
    parent_id: int
    child_id: int
    supporting_ids: list[str] = Field(min_length=1)
    falsification_criteria: str = Field(min_length=10, max_length=500)


class ExperimentIn(BaseModel):
    hypothesis_id: int
    method: str = Field(min_length=10, max_length=1000)
    controlled_conditions: list[str] = Field(min_length=1)
    baseline: dict = Field(min_length=1)
    intervention: dict = Field(min_length=1)
    sample_size: int = Field(ge=2)
    acceptance_rule: str = Field(min_length=10, max_length=500)  # stated before the result
    evidence_ids: list[str] = Field(min_length=1)
    result: Literal["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"]


class DecisionIn(BaseModel):
    hypothesis_id: int
    decision: Literal["CONFIRMED", "REJECTED", "INCONCLUSIVE"]
    basis_experiment_ids: list[int] = []
    rationale: str = Field(min_length=10, max_length=1000)
    counter_evidence_response: str = Field(default="", max_length=1000)


def make_d4_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    # eightd builds on workflow too; imported late to keep one direction
    from app.eightd import active_policy

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.post("/cases/{case_id}/hypotheses", status_code=201)
    def add_hypothesis(case_id: str, body: HypothesisIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            _known(session, case_id, body.evidence_ids + body.counter_evidence_ids)
            if body.source_claim:
                ver, cid = body.source_claim.removeprefix("RCA v").split(":")
                claim = session.scalar(select(DocumentClaim).join(DocumentVersion).where(
                    DocumentVersion.case_id == case_id, DocumentVersion.doc_type == "RCA",
                    DocumentVersion.version == int(ver), DocumentClaim.claim_id == cid))
                if claim is None or claim.classification != "HYPOTHESIS":
                    raise HTTPException(422, f"{body.source_claim} is not a HYPOTHESIS claim of this case's RCA")
            h = CauseHypothesis(case_id=case_id, created_by=actor.id, created_at=now(), **body.model_dump())
            session.add(h)
            session.flush()
            log(session, case_id, actor, "D4_HYPOTHESIS", f"H{h.id} {h.category}/{h.cause_type} origin={h.origin}: "
                f"{h.text[:120]}")
            return hypothesis_out(session, h)

    @router.get("/cases/{case_id}/hypotheses")
    def list_hypotheses(case_id: str, actor: Who) -> dict:
        """Hypotheses with status, plus the Fishbone (6M branch x cause type) and 5-Why links over them."""
        with sessions() as session:
            require_case(session, case_id, actor)
            hs = [hypothesis_out(session, h) for h in session.scalars(
                select(CauseHypothesis).where(CauseHypothesis.case_id == case_id).order_by(CauseHypothesis.id))]
            fishbone = {c: [{"hypothesis_id": h["hypothesis_id"], "cause_type": h["cause_type"],
                             "status": h["status"], "text": h["text"]} for h in hs if h["category"] == c]
                        for c in CATEGORIES}
            whys = [{"why_id": w.id, "parent_id": w.parent_id, "child_id": w.child_id,
                     "supporting_ids": w.supporting_ids, "falsification_criteria": w.falsification_criteria}
                    for w in session.scalars(select(WhyLink).where(WhyLink.case_id == case_id).order_by(WhyLink.id))]
            return {"hypotheses": hs, "fishbone": fishbone, "why_links": whys,
                    "confirmed": [h["hypothesis_id"] for h in hs if h["status"] == "CONFIRMED"]}

    @router.post("/cases/{case_id}/why-links", status_code=201)
    def add_why(case_id: str, body: WhyIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            get_hypothesis(session, case_id, body.parent_id)
            get_hypothesis(session, case_id, body.child_id)
            if body.parent_id == body.child_id:
                raise HTTPException(422, "a why-link joins two different hypotheses")
            _known(session, case_id, body.supporting_ids)
            blocks, _ = quality.check_use(session, case_id, body.supporting_ids, "OBSERVATION")
            if blocks:
                raise HTTPException(422, "; ".join(blocks))
            w = WhyLink(case_id=case_id, created_by=actor.id, created_at=now(), **body.model_dump())
            session.add(w)
            session.flush()
            log(session, case_id, actor, "D4_WHY_LINK", f"H{w.parent_id} because H{w.child_id}")
            return {"why_id": w.id, **body.model_dump()}

    @router.post("/cases/{case_id}/experiments", status_code=201)
    def add_experiment(case_id: str, body: ExperimentIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            h = get_hypothesis(session, case_id, body.hypothesis_id)
            if status(session, h.id) in ("CONFIRMED", "REJECTED"):
                raise HTTPException(409, f"H{h.id} is {status(session, h.id)}; reopen it before adding experiments")
            _known(session, case_id, body.evidence_ids)
            e = Experiment(case_id=case_id, performed_by=actor.id, synthetic=True, created_at=now(),
                           **body.model_dump())
            session.add(e)
            session.flush()
            log(session, case_id, actor, "D4_EXPERIMENT",
                f"E{e.id} on H{h.id} n={e.sample_size} result={e.result} (SIMULATED)")
            return experiment_out(e)

    @router.post("/cases/{case_id}/causal-decisions", status_code=201)
    def decide(case_id: str, body: DecisionIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            p = active_policy(session, case_id)
            need = p.body["approval_gates"]["D4"]["approver"]
            if actor.role != need:
                raise HTTPException(403, f"D4 cause decisions need role {need}")
            h = get_hypothesis(session, case_id, body.hypothesis_id)
            if status(session, h.id) == body.decision:
                raise HTTPException(409, f"H{h.id} is already {body.decision}")
            own = {e.id: e for e in experiments(session, h.id)}
            if bad := sorted(set(body.basis_experiment_ids) - set(own)):
                raise HTTPException(422, f"experiments {bad} are not experiments on H{h.id}")
            basis = [own[i] for i in body.basis_experiment_ids]
            if body.decision == "CONFIRMED":
                if blocks := confirm_blocks(session, h, basis, actor, body.counter_evidence_response):
                    raise HTTPException(409, "; ".join(blocks))
            elif body.decision == "REJECTED" and not basis:
                raise HTTPException(422, "REJECTED needs the experiment(s) it rests on; use INCONCLUSIVE otherwise")
            d = CausalDecision(case_id=case_id, hypothesis_id=h.id, decision=body.decision,
                               basis_experiment_ids=body.basis_experiment_ids,
                               rationale=body.rationale + (f" | counter evidence: {body.counter_evidence_response}"
                                                           if body.counter_evidence_response else ""),
                               actor_id=actor.id, policy_hash=p.policy_hash, created_at=now())
            session.add(d)
            session.flush()
            log(session, case_id, actor, f"D4_{body.decision}",
                f"H{h.id} basis={body.basis_experiment_ids} policy={p.policy_hash}: {body.rationale[:120]}")
            return hypothesis_out(session, h)

    return router
