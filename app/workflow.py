"""Identity, case scope, document versions (NCR -> Containment -> RCA), review/approval, source
corrections with impact analysis, and the audit timeline."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.convertors import StringConvertor, register_url_convertor

from app import audit, factcheck, history, impact, investigator, ncr, policy
from app.db import (
    ApprovalEvent,
    Assignment,
    CaseLink,
    ChangeImpact,
    DocComment,
    DocumentClaim,
    DocumentVersion,
    Evidence,
    IdempotencyKey,
    ModelRun,
    QualityCase,
    Review,
    User,
    WorkflowEvent,
)
from app.ingestion import SourceAssetInput
from app.model_provider import ModelProvider

# ponytail: demo identities selected by X-User header, no passwords. Swap for real auth before any
# non-demo use; the role/assignment checks below do not change.
DEMO_USERS = {
    "alice": ("Alice (author)", "AUTHOR"), "dave": ("Dave (author)", "AUTHOR"),
    "bob": ("Bob (reviewer)", "REVIEWER"), "carol": ("Carol (reviewer)", "REVIEWER"),
    "erin": ("Erin (QA/Production)", "QA_PRODUCTION"), "frank": ("Frank (process engineer)", "PROCESS_ENGINEER"),
}
# URL kind -> document type; which approved document it must build on. Who may approve comes from the active
# WorkflowPolicy (eightd.approval_gate); DEFAULT gives NCR=REVIEWER, CONTAINMENT=QA_PRODUCTION, RCA=PROCESS_ENGINEER.
KINDS = {"ncr": "NCR", "containment": "CONTAINMENT", "rca": "RCA"}
PREREQ = {"CONTAINMENT": "NCR", "RCA": "CONTAINMENT"}
STEP = {"NCR": "D2", "CONTAINMENT": "D3", "RCA": "D4"}  # 8D: problem description, containment, root cause


class DocKind(StringConvertor):
    regex = "|".join(KINDS)


register_url_convertor("doc", DocKind())


class Actor(NamedTuple):
    id: str
    role: str


def now() -> str:
    return datetime.now(UTC).isoformat()


class ReviewRequest(BaseModel):
    reviewer_id: str


class Decision(BaseModel):
    decision: Literal["APPROVE", "REJECT", "REQUEST_INFO"]
    comment: str = ""
    content_sha256: str  # the exact version content the reviewer saw


class BasisCheck(BaseModel):
    decision: Literal["NO_SCOPE_IMPACT", "REVISE"]
    comment: str = Field(min_length=3, max_length=300)
    content_sha256: str


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)
    claim_id: str | None = None  # anchor to one claim, or the whole version
    reply_to: int | None = None


class ResolveIn(BaseModel):
    body: str = Field(min_length=1, max_length=500)


class NcrCreate(BaseModel):
    extra_claims: list[dict] = []  # author-added claims, held to the same evidence rules
    investigation_run_id: int | None = None  # build from a VALIDATED model run instead of the template


class RevisionIn(BaseModel):
    asset: SourceAssetInput  # SYNTHETIC + APPROVED_FOR_EXTERNAL only; anything else is a 422
    reason: str = Field(min_length=3, max_length=200)


class Assign(BaseModel):
    user_id: str


class InvestigateIn(BaseModel):
    use_history: bool = True


class LinkIn(BaseModel):
    historical_case_id: str
    decision: Literal["ACCEPTED", "REJECTED"]
    note: str = ""


def make_auth(sessions: sessionmaker) -> Callable[..., Actor]:
    def current_user(x_user: Annotated[str | None, Header()] = None) -> Actor:
        if x_user not in DEMO_USERS:
            raise HTTPException(401, "Unknown or missing X-User")
        name, role = DEMO_USERS[x_user]
        with sessions.begin() as session:
            if session.get(User, x_user) is None:
                session.add(User(id=x_user, name=name, role=role))
        return Actor(x_user, role)

    return current_user


def require_case(session: Session, case_id: str, actor: Actor) -> QualityCase:
    case = session.get(QualityCase, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    if not session.scalar(select(Assignment.id).where(
            Assignment.case_id == case_id, Assignment.user_id == actor.id)):
        raise HTTPException(403, "Not assigned to this case")
    return case


def require_role(actor: Actor, role: str) -> None:
    if actor.role != role:
        raise HTTPException(403, f"{role} role required")


def log(session: Session, case_id: str, actor: Actor, event: str, detail: str, doc_id: int | None = None):
    session.add(WorkflowEvent(case_id=case_id, document_version_id=doc_id, actor_id=actor.id,
                              event=event, detail=detail, created_at=now()))


def _comments(session: Session, doc_id: int) -> list[dict]:
    rows = session.scalars(select(DocComment).where(DocComment.document_version_id == doc_id)
                           .order_by(DocComment.id)).all()
    resolved = {r.reply_to for r in rows if r.kind == "RESOLVE"}
    return [{"comment_id": r.id, "claim_id": r.claim_id, "actor_id": r.actor_id, "kind": r.kind,
             "reply_to": r.reply_to, "body": r.body, "created_at": r.created_at,
             "open": r.kind == "COMMENT" and r.reply_to is None and r.id not in resolved} for r in rows]


def _trail(session: Session, doc_id: int) -> list[dict]:
    """Who did what to this version, in order, with the role they acted in (from the append-only log)."""
    rows = session.scalars(select(WorkflowEvent).where(WorkflowEvent.document_version_id == doc_id)
                           .order_by(WorkflowEvent.id)).all()
    return [{"at": w.created_at, "actor_id": w.actor_id, "role": DEMO_USERS[w.actor_id][1], "event": w.event,
             "detail": w.detail} for w in rows]


def _doc_out(session: Session, doc: DocumentVersion) -> dict:
    claims = session.scalars(select(DocumentClaim).where(DocumentClaim.document_version_id == doc.id)
                             .order_by(DocumentClaim.id)).all()
    reviews = session.scalars(select(Review).where(Review.document_version_id == doc.id)).all()
    decisions = session.scalars(select(ApprovalEvent).where(ApprovalEvent.document_version_id == doc.id)
                                .order_by(ApprovalEvent.id)).all()
    return {
        "case_id": doc.case_id, "doc_type": doc.doc_type, "version": doc.version, "status": doc.status,
        "author_id": doc.author_id, "builder": doc.builder, "content_sha256": doc.content_sha256,
        "created_at": doc.created_at, "based_on": doc.based_on,
        "template_version": ncr.template_version(doc.builder, claims),
        "note": ncr.DOC_NOTE.get(doc.doc_type, ""),
        "claims": [{"claim_id": c.claim_id, "classification": c.classification, "text": c.text,
                    "value": c.value, "unit": c.unit, "evidence_ids": c.evidence_ids} for c in claims],
        "reviews": [{"reviewer_id": r.reviewer_id, "state": r.state} for r in reviews],
        "decisions": [{"actor_id": d.actor_id, "action": d.action, "comment": d.comment,
                       "content_sha256": d.content_sha256, "created_at": d.created_at} for d in decisions],
        "comments": _comments(session, doc.id), "trail": _trail(session, doc.id),
    }


def _get_doc(session: Session, case_id: str, version: int, doc_type: str = "NCR") -> DocumentVersion:
    doc = session.scalar(select(DocumentVersion).where(
        DocumentVersion.case_id == case_id, DocumentVersion.doc_type == doc_type,
        DocumentVersion.version == version))
    if doc is None:
        raise HTTPException(404, "Document version not found")
    return doc


def _latest(session: Session, case_id: str, doc_type: str = "NCR") -> DocumentVersion | None:
    return session.scalar(select(DocumentVersion).where(
        DocumentVersion.case_id == case_id, DocumentVersion.doc_type == doc_type)
        .order_by(DocumentVersion.version.desc()).limit(1))


def _based_on(session: Session, case_id: str, doc_type: str, approved: bool = True) -> list[str]:
    """The upstream chain a document builds on. Drafts may be written ahead (e.g. all sections from one
    AI run); review and approval need every upstream document APPROVED, so 8D steps cannot be skipped."""
    chain, t = [], doc_type
    while t := PREREQ.get(t):
        up = _latest(session, case_id, t)
        if up is None or up.status in ("REJECTED", "SUPERSEDED") or (approved and up.status != "APPROVED"):
            need = "APPROVED" if approved else "a live draft"
            raise HTTPException(409, f"{doc_type} needs the latest {t} to be {need} "
                                     f"(is {up.status if up else 'missing'})")
        chain.append(f"{t} v{up.version}")
    return chain[::-1]


def _require_basis(session: Session, doc: DocumentVersion) -> None:
    chain = _based_on(session, doc.case_id, doc.doc_type)
    if chain != doc.based_on:
        raise HTTPException(409, f"{doc.doc_type} v{doc.version} was drafted on {', '.join(doc.based_on)}; the "
                                 f"approved basis is now {', '.join(chain)}. Create a new draft.")


def _gate(session: Session, case_id: str, doc_type: str, actor: Actor, author_id: str | None, full: bool):
    """403 if the policy does not let this actor decide; with full, 409 if a prerequisite stage is incomplete."""
    from app import eightd  # eightd imports this module

    v, p = eightd.approval_gate(session, case_id, doc_type, actor, author_id)
    who = policy.may_decide(p.body, STEP[doc_type], actor.role, actor.id, author_id)
    if who.result == "BLOCK":
        raise HTTPException(403, "; ".join(who.reasons))
    if full and v.result == "BLOCK":
        raise HTTPException(409, "; ".join(v.reasons))
    return p


def _approver(session: Session, case_id: str, doc_type: str) -> str:
    from app import eightd

    return eightd.approver_role(session, case_id, doc_type)


def _impact_out(r: ChangeImpact) -> dict:
    return {"impact_id": r.id, "asset_id": r.asset_id, "supersedes_asset_id": r.supersedes_asset_id,
            "reason": r.reason, "actor_id": r.actor_id, "created_at": r.created_at,
            "changed_evidence": r.changed_evidence, **r.impacted}


def run_idempotent(sessions: sessionmaker, endpoint: str, key: str, actor: Actor,
                   run: Callable[[Session], tuple[int, dict]]) -> JSONResponse:
    """Run `run` once per (key, user, endpoint); a retry replays the stored response."""
    with sessions.begin() as session:
        seen = session.get(IdempotencyKey, (key, actor.id, endpoint))
        if seen:
            return JSONResponse(json.loads(seen.response_json), status_code=seen.status_code)
        status, body = run(session)
        session.add(IdempotencyKey(key=key, user_id=actor.id, endpoint=endpoint, status_code=status,
                                   response_json=json.dumps(body)))
        return JSONResponse(body, status_code=status)


def make_router(sessions: sessionmaker, current_user: Callable[..., Actor],
                provider: ModelProvider | None = None) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    def idempotent(endpoint: str, key: str, actor: Actor, run: Callable[[Session], tuple[int, dict]]):
        return run_idempotent(sessions, endpoint, key, actor, run)

    @router.get("/me")
    def me(actor: Who) -> dict:
        return {"id": actor.id, "role": actor.role, "name": DEMO_USERS[actor.id][0]}

    @router.get("/cases")
    def list_cases(actor: Who) -> list[dict]:
        with sessions() as session:
            rows = session.scalars(select(QualityCase).join(Assignment, Assignment.case_id == QualityCase.id)
                                   .where(Assignment.user_id == actor.id).order_by(QualityCase.created_at)).all()
            return [{"case_id": c.id, "domain": c.domain, "data_origin": c.data_origin} for c in rows]

    @router.post("/cases/{case_id}/assignments", status_code=201)
    def assign(case_id: str, body: Assign, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        if body.user_id not in DEMO_USERS:
            raise HTTPException(422, "Unknown user")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            if session.get(User, body.user_id) is None:
                name, role = DEMO_USERS[body.user_id]
                session.add(User(id=body.user_id, name=name, role=role))
                session.flush()
            if not session.scalar(select(Assignment.id).where(
                    Assignment.case_id == case_id, Assignment.user_id == body.user_id)):
                session.add(Assignment(case_id=case_id, user_id=body.user_id))
                log(session, case_id, actor, "ASSIGNED", body.user_id)
        return {"case_id": case_id, "user_id": body.user_id}

    @router.post("/cases/{case_id}/{kind:doc}")
    def create_doc(case_id: str, kind: str, body: NcrCreate, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")
        doc_type = KINDS[kind]

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            based_on = _based_on(session, case_id, doc_type, approved=False)
            known = set(session.scalars(select(Evidence.evidence_id).where(Evidence.case_id == case_id)))
            if not known:
                raise HTTPException(422, "Case has no evidence; upload sources first")
            if body.investigation_run_id is None:
                claims, builder = ncr.BUILDERS[doc_type](session, case_id), ncr.BUILDER
            elif doc_type == "CONTAINMENT":
                raise HTTPException(422, "Model findings carry no containment proposals; use the template")
            else:
                mrun = session.get(ModelRun, body.investigation_run_id)
                if mrun is None or mrun.case_id != case_id:
                    raise HTTPException(404, "Investigation run not found for this case")
                if mrun.status != "VALIDATED":
                    raise HTTPException(409, f"Run is {mrun.status}; only VALIDATED runs can become a draft")
                claims = investigator.report_claims(mrun, doc_type)
                builder = f"MODEL_{mrun.mode}:{mrun.model}:run{mrun.id}"
            claims += [{"value": None, "unit": None, "evidence_ids": [], **c,
                        "claim_id": f"C{len(claims) + i + 1}"} for i, c in enumerate(body.extra_claims)]
            try:
                ncr.validate_claims(claims, known)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if errors := factcheck.check_claims(session, case_id, claims):
                raise HTTPException(422, "; ".join(errors))
            prev = _latest(session, case_id, doc_type)
            version = prev.version + 1 if prev else 1
            if prev and prev.status in ("DRAFT", "IN_REVIEW", "INFO_REQUESTED"):
                prev.status = "SUPERSEDED"
            extra = None if doc_type == "NCR" else {"doc_type": doc_type, "based_on": based_on}
            doc = DocumentVersion(case_id=case_id, doc_type=doc_type, version=version, status="DRAFT",
                                  author_id=actor.id, builder=builder, created_at=now(), based_on=based_on,
                                  content_sha256=ncr.content_sha256(case_id, version, claims, builder, extra))
            session.add(doc)
            session.flush()
            session.add_all(DocumentClaim(document_version_id=doc.id, claim_id=c["claim_id"],
                                          classification=c["classification"], text=c["text"],
                                          value=c["value"], unit=c["unit"], evidence_ids=c["evidence_ids"])
                            for c in claims)
            impact.link_document(session, doc, claims)
            log(session, case_id, actor, "DRAFT_CREATED",
                f"{doc_type} v{version} builder={builder} based_on={','.join(based_on) or '-'}", doc.id)
            session.flush()
            return 201, _doc_out(session, doc)

        return idempotent(f"create_{kind}:{case_id}", key, actor, run)

    @router.get("/audit/verify")
    def audit_verify(actor: Who) -> dict:
        """Recompute the audit hash chain: detects rows edited, deleted or inserted behind the app's back."""
        with sessions() as session:
            return audit.verify(session)

    @router.get("/queue")
    def queue(actor: Who, scope: Literal["department", "mine"] = "department") -> list[dict]:
        """Open work for the caller's role (department) across assigned cases, or only items the caller owns."""
        with sessions() as session:
            cases = session.scalars(select(Assignment.case_id).where(Assignment.user_id == actor.id)).all()
            items = []
            for case_id in sorted(set(cases)):
                for kind, doc_type in KINDS.items():
                    doc = _latest(session, case_id, doc_type)
                    if doc is None:
                        continue

                    def add(task: str, owner: str | None, detail: str = "", d=doc, k=kind, c=case_id):
                        items.append({"case_id": c, "kind": k, "doc_type": d.doc_type, "version": d.version,
                                      "status": d.status, "task": task, "owner": owner, "detail": detail})

                    if actor.role == _approver(session, case_id, doc_type):
                        if doc.status == "IN_REVIEW":
                            add("REVIEW", session.scalar(select(Review.reviewer_id).where(
                                Review.document_version_id == doc.id, Review.state == "PENDING")))
                        elif doc.status == "BASIS_CHANGED":  # owned by whoever approved it
                            add("BASIS_CHECK", session.scalar(select(ApprovalEvent.actor_id).where(
                                ApprovalEvent.document_version_id == doc.id, ApprovalEvent.action == "APPROVE")
                                .order_by(ApprovalEvent.id.desc()).limit(1)))
                    if actor.role == "AUTHOR":
                        if doc.status == "DRAFT":
                            try:
                                _based_on(session, case_id, doc_type)
                                add("SEND_FOR_REVIEW", doc.author_id)
                            except HTTPException as exc:
                                add("WAITING_UPSTREAM", doc.author_id, exc.detail)
                        elif doc.status in ("REJECTED", "INFO_REQUESTED", "REVALIDATION_REQUIRED"):
                            add("REDRAFT", doc.author_id)
                        for cm in _comments(session, doc.id):
                            if cm["open"]:
                                add("ANSWER_COMMENT", doc.author_id,
                                    f"{cm['actor_id']} on {cm['claim_id'] or 'document'}: {cm['body']}")
            return [i for i in items if scope == "department" or i["owner"] == actor.id]

    @router.post("/cases/{case_id}/{kind:doc}/{version}/comments", status_code=201)
    def add_comment(case_id: str, kind: str, version: int, body: CommentIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind])
            if body.claim_id and not session.scalar(select(DocumentClaim.id).where(
                    DocumentClaim.document_version_id == doc.id, DocumentClaim.claim_id == body.claim_id)):
                raise HTTPException(422, "Unknown claim on this version")
            if body.reply_to is not None:
                parent = session.get(DocComment, body.reply_to)
                if parent is None or parent.document_version_id != doc.id:
                    raise HTTPException(422, "reply_to must be a comment on this version")
            row = DocComment(case_id=case_id, document_version_id=doc.id, claim_id=body.claim_id, actor_id=actor.id,
                             kind="COMMENT", reply_to=body.reply_to, body=body.body, created_at=now())
            session.add(row)
            session.flush()
            log(session, case_id, actor, "COMMENTED",
                f"{doc.doc_type} v{version} {body.claim_id or 'document'}: {body.body[:120]}", doc.id)
            return next(c for c in _comments(session, doc.id) if c["comment_id"] == row.id)

    @router.post("/cases/{case_id}/{kind:doc}/{version}/comments/{comment_id}/resolve", status_code=201)
    def resolve_comment(case_id: str, kind: str, version: int, comment_id: int, body: ResolveIn, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind])
            target = next((c for c in _comments(session, doc.id) if c["comment_id"] == comment_id), None)
            if target is None or not target["open"]:
                raise HTTPException(409, "Not an open comment on this version")
            if actor.id not in (doc.author_id, target["actor_id"]):
                raise HTTPException(403, "Only the document author or the commenter can resolve")
            session.add(DocComment(case_id=case_id, document_version_id=doc.id, claim_id=target["claim_id"],
                                   actor_id=actor.id, kind="RESOLVE", reply_to=comment_id, body=body.body,
                                   created_at=now()))
            log(session, case_id, actor, "COMMENT_RESOLVED",
                f"{doc.doc_type} v{version} #{comment_id}: {body.body[:120]}", doc.id)
            session.flush()
            return {"comments": _comments(session, doc.id)}

    @router.get("/cases/{case_id}/stages")
    def stages(case_id: str, actor: Who) -> list[dict]:
        """8D progress: each step's latest version and whether its review/approval is open yet."""
        with sessions() as session:
            require_case(session, case_id, actor)
            out = []
            for kind, doc_type in KINDS.items():
                doc, blocked = _latest(session, case_id, doc_type), None
                try:
                    _based_on(session, case_id, doc_type)
                except HTTPException as exc:
                    blocked = exc.detail
                out.append({"kind": kind, "doc_type": doc_type, "step": STEP[doc_type],
                            "approver_role": _approver(session, case_id, doc_type), "version": doc.version if doc else None,
                            "status": doc.status if doc else None, "approval_open": blocked is None,
                            "blocked_by": blocked})
            return out

    @router.get("/cases/{case_id}/{kind:doc}")
    def list_docs(case_id: str, kind: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            docs = session.scalars(select(DocumentVersion).where(
                DocumentVersion.case_id == case_id, DocumentVersion.doc_type == KINDS[kind])
                .order_by(DocumentVersion.version)).all()
            return [_doc_out(session, d) for d in docs]

    @router.get("/cases/{case_id}/{kind:doc}/{version}")
    def get_doc(case_id: str, kind: str, version: int, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)
            return _doc_out(session, _get_doc(session, case_id, version, KINDS[kind]))

    @router.get("/cases/{case_id}/{kind:doc}/{version}/html", response_class=HTMLResponse)
    def get_doc_html(case_id: str, kind: str, version: int, actor: Who) -> str:
        with sessions() as session:
            require_case(session, case_id, actor)
            return ncr.render_html(_doc_out(session, _get_doc(session, case_id, version, KINDS[kind])))

    @router.post("/cases/{case_id}/{kind:doc}/{version}/request-review")
    def request_review(case_id: str, kind: str, version: int, body: ReviewRequest, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")
        doc_type = KINDS[kind]

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, doc_type)
            if doc.author_id != actor.id:
                raise HTTPException(403, "Only the author can request review")
            if doc.version != _latest(session, case_id, doc_type).version or doc.status != "DRAFT":
                raise HTTPException(409, "Only the latest DRAFT version can be sent for review")
            from app import eightd

            p, reviewer = eightd.active_policy(session, case_id), DEMO_USERS.get(body.reviewer_id)
            who = policy.may_decide(p.body, STEP[doc_type], reviewer[1] if reviewer else "", body.reviewer_id,
                                    doc.author_id)
            if reviewer is None or who.result == "BLOCK":
                raise HTTPException(422, f"{doc_type} reviewer is not allowed by the policy: "
                                         f"{'; '.join(who.reasons) or 'unknown user'}")
            if not session.scalar(select(Assignment.id).where(
                    Assignment.case_id == case_id, Assignment.user_id == body.reviewer_id)):
                raise HTTPException(422, "Reviewer is not assigned to this case")
            _require_basis(session, doc)
            if body.reviewer_id == doc.author_id:  # only reachable through a policy self-approval exception
                log(session, case_id, actor, "SELF_APPROVAL_EXCEPTION", f"{doc_type} v{version} {p.policy_hash}",
                    doc.id)
            doc.status = "IN_REVIEW"
            session.add(Review(document_version_id=doc.id, requested_by=actor.id, reviewer_id=body.reviewer_id,
                               state="PENDING", created_at=now(), policy_hash=p.policy_hash))
            log(session, case_id, actor, "REVIEW_REQUESTED", f"{doc_type} v{version} -> {body.reviewer_id} "
                f"policy={p.policy_id} v{p.version} {p.policy_hash}", doc.id)
            session.flush()
            return 200, _doc_out(session, doc)

        return idempotent(f"request_review:{case_id}:{kind}:{version}", key, actor, run)

    @router.post("/cases/{case_id}/{kind:doc}/{version}/decision")
    def decide(case_id: str, kind: str, version: int, body: Decision, key: IdemKey, actor: Who):
        doc_type = KINDS[kind]

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, doc_type)
            _gate(session, case_id, doc_type, actor, doc.author_id, full=False)
            review = session.scalar(select(Review).where(
                Review.document_version_id == doc.id, Review.reviewer_id == actor.id,
                Review.state == "PENDING"))
            if review is None:
                raise HTTPException(403, "No pending review request for you on this version")
            if doc.version != _latest(session, case_id, doc_type).version:
                raise HTTPException(409, "A newer version exists; this one is stale")
            if doc.status != "IN_REVIEW" or body.content_sha256 != doc.content_sha256:
                raise HTTPException(409, "Version is not in review or content changed since you read it")
            note = ""
            if body.decision == "APPROVE":  # re-evaluated under the policy in force now, not the one at request
                p = _gate(session, case_id, doc_type, actor, doc.author_id, full=True)
                _require_basis(session, doc)
                note = f" policy={p.policy_id} v{p.version} {p.policy_hash}"
                if review.policy_hash and review.policy_hash != p.policy_hash:
                    note += f" (review was requested under {review.policy_hash}; re-evaluated)"
            review.state = "DONE"
            doc.status = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "REQUEST_INFO": "INFO_REQUESTED"}[
                body.decision]
            session.add(ApprovalEvent(document_version_id=doc.id, actor_id=actor.id, action=body.decision,
                                      content_sha256=doc.content_sha256, comment=body.comment,
                                      created_at=now()))
            log(session, case_id, actor, body.decision, f"{doc_type} v{version}: {body.comment}{note}", doc.id)
            session.flush()
            return 200, _doc_out(session, doc)

        return idempotent(f"decision:{case_id}:{kind}:{version}", key, actor, run)

    @router.post("/cases/{case_id}/{kind:doc}/{version}/basis-check")
    def basis_check(case_id: str, kind: str, version: int, body: BasisCheck, key: IdemKey, actor: Who):
        """The approver of a BASIS_CHANGED document records whether its scope still holds on the new basis."""
        doc_type = KINDS[kind]

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, doc_type)
            _gate(session, case_id, doc_type, actor, doc.author_id, full=False)
            if doc.status != "BASIS_CHANGED" or body.content_sha256 != doc.content_sha256:
                raise HTTPException(409, "Version is not BASIS_CHANGED or content changed since you read it")
            if body.decision == "NO_SCOPE_IMPACT":
                chain = _based_on(session, case_id, doc_type)  # upstream must be re-approved first
                doc.status = "APPROVED"
            else:
                chain, doc.status = doc.based_on, "REVALIDATION_REQUIRED"
            note = f"{body.comment} (basis checked: {', '.join(chain)})"
            session.add(ApprovalEvent(document_version_id=doc.id, actor_id=actor.id, action=body.decision,
                                      content_sha256=doc.content_sha256, comment=note, created_at=now()))
            log(session, case_id, actor, "BASIS_CHECKED", f"{doc_type} v{version} {body.decision}: {note}", doc.id)
            session.flush()
            return 200, _doc_out(session, doc)

        return idempotent(f"basis_check:{case_id}:{kind}:{version}", key, actor, run)

    @router.post("/cases/{case_id}/source-revisions")
    def import_revision(case_id: str, body: RevisionIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            try:
                changed = impact.import_revision(session, case_id, body.asset)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            found = impact.reopen(session, case_id, changed)
            row = ChangeImpact(case_id=case_id, asset_id=body.asset.asset_id, actor_id=actor.id,
                               supersedes_asset_id=body.asset.supersedes_asset_id, reason=body.reason,
                               changed_evidence=changed, impacted=found, created_at=now())
            session.add(row)
            log(session, case_id, actor, "SOURCE_REVISED",
                f"{body.asset.asset_id} supersedes {body.asset.supersedes_asset_id}: {body.reason}")
            for d in found["documents"]:
                if d["status_after"] != d["status_before"]:
                    log(session, case_id, actor, "REVALIDATION_REQUIRED",
                        f"{d['doc_type']} v{d['version']} was {d['status_before']}; claims "
                        f"{','.join(d['claims'])} cite corrected source rows", d["document_version_id"])
            for d in found["basis_changed"]:
                log(session, case_id, actor, "BASIS_CHANGED", f"{d['doc_type']} v{d['version']} cites no corrected "
                    f"row but builds on a reopened document; {_approver(session, case_id, d['doc_type'])} must confirm its scope",
                    d["document_version_id"])
            session.flush()
            return 201, _impact_out(row)

        return idempotent(f"revision:{case_id}", key, actor, run)

    @router.get("/cases/{case_id}/change-impact")
    def change_impact(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            rows = session.scalars(select(ChangeImpact).where(ChangeImpact.case_id == case_id)
                                   .order_by(ChangeImpact.id)).all()
            return [_impact_out(r) for r in rows]

    @router.post("/cases/{case_id}/investigations")
    def start_investigation(case_id: str, key: IdemKey, actor: Who, body: InvestigateIn | None = None):
        use_history = (body or InvestigateIn()).use_history
        require_role(actor, "AUTHOR")
        if provider is None:
            raise HTTPException(503, "LIVE model provider not configured (MODEL_API_KEY unset); no mock fallback")

        def run(session: Session) -> tuple[int, dict]:
            case = require_case(session, case_id, actor)
            if case.data_origin != "SYNTHETIC":
                raise HTTPException(422, "Only SYNTHETIC cases may be sent to an external model")
            since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            used = len(session.scalars(select(ModelRun.id).where(ModelRun.requested_by == actor.id,
                                                                 ModelRun.started_at >= since)).all())
            if used >= investigator.RUNS_PER_USER_HOUR:  # cost/abuse cap on paid model calls
                raise HTTPException(429, f"Investigation quota reached ({used} runs in the last hour)")
            if not session.scalar(select(Evidence.id).where(Evidence.case_id == case_id).limit(1)):
                raise HTTPException(422, "Case has no evidence; upload sources first")
            mrun = investigator.investigate(session, case_id, actor.id, provider, use_history)
            log(session, case_id, actor, "INVESTIGATION_RUN",
                f"run{mrun.id} mode={mrun.mode} model={mrun.model} history={'ON' if use_history else 'OFF'} "
                f"status={mrun.status}")
            session.flush()
            return 201, investigator.run_out(session, mrun)

        return idempotent(f"investigate:{case_id}", key, actor, run)

    @router.get("/cases/{case_id}/history")
    def case_history(case_id: str, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            prof = history.case_profile(session, case_id)
            return {"profile": prof.boards, **history.retrieve(session, prof)}

    @router.get("/cases/{case_id}/next-evidence")
    def next_evidence(case_id: str, actor: Who, history_mode: Literal["on", "off"] = "on") -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            prof = history.case_profile(session, case_id)
            found = history.retrieve(session, prof) if history_mode == "on" else None
            return {**history.plan_next_evidence(prof, found),
                    "precedents": found["precedents"] if found else [], "status": found["status"] if found else None}

    @router.post("/cases/{case_id}/history/links", status_code=201)
    def link_precedent(case_id: str, body: LinkIn, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            eligible = {p["historical_case_id"] for p in
                        history.retrieve(session, history.case_profile(session, case_id))["precedents"]}
            if body.historical_case_id not in eligible:
                raise HTTPException(422, "Precedent is not eligible for this case")
            session.add(CaseLink(case_id=case_id, historical_case_id=body.historical_case_id,
                                 decision=body.decision, note=body.note, actor_id=actor.id, created_at=now()))
            log(session, case_id, actor, f"PRECEDENT_{body.decision}", f"{body.historical_case_id}: {body.note}")
        return {"case_id": case_id, **body.model_dump()}

    @router.get("/cases/{case_id}/investigations")
    def list_investigations(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            runs = session.scalars(select(ModelRun).where(ModelRun.case_id == case_id).order_by(ModelRun.id)).all()
            return [investigator.run_out(session, r) for r in runs]

    @router.get("/cases/{case_id}/timeline")
    def timeline(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            rows = session.scalars(select(WorkflowEvent).where(WorkflowEvent.case_id == case_id)
                                   .order_by(WorkflowEvent.id)).all()
            return [{"at": w.created_at, "actor_id": w.actor_id, "event": w.event, "detail": w.detail,
                     "version_id": w.document_version_id} for w in rows]

    return router
