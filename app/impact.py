"""S6 evidence dependency graph, deterministic BFS impact analysis and source revision import.

Nodes: source evidence (EV-...), model evidence (PRED-n, XAI-n), claims (CLAIM:<doc id>:<claim id>) and
documents (DOC:<doc id>). A corrected source row reopens only the documents reachable from its old evidence.
"""

import hashlib
from collections import defaultdict, deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import (
    DataQualityIssue,
    DocumentVersion,
    Evidence,
    EvidenceDependency,
    Review,
    SourceAsset,
    SourceEvent,
)
from app.ingestion import SourceAssetInput, SyntheticBundle, normalize
from app.synthetic import canonical

ACTIVE = ("DRAFT", "IN_REVIEW", "INFO_REQUESTED", "APPROVED")


def link(session: Session, case_id: str, edges: set[tuple[str, str]]) -> None:
    have = set(session.execute(select(EvidenceDependency.src, EvidenceDependency.dst)
                               .where(EvidenceDependency.case_id == case_id)).all())
    session.add_all(EvidenceDependency(case_id=case_id, src=s, dst=d) for s, d in sorted(edges - have))


def link_document(session: Session, doc: DocumentVersion, claims: list[dict]) -> None:
    edges = set()
    for c in claims:
        node = f"CLAIM:{doc.id}:{c['claim_id']}"
        edges |= {(ev, node) for ev in c["evidence_ids"]}
        if c["evidence_ids"]:
            edges.add((node, f"DOC:{doc.id}"))
    link(session, doc.case_id, edges)


def reachable(session: Session, case_id: str, seeds: list[str]) -> list[str]:
    adj: dict[str, list[str]] = defaultdict(list)
    for e in session.scalars(select(EvidenceDependency).where(EvidenceDependency.case_id == case_id)
                             .order_by(EvidenceDependency.id)):
        adj[e.src].append(e.dst)
    seen, queue = set(seeds), deque(seeds)
    while queue:
        for nxt in adj[queue.popleft()]:
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return sorted(seen - set(seeds))


def import_revision(session: Session, case_id: str, asset: SourceAssetInput) -> list[str]:
    """Store a corrected source asset; return evidence ids of the rows it supersedes. Raises ValueError."""
    old = session.scalar(select(SourceAsset).where(SourceAsset.case_id == case_id,
                                                   SourceAsset.asset_id == asset.supersedes_asset_id))
    if old is None or old.entity_type != asset.entity_type:
        raise ValueError("supersedes_asset_id must name an asset of the same type in this case")
    top = max(session.scalars(select(SourceAsset.source_version).where(
        SourceAsset.case_id == case_id, SourceAsset.entity_type == asset.entity_type)))
    if old.source_version != top or asset.source_version <= top:
        raise ValueError(f"revision must supersede the latest {asset.entity_type} asset (v{top}) with a higher version")
    if session.scalar(select(SourceAsset.id).where(SourceAsset.case_id == case_id,
                                                   SourceAsset.asset_id == asset.asset_id)):
        raise ValueError("asset_id already exists in this case")
    # Same contract checks as S1 upload (license, hash, origin, keys, timestamps). Cross-asset link checks
    # do not apply to a lone correction; each row must instead match a row that already passed them.
    events, _ = normalize(SyntheticBundle(generator_version="revision", seed=0, data_origin="SYNTHETIC",
                                          assets=[asset.model_copy(update={"supersedes_asset_id": None})]))
    stored = SourceAsset(case_id=case_id, asset_id=asset.asset_id, source_system=asset.source_system,
                         entity_type=asset.entity_type, source_version=asset.source_version,
                         supersedes_asset_id=asset.supersedes_asset_id, license_id=asset.license_id,
                         data_origin=asset.data_origin, sensitivity=asset.sensitivity,
                         captured_at=asset.captured_at.isoformat(), ingested_at=asset.ingested_at.isoformat(),
                         content_sha256=asset.content_sha256, raw_json=canonical(asset.records))
    session.add(stored)
    session.flush()
    changed: list[str] = []
    for e in events:
        prior = session.execute(select(SourceEvent, Evidence).join(Evidence, Evidence.source_event_id == SourceEvent.id)
                                .where(SourceEvent.case_id == case_id, SourceEvent.entity_type == e["entity_type"],
                                       SourceEvent.original_row_id == e["original_row_id"])).all()
        if not prior:
            raise ValueError(f"row {e['original_row_id']} does not exist; a revision may only correct rows")
        if any(p.entity_key != e["entity_key"] for p, _ in prior):
            raise ValueError(f"row {e['original_row_id']} changes its manufacturing key")
        changed += [v.evidence_id for _, v in prior]
        validity = "CHECKED" if any(v.validity == "CHECKED" for _, v in prior) else "INVALID_LINK"
        row = SourceEvent(case_id=case_id, source_asset_id=stored.id, event_id=e["id"],
                          original_row_id=e["original_row_id"], entity_type=e["entity_type"],
                          entity_key=e["entity_key"], event_time=e["event_time"],
                          source_updated_at=e["source_updated_at"], ingested_at=e["ingested_at"],
                          data_origin=e["data_origin"], sensitivity=e["sensitivity"], validation_status=validity,
                          raw_json=e["raw_json"])
        session.add(row)
        session.flush()
        session.add(Evidence(case_id=case_id, source_event_id=row.id, evidence_id=f"EV-{e['id']}",
                             classification="OBSERVED", validity=validity,
                             content_sha256=hashlib.sha256(e["raw_json"].encode()).hexdigest()))
        session.add(DataQualityIssue(case_id=case_id, event_id=e["id"], code="SOURCE_CORRECTION",
                                     severity="INFO", detail=asset.supersedes_asset_id))
    return sorted(set(changed))


def reopen(session: Session, case_id: str, seeds: list[str]) -> dict:
    """Mark only the reachable active documents REVALIDATION_REQUIRED and hold their pending reviews.

    Approval events are never touched; superseded/rejected versions are reported but left as they are.
    """
    nodes = reachable(session, case_id, seeds)
    claims = [n for n in nodes if n.startswith("CLAIM:")]
    docs = []
    for doc_id in sorted({int(n.split(":")[1]) for n in nodes if n.startswith("DOC:")}):
        doc = session.get(DocumentVersion, doc_id)
        before = doc.status
        if before in ACTIVE:
            doc.status = "REVALIDATION_REQUIRED"
            for r in session.scalars(select(Review).where(Review.document_version_id == doc.id,
                                                          Review.state == "PENDING")):
                r.state = "HELD"
        docs.append({"document_version_id": doc.id, "doc_type": doc.doc_type, "version": doc.version,
                     "status_before": before, "status_after": doc.status,
                     "claims": sorted((n.split(":")[2] for n in claims if n.split(":")[1] == str(doc.id)),
                                      key=lambda cid: int(cid[1:]))})
    return {"derived": [n for n in nodes if n.startswith(("PRED-", "XAI-"))], "claims": claims, "documents": docs}
