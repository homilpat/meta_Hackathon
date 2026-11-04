"""Versioned WorkflowPolicy and pure gate functions (v5 structure A).

Drafting, urgent execution, approval and closure are separate decisions. Each gate returns a Verdict:
PASS (allowed), WARN (allowed, needs review), UNKNOWN (evidence missing), BLOCK (refused) with reasons.
The functions take plain dicts so they can be tested without a database.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import WorkflowPolicy

Result = Literal["PASS", "WARN", "UNKNOWN", "BLOCK"]
STAGES = ("D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8")
DONE = ("APPROVED", "DONE")  # a stage counts as complete in either state

# Equivalent to the S6 chain for D2-D4 (PREREQ in workflow.py), extended to D0-D8. eightd.approval_gate is the
# single approval decision for the D2-D4 documents. Urgent
# containment only needs a D0 risk assessment: safety is never held up by document order.
DEFAULT_BODY = {
    "required_roles": {"LEAD": "AUTHOR", "QUALITY": "REVIEWER", "PRODUCTION": "QA_PRODUCTION",
                       "PROCESS": "PROCESS_ENGINEER"},
    "draft_requirements": {"D2": [], "D3": ["D2"], "D4": ["D3"], "D5": ["D4"], "D6": ["D5"], "D7": ["D6"]},
    "execution_permissions": {"URGENT_CONTAINMENT": ["QA_PRODUCTION"], "D3_EXECUTE": ["QA_PRODUCTION"],
                              "D3_VERIFY": ["REVIEWER"], "D6_EXECUTE": ["QA_PRODUCTION", "PROCESS_ENGINEER"],
                              "D6_VERIFY": ["REVIEWER"]},
    "urgent_requires": ["D0"],
    "approval_gates": {
        "D0": {"approver": "REVIEWER", "requires": []},
        "D1": {"approver": "AUTHOR", "requires": ["D0"]},
        "D2": {"approver": "REVIEWER", "requires": []},
        "D3": {"approver": "QA_PRODUCTION", "requires": ["D2"]},
        "D4": {"approver": "PROCESS_ENGINEER", "requires": ["D3"]},
        "D5": {"approver": "PROCESS_ENGINEER", "requires": ["D4"]},
        "D6": {"approver": "REVIEWER", "requires": ["D5"]},
        "D7": {"approver": "REVIEWER", "requires": ["D6"]},
        "D8": {"approver": "REVIEWER", "requires": ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]},
    },
    "closure_gates": ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"],
    "independent_verification": True,  # executor and verifier must differ
    "self_approval_exceptions": [],  # stages where an author may approve; each use is logged
    "routes": {"NCR_ONLY": ["D0", "D1", "D2", "D3"], "FULL_8D": list(STAGES[:-1]),
               "EMERGENCY_FULL_8D": list(STAGES[:-1])},
}
DEFAULT_APPLICABILITY = {"site": "*", "customer": "*", "process_type": "*", "severity": "*"}


class Verdict(NamedTuple):
    result: Result
    reasons: list[str]

    def out(self) -> dict:
        return {"result": self.result, "reasons": self.reasons}


# Reasons a person reads (user 2026-11-04: no policy internals on screen)
ROLE_KO = {"AUTHOR": "작성자", "REVIEWER": "검토자", "QA_PRODUCTION": "QA/생산", "PROCESS_ENGINEER": "공정 엔지니어",
           "AGENT_ADMIN": "AI 운영"}
STATE_KO = {None: "시작 전", "DRAFT": "초안", "IN_REVIEW": "검토 중", "REJECTED": "반려됨", "BASIS_CHANGED": "기반 변경 확인 필요",
            "REVALIDATION_REQUIRED": "재검증 필요", "NOT_EFFECTIVE": "효과 없음", "INCONCLUSIVE": "판단 보류",
            "REOPENED": "재오픈", "OPEN": "진행 중", "PLANNED": "계획됨", "EXECUTED": "실행됨"}


def policy_hash(policy_id: str, version: int, applicability: dict, body: dict) -> str:
    raw = {"policy_id": policy_id, "version": version, "applicability": applicability, "body": body}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _verdict(blocks: list[str], warns: list[str] | None = None, unknown: list[str] | None = None) -> Verdict:
    if blocks:
        return Verdict("BLOCK", blocks)
    if unknown:
        return Verdict("UNKNOWN", unknown)
    if warns:
        return Verdict("WARN", warns)
    return Verdict("PASS", [])


def can_draft(body: dict, stage: str, state: dict[str, str | None]) -> Verdict:
    """Drafts may be written ahead of approvals, but need a live (not rejected/superseded) upstream draft."""
    missing = [s for s in body["draft_requirements"].get(stage, [])
               if state.get(s) in (None, "REJECTED", "SUPERSEDED")]
    return _verdict([f"{stage} 초안은 {s} 문서가 먼저 있어야 합니다" for s in missing])


def can_execute_urgent(body: dict, role: str, state: dict[str, str | None], route: str | None) -> Verdict:
    """Urgent containment: allowed right after D0 for an authorised role, before D1/D2 are complete."""
    blocks = []
    if role not in body["execution_permissions"]["URGENT_CONTAINMENT"]:
        blocks.append(f"{ROLE_KO.get(role, role)} 역할은 긴급 봉쇄를 실행할 수 없습니다")
    blocks += [f"긴급 봉쇄 전에 {s} 위험 평가가 필요합니다" for s in body["urgent_requires"]
               if state.get(s) not in DONE]
    warns = [] if route == "EMERGENCY_FULL_8D" else ["긴급 경로가 아닌 사건의 긴급 조치입니다"]
    return _verdict(blocks, warns)


def can_execute(body: dict, permission: str, role: str) -> Verdict:
    allowed = body["execution_permissions"].get(permission, [])
    return _verdict([] if role in allowed else [f"{ROLE_KO.get(role, role)} 역할은 이 작업을 할 수 없습니다"])


def may_decide(body: dict, stage: str, role: str, actor_id: str, author_id: str | None) -> Verdict:
    """Who may decide (approve, reject, ask for info) at a stage: the policy's approver role, not the author."""
    gate = body["approval_gates"].get(stage)
    if gate is None:
        return Verdict("BLOCK", [f"{stage} 단계는 결재 대상이 아닙니다"])
    blocks = []
    if role != gate["approver"]:
        blocks.append(f"{stage} 결재는 {ROLE_KO.get(gate['approver'], gate['approver'])}만 할 수 있습니다")
    if author_id == actor_id and stage not in body["self_approval_exceptions"]:
        blocks.append("self-approval is not allowed by this policy")
    return _verdict(blocks)


def can_approve(body: dict, stage: str, role: str, actor_id: str, author_id: str | None,
                state: dict[str, str | None]) -> Verdict:
    who = may_decide(body, stage, role, actor_id, author_id)
    if stage not in body["approval_gates"]:
        return who
    blocks = who.reasons + [f"{stage} 결재 전에 {s} 단계가 끝나야 합니다 (지금 {STATE_KO.get(state.get(s), '시작 전')})"
                            for s in body["approval_gates"][stage]["requires"] if state.get(s) not in DONE]
    return _verdict(blocks)


def can_close(body: dict, state: dict[str, str | None], route: str | None,
              extra_blocks: list[str] | None = None) -> Verdict:
    """D8: every stage the route requires is complete; callers add evidence/risk/signature checks."""
    required = body["routes"].get(route or "", body["closure_gates"]) if route else None
    if required is None:
        return Verdict("BLOCK", ["D0 판정이 없어 종결할 수 없습니다"])
    blocks = [f"{s} 단계가 끝나지 않았습니다 (지금 {STATE_KO.get(state.get(s), '시작 전')})" for s in required if state.get(s) not in DONE]
    return _verdict(blocks + (extra_blocks or []))


# --- storage ---------------------------------------------------------------------------------------------

def ensure_default(session: Session) -> WorkflowPolicy:
    row = session.scalar(select(WorkflowPolicy).where(WorkflowPolicy.policy_id == "DEFAULT",
                                                      WorkflowPolicy.version == 1))
    if row is None:
        row = WorkflowPolicy(policy_id="DEFAULT", version=1, applicability=DEFAULT_APPLICABILITY, body=DEFAULT_BODY,
                             policy_hash=policy_hash("DEFAULT", 1, DEFAULT_APPLICABILITY, DEFAULT_BODY),
                             effective_from="2026-10-28T00:00:00+00:00", approved_by="SYSTEM_DEFAULT",
                             created_at=datetime.now(UTC).isoformat())
        session.add(row)
        session.flush()
    return row


def active(session: Session, ctx: dict, at: str | None = None) -> WorkflowPolicy:
    """Most specific effective policy for ctx (site/customer/process_type/severity); newest version wins."""
    ensure_default(session)
    at = at or datetime.now(UTC).isoformat()
    best, best_key = None, None
    for p in session.scalars(select(WorkflowPolicy).where(WorkflowPolicy.effective_from <= at)):
        a = p.applicability
        if any(a.get(k, "*") not in ("*", ctx.get(k)) for k in DEFAULT_APPLICABILITY):
            continue
        key = (sum(a.get(k, "*") != "*" for k in DEFAULT_APPLICABILITY), p.version)
        if best_key is None or key > best_key:
            best, best_key = p, key
    return best


def publish(session: Session, policy_id: str, applicability: dict, body: dict, approved_by: str) -> WorkflowPolicy:
    missing = sorted(set(DEFAULT_BODY) - set(body))
    if missing:
        raise ValueError(f"policy body missing keys {missing}")
    prev = session.scalar(select(WorkflowPolicy.version).where(WorkflowPolicy.policy_id == policy_id)
                          .order_by(WorkflowPolicy.version.desc()).limit(1))
    version = (prev or 0) + 1
    appl = {**DEFAULT_APPLICABILITY, **applicability}
    now = datetime.now(UTC).isoformat()
    row = WorkflowPolicy(policy_id=policy_id, version=version, applicability=appl, body=body,
                         policy_hash=policy_hash(policy_id, version, appl, body), effective_from=now,
                         approved_by=approved_by, created_at=now)
    session.add(row)
    session.flush()
    return row


def ref(p: WorkflowPolicy) -> dict:
    return {"policy_id": p.policy_id, "version": p.version, "policy_hash": p.policy_hash}
