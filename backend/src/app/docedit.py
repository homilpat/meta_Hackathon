"""G9 Human Docs: a person edits a D2/D3/D4 document; every save is a new version, re-validated by the same validator.

The stored versions, claims, validation runs and approvals are the existing ones (no second approval source). An edit
names the exact version it started from (`expected_sha256`); anything newer or changed is a 409. An AI suggestion is
returned as a proposed change list and is never applied by the server; the person submits it as an ordinary edit.
"""

import json
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import factcheck, impact, ncr, validation
from app.db import DocumentClaim, DocumentVersion
from app.fields import FreeText
from app.model_provider import ModelProvider, ProviderError
from app.workflow import (
    KINDS,
    Actor,
    _doc_out,
    _get_doc,
    _latest,
    log,
    require_case,
    require_role,
    run_idempotent,
)

PREFIX = "HUMAN_EDIT"
FIELDS = ("classification", "text", "value", "unit", "evidence_ids")


class ClaimChange(BaseModel):
    claim_id: str
    classification: Literal["OBSERVED", "CALCULATED", "HYPOTHESIS", "UNKNOWN"] | None = None
    text: str | None = Field(None, min_length=1, max_length=2000)
    value: float | None = None
    unit: str | None = Field(None, max_length=20)
    evidence_ids: list[str] | None = None


class EditIn(BaseModel):
    expected_sha256: str  # content hash of the version the editor started from
    reason: FreeText
    changes: list[ClaimChange] = []
    add: list[dict] = []
    remove: list[str] = []
    ai_proposal: bool = False  # the editor is submitting an AI suggestion they accepted


class ProposalIn(BaseModel):
    instruction: FreeText


def claims_of(session: Session, doc: DocumentVersion) -> list[dict]:
    rows = session.scalars(select(DocumentClaim).where(DocumentClaim.document_version_id == doc.id)
                           .order_by(DocumentClaim.id))
    return [{"claim_id": c.claim_id, **{f: getattr(c, f) for f in FIELDS}} for c in rows]


def diff(old: list[dict], new: list[dict]) -> list[dict]:
    a, b = {c["claim_id"]: c for c in old}, {c["claim_id"]: c for c in new}
    out = [{"claim_id": k, "change": "REMOVED", "before": a[k]} for k in a if k not in b]
    out += [{"claim_id": k, "change": "ADDED", "after": b[k]} for k in b if k not in a]
    for k in a.keys() & b.keys():
        fields = {f: [a[k][f], b[k][f]] for f in FIELDS if a[k][f] != b[k][f]}
        if fields:
            out.append({"claim_id": k, "change": "CHANGED", "fields": fields})
    return sorted(out, key=lambda d: (len(d["claim_id"]), d["claim_id"]))


def apply(claims: list[dict], body: EditIn) -> list[dict]:
    by_id = {c["claim_id"]: dict(c) for c in claims}
    for cid in [*body.remove, *(ch.claim_id for ch in body.changes)]:
        if cid not in by_id:
            raise HTTPException(422, f"claim {cid} is not in this version")
    for ch in body.changes:
        by_id[ch.claim_id].update(ch.model_dump(exclude_unset=True, exclude={"claim_id"}))
    out = [c for cid, c in by_id.items() if cid not in body.remove]
    n = max((int(c["claim_id"][1:]) for c in claims if c["claim_id"][1:].isdigit()), default=0)
    out += [{"value": None, "unit": None, "evidence_ids": [], **c, "claim_id": f"C{n + i + 1}"}
            for i, c in enumerate(body.add)]
    if not out:
        raise HTTPException(422, "a document needs at least one claim")
    return out


def require_fresh_validation(session: Session, doc: DocumentVersion) -> None:
    """A human-edited version is approved only on a validation of this exact content, still current, not BLOCK."""
    v = validation.latest_run(session, doc)
    if v is None:
        raise HTTPException(409, f"{doc.doc_type} v{doc.version} was edited by a person; validate it before approval")
    if stale := validation.stale_reasons(session, v):
        raise HTTPException(409, f"validation #{v.id} is stale ({'; '.join(stale)}); validate again")
    if v.result == "BLOCK":
        raise HTTPException(409, f"validation #{v.id} is BLOCK; fix the document first")


def make_docs_router(sessions: sessionmaker, current_user: Callable[..., Actor],
                     provider: ModelProvider | None = None) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    @router.post("/cases/{case_id}/{kind:doc}/{version}/edits")
    def edit(case_id: str, kind: str, version: int, body: EditIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")
        doc_type = KINDS[kind]

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            base = _get_doc(session, case_id, version, doc_type)
            if base.version != _latest(session, case_id, doc_type).version:
                raise HTTPException(409, f"{doc_type} v{version} is not the latest version; reload and edit that")
            if base.content_sha256 != body.expected_sha256:
                raise HTTPException(409, "the version changed since you opened it; reload before editing")
            old = claims_of(session, base)
            new = apply(old, body)
            changes = diff(old, new)
            if not changes:
                raise HTTPException(422, "nothing changed")
            if errors := factcheck.check_claims(session, case_id, new, actor.role):
                raise HTTPException(422, "; ".join(errors))
            nv = base.version + 1
            if base.status in ("DRAFT", "IN_REVIEW", "INFO_REQUESTED"):
                base.status = "SUPERSEDED"  # a pending review of the old content can no longer be decided
            builder = f"{PREFIX}:{doc_type} v{base.version}"
            extra = None if doc_type == "NCR" else {"doc_type": doc_type, "based_on": base.based_on}
            doc = DocumentVersion(case_id=case_id, doc_type=doc_type, version=nv, status="DRAFT", author_id=actor.id,
                                  builder=builder, created_at=validation.now(), based_on=base.based_on,
                                  content_sha256=ncr.content_sha256(case_id, nv, new, builder, extra))
            session.add(doc)
            session.flush()
            session.add_all(DocumentClaim(document_version_id=doc.id, claim_id=c["claim_id"],
                                          classification=c["classification"], text=c["text"], value=c["value"],
                                          unit=c["unit"], evidence_ids=c["evidence_ids"]) for c in new)
            impact.link_document(session, doc, new)
            src = "AI suggestion accepted" if body.ai_proposal else "manual"
            log(session, case_id, actor, "DRAFT_EDITED", f"{doc_type} v{base.version} -> v{nv} ({src}): "
                f"{body.reason} | changed {', '.join(d['claim_id'] for d in changes)}", doc.id)
            v = validation.run(session, doc, actor)
            log(session, case_id, actor, "VALIDATED", f"{doc_type} v{nv} {v.result} issues={len(v.issues)} "
                f"contract={v.contract_ref} rules={v.rules_version}", doc.id)
            session.flush()
            return 201, {**_doc_out(session, doc), "diff": changes, "edit_reason": body.reason,
                         "validation": validation.run_out(session, v)}

        return run_idempotent(sessions, f"edit_{kind}:{case_id}:{version}", key, actor, run)

    @router.get("/cases/{case_id}/{kind:doc}/{version}/diff")
    def get_diff(case_id: str, kind: str, version: int, actor: Who, against: int | None = None) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind])
            base = _get_doc(session, case_id, against or version - 1, KINDS[kind])
            return {"from": base.version, "to": doc.version, "from_sha256": base.content_sha256,
                    "to_sha256": doc.content_sha256, "diff": diff(claims_of(session, base), claims_of(session, doc))}

    @router.post("/cases/{case_id}/{kind:doc}/{version}/edit-proposals")
    def propose(case_id: str, kind: str, version: int, body: ProposalIn, actor: Who) -> dict:
        """Ask the model for suggested claim changes. Nothing is stored or applied; the result is a proposal."""
        require_role(actor, "AUTHOR")
        if provider is None:
            raise HTTPException(503, "AI OFFLINE: no model key configured. Manual editing and validation still work.")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind])
            claims, doc_id, doc_type, sha = claims_of(session, doc), doc.id, doc.doc_type, doc.content_sha256
        msgs = [{"role": "system", "content": (
                    "You suggest wording changes to quality-document claims. Reply with JSON only: "
                    '{"changes":[{"claim_id":"C1","text":"..."}]}. Change only text, value or unit of existing '
                    "claims. Do not invent numbers, lots, causes or completed actions; the server re-validates.")},
                {"role": "user", "content": json.dumps({"instruction": body.instruction, "claims": claims})}]
        try:
            reply = provider.chat(msgs, [])
        except ProviderError as e:
            raise HTTPException(502, f"model call failed: {e}") from e
        try:
            raw = json.loads(reply["message"].get("content") or "")["changes"]
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(502, "model reply was not the requested JSON") from e
        known = {c["claim_id"] for c in claims}
        changes = [{"claim_id": c["claim_id"], **{f: c[f] for f in ("text", "value", "unit") if f in c}}
                   for c in raw if isinstance(c, dict) and c.get("claim_id") in known]
        preview = diff(claims, [{**c, **next((x for x in changes if x["claim_id"] == c["claim_id"]), {})}
                                for c in claims])
        with sessions.begin() as session:
            log(session, case_id, actor, "AI_EDIT_PROPOSED", f"{doc_type} v{version} {len(changes)} change(s) "
                f"by {provider.mode}:{provider.model}; not applied", doc_id)
        return {"applied": False, "base_version": version, "expected_sha256": sha,
                "provider_mode": provider.mode, "changes": changes, "diff": preview,
                "note": "Proposal only. Submit it through /edits to create a new version; it is then re-validated."}

    return router
