"""Tamper-evident audit trail.

Every row added to an audited table is chained in the same transaction: sha256(previous link, table, row id,
row content). Triggers stop UPDATE/DELETE through the app; the chain makes it detectable when someone with
database access bypasses them (drops a trigger, edits, deletes or inserts rows). verify() recomputes it.
"""

import hashlib
import json

from sqlalchemy import event, insert, select
from sqlalchemy.orm import Session

from app.db import AuditChain, Base

AUDITED = ("approval_events", "workflow_events", "doc_comments")
TABLES = {m.class_.__tablename__: m.class_ for m in Base.registry.mappers if m.class_.__tablename__ in AUDITED}
GENESIS = "0" * 64


def digest(prev: str, table: str, row) -> str:
    content = {c.key: getattr(row, c.key) for c in row.__table__.columns}
    body = json.dumps([prev, table, row.id, content], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def chain(session: Session, rows) -> None:
    """Append links for rows (already flushed, so they have ids). Writers are serialised by BEGIN IMMEDIATE."""
    conn = session.connection()
    prev = conn.execute(select(AuditChain.sha256).order_by(AuditChain.id.desc()).limit(1)).scalar() or GENESIS
    for row in sorted(rows, key=lambda r: (r.__tablename__, r.id)):
        link = digest(prev, row.__tablename__, row)
        conn.execute(insert(AuditChain).values(table_name=row.__tablename__, row_id=row.id, prev_sha256=prev,
                                               sha256=link))
        prev = link


@event.listens_for(Session, "after_flush")
def _chain_new_rows(session: Session, _ctx) -> None:
    rows = [o for o in session.new if getattr(o, "__tablename__", None) in AUDITED]
    if rows:
        chain(session, rows)


def backfill(session: Session) -> int:
    """Chain audit rows that predate the chain (used by the migration)."""
    have = set(session.execute(select(AuditChain.table_name, AuditChain.row_id)).all())
    rows = [r for t, cls in TABLES.items() for r in session.scalars(select(cls).order_by(cls.id))
            if (t, r.id) not in have]
    chain(session, rows)
    return len(rows)


def verify(session: Session) -> dict:
    links = session.scalars(select(AuditChain).order_by(AuditChain.id)).all()
    prev, breaks, chained = GENESIS, [], set()
    for link in links:
        chained.add((link.table_name, link.row_id))
        row = session.get(TABLES[link.table_name], link.row_id)
        where = {"table": link.table_name, "row_id": link.row_id, "link_id": link.id}
        if link.prev_sha256 != prev:
            breaks.append({**where, "problem": "LINK_BROKEN"})  # a link was removed or rewritten
        if row is None:
            breaks.append({**where, "problem": "DELETED"})
        elif digest(link.prev_sha256, link.table_name, row) != link.sha256:
            breaks.append({**where, "problem": "MODIFIED"})
        prev = link.sha256
    for table, cls in TABLES.items():
        for row_id in session.scalars(select(cls.id)):
            if (table, row_id) not in chained:
                breaks.append({"table": table, "row_id": row_id, "link_id": None, "problem": "UNCHAINED"})
    return {"ok": not breaks, "links": len(links), "head_sha256": prev, "breaks": breaks[:50]}
