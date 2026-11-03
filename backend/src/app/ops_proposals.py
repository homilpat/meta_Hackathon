"""Operating-limit proposals (spec v5.14 §29 AI-CFG-04). The server summarizes recent investigation runs (status,
rounds, tool calls, seconds, cost, which cap stopped them); Meta proposes changes to the tunable limits only, as
JSON; the server checks each value with the limits' own rules and computes from the same recorded runs what the
value would have changed (runs cut or rescued, cost); a person with AGENT_ADMIN approves or rejects, and an approved
change goes through the same path as POST /limits/{name} (append-only history). The model never writes a setting.
"""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import limits
from app.fields import FreeText

# what Meta may propose, and the run measure each one bounds
TUNABLE = {"INVESTIGATION_MAX_REPAIRS": "repairs", "INVESTIGATION_MAX_ROUNDS": "rounds",
           "INVESTIGATION_MAX_TOOL_CALLS": "tool_calls", "INVESTIGATION_DEADLINE_S": "seconds",
           "INVESTIGATION_MAX_COST_USD": "cost_usd"}
RECENT_RUNS = 200  # DEFAULT: investigation runs the statistics are taken over (newest first)


def runs(session: Session) -> list[dict]:
    """The recent investigation runs as measures: what each used and how it ended."""
    from app.db import ModelRun, ToolCall

    tools = dict(session.execute(select(ToolCall.model_run_id, func.count()).group_by(ToolCall.model_run_id)).all())
    price = limits.get("MODEL_PRICE_INPUT_PER_M_USD"), limits.get("MODEL_PRICE_OUTPUT_PER_M_USD")
    out = []
    for r in session.scalars(select(ModelRun).order_by(ModelRun.id.desc()).limit(RECENT_RUNS)):
        try:
            secs = (datetime.fromisoformat(r.finished_at) - datetime.fromisoformat(r.started_at)).total_seconds()
        except (TypeError, ValueError):
            secs = None
        out.append({"id": r.id, "status": r.status, "rounds": r.rounds, "tool_calls": tools.get(r.id, 0),
                    "repairs": max(0, len(r.attempts or []) - 1), "seconds": secs, "error": (r.error or "")[:200],
                    "cost_usd": round((r.prompt_tokens * price[0] + r.completion_tokens * price[1]) / 1e6, 5)})
    return out


def stopped_by(x: dict, name: str, cap) -> bool:
    """Did this cap end the run? A repair cap: still refused after the last allowed repair. Any other cap: the server
    stopped the run as LIMIT_EXCEEDED having used it all. A run that failed for another reason (a refused report,
    a JSON error) does not count, however much it used."""
    m = TUNABLE[name]
    if not cap or x[m] is None or x[m] < cap:
        return False
    return x["status"] == "VALIDATION_FAILED" if m == "repairs" else x["status"] == "LIMIT_EXCEEDED"


def stats(rs: list[dict]) -> dict:
    """Counts and distributions only (no case content): what the model may see."""
    def dist(k):
        xs = sorted(x[k] for x in rs if x[k] is not None)
        if not xs:
            return None
        return {"min": xs[0], "median": xs[len(xs) // 2], "p90": xs[int(len(xs) * 0.9) - 1 if len(xs) > 1 else 0],
                "max": xs[-1]}
    status: dict[str, int] = {}
    for x in rs:
        status[x["status"]] = status.get(x["status"], 0) + 1
    at_cap = {name: sum(stopped_by(x, name, limits.get(name)) for x in rs) for name in TUNABLE}
    return {"runs": len(rs), "status": status, "distributions": {m: dist(m) for m in set(TUNABLE.values())},
            "stopped_by_cap": at_cap,
            "repair_outcomes": {"needed_repair": sum(x["repairs"] > 0 for x in rs),
                                "validated_after_repair": sum(x["repairs"] > 0 and x["status"] == "VALIDATED"
                                                              for x in rs)}}


def compare(rs: list[dict], name: str, value) -> dict:
    """What the value would have done on the recorded runs: runs it would cut (they used more), runs stopped at the
    current cap that it would let continue, and the cost of the runs it would cut. A replay, not a promise."""
    m, cur = TUNABLE[name], limits.get(name)
    used = [x for x in rs if x[m] is not None]
    off = value == 0 and name in limits.OFF_ALLOWED  # 0 = no cap
    cut = [] if off else [x for x in used if x[m] > value]
    freed = [x for x in used if stopped_by(x, name, cur) and (off or value > cur)]
    return {"measure": m, "current": cur, "proposed": value, "runs_compared": len(used),
            "would_cut": len(cut), "would_cut_validated": sum(x["status"] == "VALIDATED" for x in cut),
            "stopped_at_current_cap": len(freed), "cost_of_cut_runs_usd": round(sum(x["cost_usd"] for x in cut), 4),
            "note": "a run cut by a lower cap ends as LIMIT_EXCEEDED; a run stopped at the current cap may or may "
                    "not succeed with more room"}


PROMPT = """You review the operating limits of an investigation assistant from statistics of its recent runs.
Propose at most three changes to the listed limits only, each with a number and a one-sentence reason grounded in
the statistics (e.g. runs the server stopped at a cap: stopped_by_cap; or a cap far above what runs use that could
be lower to bound cost and time). A run that failed for another reason is not evidence about a cap.
Propose nothing when the statistics do not support a change. A person approves or rejects each proposal."""


def schema() -> dict:
    return {"type": "json_schema", "json_schema": {"name": "limit_proposals", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["proposals"],
        "properties": {"proposals": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "value", "reason"],
            "properties": {"name": {"type": "string", "enum": list(TUNABLE)}, "value": {"type": "number"},
                           "reason": {"type": "string"}}}}}}}}


def ask_model(provider, rs: list[dict]) -> tuple[dict, dict, dict]:
    """(statistics, reply, usage). Called outside any transaction: the provider may write its response cache."""
    from app.model_provider import ProviderError

    st = stats(rs)
    current = {n: {"value": limits.get(n), "unit": limits.LIMITS[n].unit, "basis": limits.LIMITS[n].basis}
               for n in TUNABLE}
    if provider is None:
        raise HTTPException(503, "Meta 미연결: 제안을 받을 수 없습니다 (설정은 직접 바꿀 수 있습니다)")
    try:
        r = provider.chat([{"role": "system", "content": PROMPT},
                           {"role": "user", "content": json.dumps({"limits": current, "statistics": st})}], [],
                          response_format=schema())
        reply = json.loads(r["message"].get("content") or "")
    except (ProviderError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, f"AI 제안 실패 ({type(exc).__name__}): 설정은 직접 바꿀 수 있습니다") from None
    return st, reply, r.get("usage") or {}


def store(session: Session, rs: list[dict], st: dict, reply: dict, usage: dict, provider, actor) -> list[dict]:
    """Each proposed value checked by the limit's own rules and replayed on the runs; stored for a person."""
    from app.db import LimitProposal
    from app.workflow import now

    snapshot = hashlib.sha256(json.dumps(st, sort_keys=True).encode()).hexdigest()[:16]
    out = []
    for p in (reply.get("proposals") if isinstance(reply, dict) else None) or []:
        if not isinstance(p, dict) or p.get("name") not in TUNABLE:
            continue
        name, issue = p["name"], None
        try:
            value = limits.cast(name, str(int(p["value"]) if float(p["value"]).is_integer()
                                           and isinstance(limits.LIMITS[name].default, int) else p["value"]))
        except (HTTPException, ValueError, TypeError) as exc:
            value, issue = p.get("value"), getattr(exc, "detail", str(exc))
        if issue is None and value == limits.get(name):
            issue = "현재값과 같습니다"
        row = LimitProposal(name=name, current_value=str(limits.get(name)), proposed_value=str(value), scope="GLOBAL",
                            reason=str(p.get("reason", ""))[:500], statistics=st, snapshot_sha=snapshot,
                            comparison=compare(rs, name, value) if issue is None else {},
                            status="INVALID" if issue else "PROPOSED", issue=issue, mode=provider.mode,
                            model=provider.model, usage=usage, created_by=actor.id, created_at=now())
        session.add(row)
        session.flush()
        out.append(proposal_out(session, row))
    return out


def proposal_out(session: Session, p) -> dict:
    from app.db import LimitProposalDecision

    d = session.scalar(select(LimitProposalDecision).where(LimitProposalDecision.proposal_id == p.id)
                       .order_by(LimitProposalDecision.id.desc()).limit(1))
    return {"proposal_id": p.id, "name": p.name, "current": p.current_value, "proposed": p.proposed_value,
            "scope": p.scope, "reason": p.reason, "comparison": p.comparison, "statistics": p.statistics,
            "status": d.decision if d else p.status, "issue": p.issue, "mode": p.mode, "model": p.model,
            "created_at": p.created_at, "decision": {"by": d.actor_id, "reason": d.reason, "at": d.created_at} if d else None,
            "unit": limits.LIMITS[p.name].unit, "live_value": str(limits.get(p.name))}


class DecisionIn(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reason: FreeText


def make_ops_router(sessions: sessionmaker, current_user, provider=None) -> APIRouter:
    from app.db import LimitProposal, LimitProposalDecision
    from app.workflow import Actor, now

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    def admin(actor):
        if actor.role != limits.ADMIN_ROLE:
            raise HTTPException(403, f"only {limits.ADMIN_ROLE} (AI 운영 담당) reviews operating limits")

    @router.post("/limit-proposals", status_code=201)
    def ask(actor: Who) -> list[dict]:
        admin(actor)
        with sessions() as session:
            rs = runs(session)
        st, reply, usage = ask_model(provider, rs)  # outside any transaction
        with sessions.begin() as session:
            return store(session, rs, st, reply, usage, provider, actor)

    @router.get("/limit-proposals")
    def list_(actor: Who) -> list[dict]:
        with sessions() as session:
            return [proposal_out(session, p) for p in
                    session.scalars(select(LimitProposal).order_by(LimitProposal.id.desc()).limit(50))]

    @router.post("/limit-proposals/{proposal_id}/decision", status_code=201)
    def decide(proposal_id: int, body: DecisionIn, actor: Who) -> dict:
        admin(actor)
        with sessions.begin() as session:
            p = session.get(LimitProposal, proposal_id)
            if p is None:
                raise HTTPException(404, "Proposal not found")
            if proposal_out(session, p)["status"] != "PROPOSED":
                raise HTTPException(409, f"이미 처리된 제안입니다 ({proposal_out(session, p)['status']})")
            if body.decision == "APPROVED" and str(limits.get(p.name)) != p.current_value:
                raise HTTPException(409, f"제안 뒤에 현재값이 바뀌었습니다 ({p.current_value} -> {limits.get(p.name)}): "
                                         "새로 제안을 받으세요")
            session.add(LimitProposalDecision(proposal_id=p.id, decision=body.decision, reason=body.reason,
                                              actor_id=actor.id, created_at=now()))
            name, value = p.name, p.proposed_value
        if body.decision == "APPROVED":  # the same path as POST /limits/{name}: history row, then the override
            limits.apply(sessions, name, value, f"제안 #{proposal_id} 승인: {body.reason}", actor)
        with sessions() as session:
            return proposal_out(session, session.get(LimitProposal, proposal_id))

    return router
