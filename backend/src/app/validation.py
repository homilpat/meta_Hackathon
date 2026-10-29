"""Document validation runs, TemplateContracts and controlled-document search (G8).

A ValidationRun pins what was checked: document content hash, a hash of the cited evidence (content + quality
state + referenced action/cause/document states), the WorkflowPolicy hash, the TemplateContract hash and the
rules version. A run is stale as soon as any of them differs now. Template candidates may be retrieved by text,
but which contract applies is decided by deterministic rules (customer, effective period, document type), and
conformance is checked by the contract's rules, never by retrieval or a model.
"""

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import actions, causes, factcheck, quality, registry, retrieval
from app.db import (
    Action,
    CauseHypothesis,
    DocumentClaim,
    DocumentVersion,
    Evidence,
    ProcessContext,
    TemplateContract,
    ValidationRun,
)
from app.workflow import KINDS, Actor, log, require_case

FIXTURE_AT = registry.FIXTURE_AT
ALL = ["NCR", "CONTAINMENT", "RCA"]
# (contract_id, version, customer, doc_types, effective_from, effective_to, template doc, rules)
FIXTURES = [
    ("DEFAULT-8D", 1, "*", ALL, FIXTURE_AT, None, "TPL-8D-DEFAULT:1",
     {"NCR": [{"pattern": r"5W2H", "min": 1, "label": "5W2H problem statement"},
              {"pattern": r"^IS:|IS / IS NOT", "min": 1, "label": "IS / IS NOT"}],
      "CONTAINMENT": [{"classification": "PROPOSAL", "min": 1, "label": "containment proposal"}],
      "RCA": [{"classification": "HYPOTHESIS", "min": 1, "label": "cause hypothesis"}]}),
    ("CUSTX-8D", 1, "CUST-X", ALL, FIXTURE_AT, "2026-06-30T00:00:00+00:00", "TPL-8D-CUSTX:1",
     {"NCR": [{"pattern": r"5W2H", "min": 1, "label": "5W2H problem statement"}]}),
    ("CUSTX-8D", 2, "CUST-X", ALL, "2026-06-30T00:00:00+00:00", None, "TPL-8D-CUSTX:2",
     {"NCR": [{"pattern": r"5W2H", "min": 1, "label": "5W2H problem statement"},
              {"pattern": r"customer part number", "min": 1, "label": "customer part number"}],
      "CONTAINMENT": [{"classification": "PROPOSAL", "min": 1, "label": "containment proposal"}],
      "RCA": [{"classification": "HYPOTHESIS", "min": 1, "label": "cause hypothesis"}]}),
]


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def ensure_contracts(session: Session) -> None:
    if session.scalar(select(TemplateContract.id).limit(1)):
        return
    for cid, ver, cust, types, frm, to, tpl, rules in FIXTURES:
        body = {"contract_id": cid, "version": ver, "customer": cust, "doc_types": types, "effective_from": frm,
                "effective_to": to, "template_doc": tpl, "rules": rules}
        session.add(TemplateContract(**body, site="*", process_type="*", contract_hash=sha(body),
                                     authorized_by="SYSTEM_FIXTURE", created_at=FIXTURE_AT))
    session.flush()


def contract_ref(t: TemplateContract) -> str:
    return f"{t.contract_id}:{t.version}"


def _customer(session: Session, case_id: str) -> str:
    return session.scalar(select(ProcessContext.customer).where(ProcessContext.case_id == case_id)) or "DEFAULT"


def _applicable(t: TemplateContract, customer: str, doc_type: str, at: str) -> str | None:
    """Why the contract does not apply to this case/document now (None = it applies)."""
    if t.customer not in ("*", customer):
        return f"{contract_ref(t)} is for customer {t.customer}, the case customer is {customer}"
    if doc_type not in t.doc_types:
        return f"{contract_ref(t)} does not cover {doc_type}"
    if t.effective_from > at or (t.effective_to and t.effective_to <= at):
        return f"{contract_ref(t)} is not in effect (from {t.effective_from} to {t.effective_to or 'open'})"
    return None


def select_contract(session: Session, case_id: str, doc_type: str,
                    override: str | None = None) -> tuple[TemplateContract | None, list[dict]]:
    ensure_contracts(session)
    at, customer = now(), _customer(session, case_id)
    rows = list(session.scalars(select(TemplateContract).order_by(TemplateContract.id)))
    if override:
        t = next((r for r in rows if contract_ref(r) == override), None)
        if t is None:
            return None, [{"claim_id": None, "code": "TEMPLATE_UNKNOWN", "severity": "BLOCK",
                           "message": f"template contract {override} does not exist"}]
        why = _applicable(t, customer, doc_type, at)
        chosen = t
    else:
        ok = [r for r in rows if _applicable(r, customer, doc_type, at) is None]
        chosen = max(ok, key=lambda r: (r.customer != "*", r.version), default=None)
        why = None if chosen else f"no template contract applies to {doc_type} for customer {customer}"
    issues = [{"claim_id": None, "code": "TEMPLATE_NOT_APPLICABLE", "severity": "BLOCK", "message": why}] if why else []
    if chosen is not None:
        num, rev = chosen.template_doc.rsplit(":", 1)
        st = registry.revision_state(session, num, int(rev))
        if not st["in_effect"]:
            issues.append({"claim_id": None, "code": "TEMPLATE_DOC_STALE", "severity": "BLOCK",
                           "message": f"template document {chosen.template_doc}: {st['reason']}"})
    return chosen, issues


def contract_issues(t: TemplateContract, doc_type: str, claims: list[dict]) -> list[dict]:
    out = []
    for rule in t.rules.get(doc_type, []):
        hits = [c for c in claims if (not rule.get("classification") or c["classification"] == rule["classification"])
                and (not rule.get("pattern") or re.search(rule["pattern"], c["text"], re.IGNORECASE | re.MULTILINE))]
        if len(hits) < rule["min"]:
            out.append({"claim_id": None, "code": "TEMPLATE_MISSING_FIELD", "severity": "BLOCK",
                        "message": f"{contract_ref(t)} requires {rule['label']} (found {len(hits)}, "
                                   f"need {rule['min']})"})
    return out


def evidence_hash(session: Session, case_id: str, claims: list[dict]) -> str:
    """Cited rows (content + quality state) and the current state of every referenced case object."""
    ids = sorted({e for c in claims for e in c["evidence_ids"]})
    rows = dict(session.execute(select(Evidence.evidence_id, Evidence.content_sha256).where(
        Evidence.case_id == case_id, Evidence.evidence_id.in_(ids))).all())
    states = quality.current(session, case_id, set(rows)) if rows else {}
    out = []
    for e in ids:
        if e in rows:
            out.append([e, rows[e], states[e]["quality_state"]])
        elif m := factcheck.REF.match(e):
            if m.group(1) == "ACT" and session.get(Action, int(m.group(2))):
                out.append([e, actions.status(session, int(m.group(2)))])
            elif m.group(1) == "H" and session.get(CauseHypothesis, int(m.group(2))):
                out.append([e, causes.status(session, int(m.group(2)))])
            elif m.group(3):
                st = registry.revision_state(session, m.group(3), int(m.group(4)))
                out.append([e, st["status"], st["in_effect"], st["row"].content_sha256 if st["row"] else None])
            else:
                out.append([e, "?"])
    return sha(out)


def claims_of(session: Session, doc: DocumentVersion) -> list[dict]:
    rows = session.scalars(select(DocumentClaim).where(DocumentClaim.document_version_id == doc.id)
                           .order_by(DocumentClaim.id)).all()
    return [{"claim_id": c.claim_id, "classification": c.classification, "text": c.text, "value": c.value,
             "unit": c.unit, "evidence_ids": c.evidence_ids} for c in rows]


def current_hashes(session: Session, doc: DocumentVersion, contract: TemplateContract | None) -> dict:
    from app.eightd import active_policy

    return {"document_sha256": doc.content_sha256,
            "evidence_sha256": evidence_hash(session, doc.case_id, claims_of(session, doc)),
            "policy_hash": active_policy(session, doc.case_id).policy_hash,
            "template_hash": contract.contract_hash if contract else None,
            "rules_version": factcheck.RULES_VERSION}


def run(session: Session, doc: DocumentVersion, actor: Actor, override: str | None = None) -> ValidationRun:
    claims = claims_of(session, doc)
    checked = factcheck.validate(session, doc.case_id, claims, actor.role)
    contract, t_issues = select_contract(session, doc.case_id, doc.doc_type, override)
    issues = checked["issues"] + t_issues + (contract_issues(contract, doc.doc_type, claims) if contract else [])
    result = "BLOCK" if any(i["severity"] == "BLOCK" for i in issues) else (
        "WARN" if any(i["severity"] == "WARN" for i in issues) else "PASS")
    h = current_hashes(session, doc, contract)
    v = ValidationRun(case_id=doc.case_id, document_version_id=doc.id, contract_ref=contract_ref(contract)
                      if contract else None, result=result, issues=issues, predicates=checked["predicates"],
                      validated_by=actor.id, validated_at=now(), **h)
    session.add(v)
    session.flush()
    return v


def stale_reasons(session: Session, v: ValidationRun) -> list[str]:
    doc = session.get(DocumentVersion, v.document_version_id)
    contract = None
    if v.contract_ref:
        contract = next((t for t in session.scalars(select(TemplateContract))
                         if contract_ref(t) == v.contract_ref), None)
    now_h = current_hashes(session, doc, contract)
    names = {"document_sha256": "document content", "evidence_sha256": "cited evidence or referenced state",
             "policy_hash": "workflow policy", "template_hash": "template contract", "rules_version": "rules"}
    return [f"{names[k]} changed since validation" for k in names if getattr(v, k) != now_h[k]]


def latest_run(session: Session, doc: DocumentVersion) -> ValidationRun | None:
    return session.scalar(select(ValidationRun).where(ValidationRun.document_version_id == doc.id)
                          .order_by(ValidationRun.id.desc()).limit(1))


def run_out(session: Session, v: ValidationRun) -> dict:
    stale = stale_reasons(session, v)
    return {"validation_id": v.id, "document_version_id": v.document_version_id, "result": v.result,
            "issues": v.issues, "predicates": v.predicates, "contract_ref": v.contract_ref,
            "hashes": {k: getattr(v, k) for k in ("document_sha256", "evidence_sha256", "policy_hash",
                                                   "template_hash", "rules_version")},
            "validated_by": v.validated_by, "validated_at": v.validated_at, "stale": bool(stale),
            "stale_reasons": stale}


# --- controlled-document search ----------------------------------------------------------------------------

def search_documents(session: Session, case_id: str, role: str, query: str, kind: str | None = None,
                     k: int = 5) -> dict:
    """Pre-filter (kind, ACL, site, process, customer, in effect) THEN rank by BM25. Excluded rows are only counted."""
    pc = session.scalar(select(ProcessContext).where(ProcessContext.case_id == case_id))
    site, proc, cust = (pc.site, pc.process_type, pc.customer) if pc else (None, None, "DEFAULT")
    excluded: dict[str, int] = {}
    cands = []
    latest = {}
    for r in registry.rows(session):
        latest[(r.doc_number, r.revision)] = r
    for r in latest.values():
        if kind and r.kind != kind:
            continue
        reason = None
        if not registry.visible(r, role):
            reason = "ACCESS"
        elif site and r.site not in ("*", site):
            reason = "OTHER_SITE"
        elif proc and r.process_type not in ("*", proc):
            reason = "OTHER_PROCESS"
        elif r.customer not in ("*", cust):
            reason = "OTHER_CUSTOMER"
        elif not registry.revision_state(session, r.doc_number, r.revision, None if r.site == "*" else r.site)[
                "in_effect"]:
            reason = "NOT_IN_EFFECT"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
        else:
            cands.append(r)
    scores = retrieval.bm25(query, [f"{r.title} {r.body}" for r in cands])
    ranked = sorted(((s, hit, r) for (s, hit), r in zip(scores, cands, strict=True) if s > 0),
                    key=lambda t: (-t[0], t[2].doc_number))[:k]
    return {"query": query, "method": retrieval.VERSION, "excluded": excluded,
            "results": [{"ref": f"DOC:{r.doc_number}:{r.revision}", "doc_number": r.doc_number, "kind": r.kind,
                         "revision": r.revision, "title": r.title, "matched_terms": hit, "bm25": s,
                         "effective_from": r.effective_from, "content_sha256": r.content_sha256,
                         "data_origin": "SYNTHETIC"} for s, hit, r in ranked],
            "note": "Retrieval ranks candidates; only TemplateContract rules decide template conformance."}


class ValidateIn(BaseModel):
    contract_ref: str | None = None  # default: the deterministic selection for this case and document type


def make_validation_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    from app.workflow import _get_doc

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.get("/template-contracts")
    def contracts(actor: Who) -> list[dict]:
        with sessions.begin() as session:
            ensure_contracts(session)
            return [{"ref": contract_ref(t), "customer": t.customer, "doc_types": t.doc_types,
                     "effective_from": t.effective_from, "effective_to": t.effective_to,
                     "template_doc": t.template_doc, "rules": t.rules, "contract_hash": t.contract_hash}
                    for t in session.scalars(select(TemplateContract).order_by(TemplateContract.id))]

    @router.post("/cases/{case_id}/{kind:doc}/{version}/validate", status_code=201)
    def validate_doc(case_id: str, kind: str, version: int, actor: Who, body: ValidateIn | None = None) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            doc = _get_doc(session, case_id, version, KINDS[kind])
            v = run(session, doc, actor, (body or ValidateIn()).contract_ref)
            log(session, case_id, actor, "VALIDATED", f"{doc.doc_type} v{version} {v.result} "
                f"issues={len(v.issues)} contract={v.contract_ref} rules={v.rules_version}", doc.id)
            return run_out(session, v)

    @router.get("/cases/{case_id}/{kind:doc}/{version}/validation")
    def get_validation(case_id: str, kind: str, version: int, actor: Who) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            v = latest_run(session, _get_doc(session, case_id, version, KINDS[kind]))
            if v is None:
                raise HTTPException(404, "not validated yet")
            return run_out(session, v)

    @router.get("/cases/{case_id}/documents/search")
    def doc_search(case_id: str, actor: Who, q: str = "", kind: str | None = None) -> dict:  # access before input
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            return search_documents(session, case_id, actor.role, q, kind)

    return router
