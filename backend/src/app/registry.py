"""Controlled-document registry: SOP / FMEA / Control Plan / customer templates / prior 8D, by revision.

Rows are append-only. A revision is first a DRAFT row (author), then a RELEASED row written by a different person
(quality), optionally later a WITHDRAWN row. A revision is in effect when released, its effective period covers
the moment asked about and no later released revision of the same document is in effect. Every document here is
a SYNTHETIC fixture or was raised in this demo; none is a real plant document.
"""

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ControlledDocument

KINDS = ("SOP", "FMEA", "CONTROL_PLAN", "TEMPLATE", "PRIOR_8D")
FIXTURE_AT = "2026-01-01T00:00:00+00:00"

# (number, kind, revision, title, body, site, process, customer, effective_from, effective_to, acl)
FIXTURES = [
    ("SOP-SMT-010", "SOP", 3, "Stencil cleaning and inspection",
     ("Clean the stencil every 8 hours of print time. Inspect apertures under 10x magnification after cleaning. "
     "Record cleaning in the equipment log."), "SITE-A", "PCB_SMT", "*", FIXTURE_AT, None, ["*"]),
    ("SOP-B-SMT-010", "SOP", 7, "Stencil cleaning and inspection (SITE-B)",
     "SITE-B wet-wipe stencil cleaning every 4 hours with solvent SV-2; SPI recipe S09.",
     "SITE-B", "PCB_SMT", "*", FIXTURE_AT, None, ["*"]),
    ("FMEA-SMT-001", "FMEA", 5, "SMT print process FMEA",
     ("Failure mode: insufficient solder paste. Causes: stencil wear, clogged apertures, paste viscosity. "
     "Detection: SPI volume limits, AOI. Occurrence 4, detection 5."), "SITE-A", "PCB_SMT", "*", FIXTURE_AT, None,
     ["*"]),
    ("CP-SMT-001", "CONTROL_PLAN", 2, "SMT print control plan",
     ("Characteristic: paste volume per pad. Method: SPI 100 percent. Reaction: stop line on 3 consecutive low "
     "volume boards."), "SITE-A", "PCB_SMT", "*", FIXTURE_AT, None, ["*"]),
    ("FMEA-SMT-009", "FMEA", 1, "Supplier paste FMEA (restricted)",
     "Supplier-confidential paste formulation risks. Visible to process engineering only.",
     "SITE-A", "PCB_SMT", "*", FIXTURE_AT, None, ["PROCESS_ENGINEER"]),
    ("TPL-8D-DEFAULT", "TEMPLATE", 1, "Default 8D report template",
     ("Sections D0-D8, 5W2H, IS/IS NOT, containment, root cause with experiments, corrective actions, "
     "effectiveness, prevention, closure and signatures."), "*", "*", "*", FIXTURE_AT, None, ["*"]),
    ("TPL-8D-CUSTX", "TEMPLATE", 1, "CUST-X 8D template (expired)",
     "CUST-X 8D form, superseded on 2026-06-30.", "*", "*", "CUST-X", FIXTURE_AT, "2026-06-30T00:00:00+00:00",
     ["*"]),
    ("TPL-8D-CUSTX", "TEMPLATE", 2, "CUST-X 8D template",
     "CUST-X 8D form: requires customer part number, 5W2H, containment within 24 h, D6 data, signatures.",
     "*", "*", "CUST-X", "2026-06-30T00:00:00+00:00", None, ["*"]),
]


def now() -> str:
    return datetime.now(UTC).isoformat()


def body_sha256(number: str, revision: int, title: str, body: str) -> str:
    return hashlib.sha256(f"{number}\n{revision}\n{title}\n{body}".encode()).hexdigest()


def ensure_fixtures(session: Session) -> None:
    if session.scalar(select(ControlledDocument.id).where(ControlledDocument.authored_by == "SYSTEM_FIXTURE")
                      .limit(1)):
        return
    for number, kind, rev, title, body, site, proc, cust, frm, to, acl in FIXTURES:
        session.add(ControlledDocument(
            doc_number=number, kind=kind, revision=rev, status="RELEASED", title=title, body=body, site=site,
            process_type=proc, customer=cust, effective_from=frm, effective_to=to, acl_roles=acl,
            content_sha256=body_sha256(number, rev, title, body), authored_by="SYSTEM_FIXTURE",
            released_by="SYSTEM_FIXTURE", case_id=None, created_at=FIXTURE_AT))
    session.flush()


def rows(session: Session, number: str | None = None) -> list[ControlledDocument]:
    ensure_fixtures(session)
    q = select(ControlledDocument).order_by(ControlledDocument.id)
    if number:
        q = q.where(ControlledDocument.doc_number == number)
    return list(session.scalars(q))


def revision_state(session: Session, number: str, revision: int, site: str | None = None) -> dict:
    """{"status": DRAFT|RELEASED|WITHDRAWN|MISSING, "row": latest row, "in_effect": bool, "reason": str}."""
    mine = [r for r in rows(session, number) if site is None or r.site in ("*", site)]
    revs = [r for r in mine if r.revision == revision]
    if not revs:
        return {"status": "MISSING", "row": None, "in_effect": False,
                "reason": f"{number} rev {revision} is not in the registry"}
    last = revs[-1]
    released = next((r for r in revs if r.status == "RELEASED"), None)
    at = now()
    if last.status != "RELEASED" or released is None:
        return {"status": last.status, "row": last, "in_effect": False,
                "reason": f"{number} rev {revision} is {last.status}, not a released revision"}
    if released.effective_from > at or (released.effective_to and released.effective_to <= at):
        return {"status": "RELEASED", "row": released, "in_effect": False,
                "reason": f"{number} rev {revision} is not in its effective period"}
    newer = [r for r in mine if r.revision > revision and r.status == "RELEASED" and r.effective_from <= at
             and not any(w.revision == r.revision and w.status == "WITHDRAWN" for w in mine)]
    if newer:
        return {"status": "RELEASED", "row": released, "in_effect": False,
                "reason": f"{number} rev {revision} is superseded by rev {newer[-1].revision}"}
    return {"status": "RELEASED", "row": released, "in_effect": True, "reason": ""}


def visible(row: ControlledDocument, role: str) -> bool:
    return "*" in row.acl_roles or role in row.acl_roles


def out(r: ControlledDocument) -> dict:
    return {"doc_number": r.doc_number, "kind": r.kind, "revision": r.revision, "status": r.status,
            "title": r.title, "body": r.body, "site": r.site, "process_type": r.process_type,
            "customer": r.customer, "effective_from": r.effective_from, "effective_to": r.effective_to,
            "acl_roles": r.acl_roles, "content_sha256": r.content_sha256, "authored_by": r.authored_by,
            "released_by": r.released_by, "case_id": r.case_id, "created_at": r.created_at,
            "data_origin": "SYNTHETIC"}
