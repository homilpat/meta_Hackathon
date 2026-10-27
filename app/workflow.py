"""Identity, case scope, document versions (NCR -> Containment -> RCA), review/approval, source
corrections with impact analysis, and the audit timeline."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.convertors import StringConvertor, register_url_convertor

from app import history, impact, investigator, ncr
from app.db import (
    ApprovalEvent,
    Assignment,
    CaseLink,
    ChangeImpact,
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
# URL kind -> document type; who may approve it; which approved document it must build on.
KINDS = {"ncr": "NCR", "containment": "CONTAINMENT", "rca": "RCA"}
APPROVER = {"NCR": "REVIEWER", "CONTAINMENT": "QA_PRODUCTION", "RCA": "PROCESS_ENGINEER"}
PREREQ = {"CONTAINMENT": "NCR", "RCA": "CONTAINMENT"}


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


def _doc_out(session: Session, doc: DocumentVersion) -> dict:
    claims = session.scalars(select(DocumentClaim).where(DocumentClaim.document_version_id == doc.id)
                             .order_by(DocumentClaim.id)).all()
    reviews = session.scalars(select(Review).where(Review.document_version_id == doc.id)).all()
    decisions = session.scalars(select(ApprovalEvent).where(ApprovalEvent.document_version_id == doc.id)
                                .order_by(ApprovalEvent.id)).all()
    return {
        "case_id": doc.case_id, "doc_type": doc.doc_type, "version": doc.version, "status": doc.status,
        "author_id": doc.author_id, "builder": doc.builder, "content_sha256": doc.content_sha256,
        "created_at": doc.created_at, "based_on": doc.based_on, "template_version": ncr.TEMPLATE_VERSION,
        "note": ncr.DOC_NOTE.get(doc.doc_type, ""),
        "claims": [{"claim_id": c.claim_id, "classification": c.classification, "text": c.text,
                    "value": c.value, "unit": c.unit, "evidence_ids": c.evidence_ids} for c in claims],
        "reviews": [{"reviewer_id": r.reviewer_id, "state": r.state} for r in reviews],
        "decisions": [{"actor_id": d.actor_id, "action": d.action, "comment": d.comment,
                       "content_sha256": d.content_sha256, "created_at": d.created_at} for d in decisions],
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


def _based_on(session: Session, case_id: str, doc_type: str) -> list[str]:
    """The approved chain a new document builds on; any break (e.g. revalidation) holds the task."""
    chain, t = [], doc_type
    while t := PREREQ.get(t):
        up = _latest(session, case_id, t)
        if up is None or up.status != "APPROVED":
            raise HTTPException(409, f"{doc_type} needs the latest {t} to be APPROVED "
                                     f"(is {up.status if up else 'missing'})")
        chain.append(f"{t} v{up.version}")
    return chain[::-1]


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
            based_on = _based_on(session, case_id, doc_type)
            known = set(session.scalars(select(Evidence.evidence_id).where(Evidence.case_id == case_id)))
            if not known:
                raise HTTPException(422, "Case has no evidence; upload sources first")
            if body.investigation_run_id is None:
                claims, builder = ncr.BUILDERS[doc_type](session, case_id), ncr.BUILDER
            elif doc_type != "NCR":
                raise HTTPException(422, "Only an NCR can be built from an investigation run")
            else:
                mrun = session.get(ModelRun, body.investigation_run_id)
                if mrun is None or mrun.case_id != case_id:
                    raise HTTPException(404, "Investigation run not found for this case")
                if mrun.status != "VALIDATED":
                    raise HTTPException(409, f"Run is {mrun.status}; only VALIDATED runs can become an NCR")
                claims = investigator.report_claims(mrun)
                builder = f"MODEL_{mrun.mode}:{mrun.model}:run{mrun.id}"
            claims += [{"value": None, "unit": None, "evidence_ids": [], **c,
                        "claim_id": f"C{len(claims) + i + 1}"} for i, c in enumerate(body.extra_claims)]
            try:
                ncr.validate_claims(claims, known)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
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
            reviewer = DEMO_USERS.get(body.reviewer_id)
            if reviewer is None or reviewer[1] != APPROVER[doc_type] or body.reviewer_id == actor.id:
                raise HTTPException(422, f"{doc_type} reviewer must be a {APPROVER[doc_type]} other than the author")
            if not session.scalar(select(Assignment.id).where(
                    Assignment.case_id == case_id, Assignment.user_id == body.reviewer_id)):
                raise HTTPException(422, "Reviewer is not assigned to this case")
            doc.status = "IN_REVIEW"
            session.add(Review(document_version_id=doc.id, requested_by=actor.id,
                               reviewer_id=body.reviewer_id, state="PENDING", created_at=now()))
            log(session, case_id, actor, "REVIEW_REQUESTED", f"{doc_type} v{version} -> {body.reviewer_id}", doc.id)
            session.flush()
            return 200, _doc_out(session, doc)

        return idempotent(f"request_review:{case_id}:{kind}:{version}", key, actor, run)

    @router.post("/cases/{case_id}/{kind:doc}/{version}/decision")
    def decide(case_id: str, kind: str, version: int, body: Decision, key: IdemKey, actor: Who):
        doc_type = KINDS[kind]
        require_role(actor, APPROVER[doc_type])

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, doc_type)
            if doc.author_id == actor.id:
                raise HTTPException(403, "Authors cannot decide their own document")
            review = session.scalar(select(Review).where(
                Review.document_version_id == doc.id, Review.reviewer_id == actor.id,
                Review.state == "PENDING"))
            if review is None:
                raise HTTPException(403, "No pending review request for you on this version")
            if doc.version != _latest(session, case_id, doc_type).version:
                raise HTTPException(409, "A newer version exists; this one is stale")
            if doc.status != "IN_REVIEW" or body.content_sha256 != doc.content_sha256:
                raise HTTPException(409, "Version is not in review or content changed since you read it")
            review.state = "DONE"
            doc.status = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "REQUEST_INFO": "INFO_REQUESTED"}[
                body.decision]
            session.add(ApprovalEvent(document_version_id=doc.id, actor_id=actor.id, action=body.decision,
                                      content_sha256=doc.content_sha256, comment=body.comment,
                                      created_at=now()))
            log(session, case_id, actor, body.decision, f"{doc_type} v{version}: {body.comment}", doc.id)
            session.flush()
            return 200, _doc_out(session, doc)

        return idempotent(f"decision:{case_id}:{kind}:{version}", key, actor, run)

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
