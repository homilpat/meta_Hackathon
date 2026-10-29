"""D5 corrective-action selection and D6 effectiveness (G6).

D5 options are `actions` rows (stage D5) tied to cause hypotheses; selecting one (PLAN_APPROVED) needs every
cause CONFIRMED. D6 is separate: execution needs an effectiveness plan registered before it, the comparison is
computed by the server from the source rows (never typed in), and a reviewer may only record EFFECTIVE when the
precommitted criteria are met. A NOT_EFFECTIVE result reopens the causes it rested on; nothing is deleted.
"""

import math
from collections.abc import Callable
from datetime import UTC, datetime
from statistics import mean, stdev
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import actions, causes, ncr, quality
from app.db import Action, CausalDecision, EffectivenessPlan, EffectivenessResult
from app.fields import FreeText, text
from app.workflow import Actor, log, require_case

D5_DETAILS = ("feasibility", "risk_analysis", "side_effects")
METRICS = {"SPI_MEAN_VOLUME_MM3": "spi_measurements", "AOI_CONFIRMED_DEFECT_RATE": "aoi_inspections"}
SELECTED = ("PLAN_APPROVED", "EXECUTED", "INDEPENDENTLY_VERIFIED")


def now() -> str:
    return datetime.now(UTC).isoformat()


def d5_actions(session: Session, case_id: str) -> list[Action]:
    return list(session.scalars(select(Action).where(Action.case_id == case_id, Action.stage == "D5")
                                .order_by(Action.id)))


def executed_at(session: Session, action_id: int) -> str | None:
    return next((e.occurred_at for e in actions.events(session, action_id) if e.event_type == "EXECUTED"), None)


def stage_states(session: Session, case_id: str) -> tuple[str | None, str | None]:
    """(D5, D6). D5 DONE: every confirmed cause has a selected action. D6 DONE: every selected action is
    independently verified effective. A NOT_EFFECTIVE action keeps D6 at NOT_EFFECTIVE until replaced."""
    acts = [(a, actions.status(session, a.id)) for a in d5_actions(session, case_id)]
    if not acts:
        return None, None
    live = [(a, s) for a, s in acts if s in SELECTED]
    covered = {c for a, _ in live for c in a.cause_ids}
    confirmed = {h.id for h in causes.confirmed(session, case_id)}
    d5 = "DONE" if confirmed and confirmed <= covered else ("PARTIAL" if live else "PROPOSED")
    started = [s for _, s in acts if s not in ("REQUESTED", "PLAN_APPROVED", "CANCELLED")]
    if not started:
        return d5, None
    if any(s == "NOT_EFFECTIVE" for _, s in acts) and not (d5 == "DONE" and all(
            s == "INDEPENDENTLY_VERIFIED" for _, s in live)):
        return d5, "NOT_EFFECTIVE"
    done = d5 == "DONE" and all(s == "INDEPENDENTLY_VERIFIED" for _, s in live)
    return d5, "DONE" if done else "IN_PROGRESS"


def d5_select_check(session: Session, a: Action, actor: Actor) -> None:
    """D5 selection (PLAN_APPROVED): the policy's D5 approver; every cause CONFIRMED; risk analysis on record."""
    from app.eightd import active_policy

    need = active_policy(session, a.case_id).body["approval_gates"]["D5"]["approver"]
    if actor.role != need:
        raise HTTPException(403, f"D5 selection needs role {need}")
    if not a.cause_ids:
        raise HTTPException(409, "a corrective action must address at least one cause")
    open_ = [f"H{c} is {causes.status(session, c)}" for c in a.cause_ids if causes.status(session, c) != "CONFIRMED"]
    if open_:
        raise HTTPException(409, f"D5 can only select an action for CONFIRMED causes: {', '.join(open_)}")
    if missing := [k for k in D5_DETAILS if not str((a.details or {}).get(k, "")).strip()]:
        raise HTTPException(409, f"D5 selection needs {missing} on the action")


def d6_execute_check(session: Session, a: Action) -> None:
    if not session.scalar(select(EffectivenessPlan.id).where(EffectivenessPlan.action_id == a.id).limit(1)):
        raise HTTPException(409, "D6 execution needs an effectiveness plan registered before it (precommitted)")


# --- deterministic comparison ----------------------------------------------------------------------------

def _samples(session: Session, plan: EffectivenessPlan, start: str) -> tuple[dict, dict, list[str]]:
    """(baseline, post) as {"values": [...], "excluded": {...}} plus reasons the comparison is not like-for-like."""
    kind = METRICS[plan.metric]
    items = ncr.current(ncr._evidence(session, plan.case_id))
    lot_of = {i["rec"]["panel_id"]: i["rec"]["lot_id"] for i in items if i["type"] == "panels"}
    rows = [i for i in items if i["type"] == kind]
    states = quality.current(session, plan.case_id, {i["ev"] for i in rows})
    reasons = []
    for k, v in plan.inspection_conditions.items():
        seen = sorted({str(i["rec"].get(k)) for i in rows})
        if seen != [str(v)]:
            reasons.append(f"inspection condition {k}={v} does not hold for every row (seen {seen})")
    confirmed = {(i["rec"]["panel_id"], i["rec"]["board_id"]) for i in items if i["type"] == "human_verifications"
                 and i["rec"]["result"] == "DEFECT_CONFIRMED"}

    def window(pick: Callable[[dict], bool]) -> dict:
        chosen = [i for i in rows if pick(i)]
        ok = [i for i in chosen if quality.suitable(states[i["ev"]]["quality_state"], "EFFECTIVENESS") == "PASS"]
        if kind == "spi_measurements":
            values = [i["rec"]["volume_mm3"] for i in ok]
        else:
            values = [1.0 if (i["rec"]["panel_id"], i["rec"]["board_id"]) in confirmed else 0.0 for i in ok]
        return {"values": values, "evidence_ids": [i["ev"] for i in ok],
                "excluded_not_valid": len(chosen) - len(ok)}

    base = window(lambda i: lot_of.get(i["rec"]["panel_id"]) in plan.baseline_lots)
    post = window(lambda i: lot_of.get(i["rec"]["panel_id"]) not in plan.baseline_lots
                  and i["rec"]["event_time"] >= start
                  and (plan.post_to is None or i["rec"]["event_time"] <= plan.post_to))
    return base, post, reasons


def _summary(values: list[float]) -> dict:
    n = len(values)
    return {"n": n, "mean": round(mean(values), 5) if n else None,
            "sd": round(stdev(values), 5) if n > 1 else None}


def evaluate(session: Session, plan: EffectivenessPlan) -> tuple[str, dict, list[str]]:
    """MEETS_CRITERIA only if: executed, plan precommitted, like-for-like inspection, enough VALID rows on both
    sides, the post value passes the acceptance rule and the change is outside its ~95% interval."""
    done = executed_at(session, plan.action_id)
    reasons = []
    if done is None:
        return "INCONCLUSIVE", {}, ["action not executed"]
    if plan.created_at > done:
        reasons.append("plan registered after execution: criteria were not precommitted")
    if plan.post_from and plan.post_from < done:
        reasons.append("post window starts before the action was executed")
    base, post, unlike = _samples(session, plan, plan.post_from or done)
    reasons += unlike
    b, p = _summary(base["values"]), _summary(post["values"])
    observed = {"metric": plan.metric, "baseline": {**b, "lots": plan.baseline_lots,
                                                    "excluded_not_valid": base["excluded_not_valid"]},
                "post": {**p, "from": plan.post_from or done, "to": plan.post_to,
                         "excluded_not_valid": post["excluded_not_valid"]},
                "acceptance": plan.acceptance, "executed_at": done,
                "evidence_ids": base["evidence_ids"] + post["evidence_ids"]}
    if min(b["n"], p["n"]) < plan.min_sample:
        reasons.append(f"sample too small: baseline n={b['n']}, post n={p['n']}, minimum {plan.min_sample}")
    if reasons:
        return "INCONCLUSIVE", observed, reasons
    diff = p["mean"] - b["mean"]
    if plan.metric == "SPI_MEAN_VOLUME_MM3":
        se = math.sqrt((b["sd"] or 0) ** 2 / b["n"] + (p["sd"] or 0) ** 2 / p["n"])
    else:  # two proportions
        se = math.sqrt(b["mean"] * (1 - b["mean"]) / b["n"] + p["mean"] * (1 - p["mean"]) / p["n"])
    ci = (round(diff - 1.96 * se, 5), round(diff + 1.96 * se, 5))
    observed["difference"] = {"post_minus_baseline": round(diff, 5), "ci95": ci}
    op, value = plan.acceptance["op"], plan.acceptance["value"]
    passes = p["mean"] >= value if op == ">=" else p["mean"] <= value
    if not passes:
        return "FAILS_CRITERIA", observed, [f"post {plan.metric} {p['mean']} does not satisfy {op} {value}"]
    improved = ci[0] > 0 if op == ">=" else ci[1] < 0
    if not improved:
        return "INCONCLUSIVE", observed, [f"change {round(diff, 5)} is within its 95% interval {ci}"]
    return "MEETS_CRITERIA", observed, []


# --- routes ------------------------------------------------------------------------------------------------

class PlanIn(BaseModel):
    action_id: int
    metric: Literal[tuple(METRICS)]
    baseline_lots: list[str] = Field(min_length=1)
    post_from: datetime | None = None  # default: the window opens when the action is executed
    post_to: datetime | None = None
    min_sample: int = Field(ge=10)
    acceptance: dict  # {"op": ">=" | "<=", "value": float}
    inspection_conditions: dict[str, str] = Field(min_length=1)
    monitoring: text(10, 500)


class EffectIn(BaseModel):
    plan_id: int
    decision: Literal["EFFECTIVE", "NOT_EFFECTIVE", "INCONCLUSIVE"]
    note: FreeText


def plan_out(p: EffectivenessPlan) -> dict:
    return {"plan_id": p.id, "action_id": p.action_id, "metric": p.metric, "baseline_lots": p.baseline_lots,
            "post_from": p.post_from, "post_to": p.post_to, "min_sample": p.min_sample, "acceptance": p.acceptance,
            "inspection_conditions": p.inspection_conditions, "monitoring": p.monitoring,
            "created_by": p.created_by, "precommitted_at": p.created_at}


def result_out(r: EffectivenessResult) -> dict:
    return {"result_id": r.id, "plan_id": r.plan_id, "action_id": r.action_id, "computed": r.computed,
            "observed": r.observed, "reasons": r.reasons, "decision": r.decision, "reviewer_id": r.reviewer_id,
            "note": r.note, "at": r.created_at, "data_origin": "SYNTHETIC"}


def make_d6_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    from app.eightd import active_policy, get_action

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.post("/cases/{case_id}/effectiveness-plans", status_code=201)
    def add_plan(case_id: str, body: PlanIn, actor: Who) -> dict:
        if actor.role not in ("REVIEWER", "PROCESS_ENGINEER"):
            raise HTTPException(403, "REVIEWER or PROCESS_ENGINEER role required")
        if body.acceptance.get("op") not in (">=", "<=") or not isinstance(body.acceptance.get("value"),
                                                                           int | float):
            raise HTTPException(422, 'acceptance must be {"op": ">=" | "<=", "value": number}')
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            a = get_action(session, case_id, body.action_id)
            if a.stage != "D5":
                raise HTTPException(422, "effectiveness plans belong to D5 corrective actions")
            st = actions.status(session, a.id)
            if st != "PLAN_APPROVED":
                raise HTTPException(409, f"criteria must be registered after selection and before execution "
                                         f"(action is {st})")
            p = EffectivenessPlan(case_id=case_id, created_by=actor.id, created_at=now(),
                                  **{**body.model_dump(),
                                     "post_from": body.post_from.isoformat() if body.post_from else None,
                                     "post_to": body.post_to.isoformat() if body.post_to else None})
            session.add(p)
            session.flush()
            log(session, case_id, actor, "D6_PLAN", f"#{p.id} for action #{a.id}: {p.metric} {p.acceptance} "
                f"min n={p.min_sample} baseline={p.baseline_lots}")
            return plan_out(p)

    @router.post("/cases/{case_id}/effectiveness", status_code=201)
    def decide(case_id: str, body: EffectIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            pol = active_policy(session, case_id)
            need = pol.body["approval_gates"]["D6"]["approver"]
            if actor.role != need:
                raise HTTPException(403, f"D6 effectiveness decisions need role {need}")
            plan = session.get(EffectivenessPlan, body.plan_id)
            if plan is None or plan.case_id != case_id:
                raise HTTPException(404, "plan not found")
            a = get_action(session, case_id, plan.action_id)
            if actions.status(session, a.id) != "EXECUTED":
                raise HTTPException(409, f"effectiveness is decided on an EXECUTED action "
                                         f"(is {actions.status(session, a.id)})")
            computed, observed, reasons = evaluate(session, plan)
            if body.decision == "EFFECTIVE" and computed != "MEETS_CRITERIA":
                raise HTTPException(409, f"EFFECTIVE needs the precommitted criteria met; computed {computed}: "
                                         + "; ".join(reasons))
            r = EffectivenessResult(case_id=case_id, plan_id=plan.id, action_id=a.id, computed=computed,
                                    observed=observed, reasons=reasons, decision=body.decision,
                                    reviewer_id=actor.id, note=body.note, created_at=now())
            session.add(r)
            session.flush()
            if body.decision == "EFFECTIVE":
                actions.record(session, a, "INDEPENDENTLY_VERIFIED", actor.id, actor.role, pol, body.note,
                               [f"EFF-{r.id}"])
            elif body.decision == "NOT_EFFECTIVE":
                actions.record(session, a, "NOT_EFFECTIVE", actor.id, actor.role, pol, body.note, [f"EFF-{r.id}"])
                for h in a.cause_ids:  # the cause it rested on is open again; its earlier decisions stay
                    session.add(CausalDecision(case_id=case_id, hypothesis_id=h, decision="REOPENED",
                                               basis_experiment_ids=[], actor_id=actor.id,
                                               rationale=f"D6 result #{r.id} NOT_EFFECTIVE for action #{a.id}",
                                               policy_hash=pol.policy_hash, created_at=now()))
                    log(session, case_id, actor, "D4_REOPENED", f"H{h}: action #{a.id} not effective (result #{r.id})")
            log(session, case_id, actor, f"D6_{body.decision}",
                f"result #{r.id} action #{a.id} computed={computed} {'; '.join(reasons)[:200]}")
            return result_out(r)

    @router.get("/cases/{case_id}/effectiveness")
    def list_effectiveness(case_id: str, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            plans = session.scalars(select(EffectivenessPlan).where(EffectivenessPlan.case_id == case_id)
                                    .order_by(EffectivenessPlan.id)).all()
            results = session.scalars(select(EffectivenessResult).where(EffectivenessResult.case_id == case_id)
                                      .order_by(EffectivenessResult.id)).all()
            d5, d6 = stage_states(session, case_id)
            return {"plans": [plan_out(p) for p in plans], "results": [result_out(r) for r in results],
                    "preview": {p.id: dict(zip(("computed", "observed", "reasons"), evaluate(session, p)))
                                for p in plans}, "D5": d5, "D6": d6}

    return router
