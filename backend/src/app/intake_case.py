"""IN3 (spec v5.8 §23.2, §23.4): a person confirms an intake into a new case or links it to an existing one.

Nothing happens without that explicit confirmation of the draft version the person looked at. Open conflicts and
unconfirmed relative deadlines must be resolved first. The confirmed values become CUSTOMER_REPORTED evidence
(the customer's cause guess a HYPOTHESIS) that D0 and D2 can cite; no internal measurement is created or copied, so
a new case says plainly that internal data is not linked. A new case starts before D0, reusing the existing
routes and policy; linking never reopens a closed case or touches an approved document.
"""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import egress
from app.db import (
    Assignment,
    Closure,
    Evidence,
    IntakeCaseLink,
    IntakeExtraction,
    IntakeFile,
    IntakeRecord,
    QualityCase,
    SourceAsset,
    SourceEvent,
    TriageAssessment,
)
from app.intake import latest, require_intake
from app.workflow import Actor, log, now, require_case, require_role, run_idempotent

CUSTOMER_SYSTEM = "CUSTOMER_DOC"
BLOCKING = ("CONFLICT", "NEEDS_CONFIRMATION")
ORIGINS = Literal["CUSTOMER_COMPLAINT", "SUPPLIER_NONCONFORMITY", "AUDIT_FINDING", "INTERNAL_INSPECTION",
                  "RECURRING_ISSUE", "OTHER"]


class ConfirmIn(BaseModel):
    base_version: int  # the draft version the person confirmed
    action: Literal["NEW_CASE", "LINK_EXISTING"]
    case_id: str | None = None  # for LINK_EXISTING
    origin: ORIGINS = "CUSTOMER_COMPLAINT"  # for NEW_CASE


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def internal_data(session: Session, case_id: str) -> dict:
    """Whether the case has any internal (non-customer) source data. Never filled from another case."""
    n = session.scalar(select(SourceAsset.id).where(SourceAsset.case_id == case_id,
                                                    SourceAsset.source_system != CUSTOMER_SYSTEM).limit(1))
    return {"linked": n is not None,
            "note": None if n else "내부 검사·출하·SPC 데이터가 연결되지 않았습니다 (UNKNOWN). 필요한 자료: 해당 LOT의 "
                                   "SPI/AOI 기록, 출하 기록, 공정 정보. 다른 사건의 값은 복사하지 않습니다."}


def register_evidence(session: Session, case_id: str, r: IntakeRecord, x: IntakeExtraction) -> list[str]:
    """One source asset per file and one CUSTOMER_REPORTED evidence row per confirmed value, citing its locator."""
    files = {f.id: f for f in session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id))}
    asset_of: dict[int, int] = {}
    for f in files.values():
        approved = egress.tier_of(session, f) == "RAW"
        a = SourceAsset(case_id=case_id, asset_id=f"intake:{r.id}:file:{f.id}", source_system=CUSTOMER_SYSTEM,
                        entity_type="CUSTOMER_DOCUMENT", source_version=1, supersedes_asset_id=None,
                        license_id="CUSTOMER_PROVIDED", data_origin=f.data_origin,
                        sensitivity="APPROVED_FOR_EXTERNAL" if approved else "UNKNOWN",
                        captured_at=f.uploaded_at, ingested_at=now(), content_sha256=f.sha256,
                        raw_json=canonical({"intake_id": r.id, "file_id": f.id, "name": f.name}))
        session.add(a)
        session.flush()
        asset_of[f.id] = a.id
    ids = []
    for name, v in x.draft["fields"].items():
        if v.get("value") is None or v["status"] not in ("FOUND", "USER_SET"):
            continue
        src = (v.get("sources") or [{}])[0]
        file_id = src.get("file_id") or next(iter(files))
        f = files[file_id]
        record = {"field": name, "value": v["value"], "kind": v["kind"], "intake_id": r.id,
                  "draft_version": x.version, "file": f.name, "element_id": src.get("element_id"),
                  "page": src.get("page"), "excerpt": src.get("excerpt"),
                  "entered_by_person": v["status"] == "USER_SET"}
        raw = canonical(record)
        event_id = f"IN{r.id}-{len(ids) + 1}"
        ev = SourceEvent(case_id=case_id, source_asset_id=asset_of[file_id], event_id=event_id,
                         original_row_id=src.get("element_id") or "user", entity_type="CUSTOMER_REPORT",
                         entity_key=[name], event_time=f.uploaded_at, source_updated_at=None, ingested_at=now(),
                         data_origin=f.data_origin,
                         sensitivity="APPROVED_FOR_EXTERNAL" if egress.tier_of(session, f) == "RAW" else "UNKNOWN",
                         validation_status="CUSTOMER_REPORTED", raw_json=raw)
        session.add(ev)
        session.flush()
        session.add(Evidence(case_id=case_id, source_event_id=ev.id, evidence_id=f"EV-{event_id}",
                             classification=v["kind"], validity="CUSTOMER_REPORTED",
                             content_sha256=hashlib.sha256(raw.encode()).hexdigest()))
        ids.append(f"EV-{event_id}")
    return ids


def duplicates(session: Session, r: IntakeRecord, actor: Actor) -> list[dict]:
    """Earlier intakes of this user with the same file or customer reference, and the cases they went to. A
    candidate only: nothing is merged and a new case is never blocked."""
    mine = {f.sha256 for f in session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id))}
    x = latest(session, r.id)
    ref = x.draft["fields"]["customer_ref"]["value"] if x else None
    out = []
    for other in session.scalars(select(IntakeRecord).where(IntakeRecord.owner_id == actor.id,
                                                            IntakeRecord.id != r.id)):
        same_file = bool(mine & {f.sha256 for f in session.scalars(
            select(IntakeFile).where(IntakeFile.intake_id == other.id))})
        ox = latest(session, other.id)
        same_ref = bool(ref) and ox is not None and ox.draft["fields"]["customer_ref"]["value"] == ref
        if same_file or same_ref:
            link = session.scalar(select(IntakeCaseLink).where(IntakeCaseLink.intake_id == other.id))
            out.append({"intake_id": other.id, "same_file": same_file, "same_customer_ref": same_ref,
                        "case_id": link.case_id if link else None})
    return out


def make_intake_case_router(sessions: sessionmaker, current_user) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    @router.get("/intakes/{intake_id}/duplicates")
    def dup(intake_id: int, actor: Who) -> list[dict]:
        with sessions() as session:
            return duplicates(session, require_intake(session, intake_id, actor), actor)

    @router.post("/intakes/{intake_id}/confirm", status_code=201)
    def confirm(intake_id: int, body: ConfirmIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            r = require_intake(session, intake_id, actor)
            if session.scalar(select(IntakeCaseLink).where(IntakeCaseLink.intake_id == r.id)):
                raise HTTPException(409, "This intake is already linked to a case")
            x = latest(session, r.id)
            if x is None:
                raise HTTPException(409, "No draft to confirm: analyze the files or enter the values first")
            if body.base_version != x.version:
                raise HTTPException(409, f"Draft changed (now v{x.version}); review it again before confirming")
            if open_items := sorted(k for k, v in x.draft["fields"].items() if v["status"] in BLOCKING):
                raise HTTPException(409, "확인이 필요한 항목이 있습니다: " + ", ".join(open_items)
                                    + " (값을 선택하거나 직접 입력한 뒤 확인하세요)")
            files = session.scalars(select(IntakeFile).where(IntakeFile.intake_id == r.id)).all()
            confirmed = [k for k, v in x.draft["fields"].items()
                         if v.get("value") and v["status"] in ("FOUND", "USER_SET")]
            if body.action == "NEW_CASE" and not confirmed:
                raise HTTPException(409, "확인된 값이 하나도 없습니다: 원문을 보고 최소한 현상이나 고객 참조번호를 입력한 뒤 "
                                         "사건을 만드세요 (근거 없는 사건은 D0에서 인용할 증거가 없습니다)")
            if body.action == "NEW_CASE":
                case_id = f"CC-{r.id}"
                if session.get(QualityCase, case_id):
                    raise HTTPException(409, f"Case {case_id} already exists")
                session.add(QualityCase(
                    id=case_id, domain="PCB", origin=body.origin, channel=r.channel, owner_id=actor.id,
                    data_origin="SYNTHETIC" if all(f.data_origin == "SYNTHETIC" for f in files) else "UNKNOWN"))
                session.flush()
                session.add(Assignment(case_id=case_id, user_id=actor.id))
            else:
                if not body.case_id:
                    raise HTTPException(422, "case_id is required to link to an existing case")
                require_case(session, body.case_id, actor)  # access and existence, rechecked now
                case_id = body.case_id
                last = session.scalar(select(Closure).where(Closure.case_id == case_id)
                                      .order_by(Closure.id.desc()).limit(1))
                if last is not None and last.decision == "CLOSED":
                    raise HTTPException(409, "종결된 사건입니다. 자동으로 재개하지 않습니다: 새 사건으로 접수하거나 "
                                             "재개 절차를 사람이 진행하세요.")
            ids = register_evidence(session, case_id, r, x)
            session.add(IntakeCaseLink(intake_id=r.id, case_id=case_id, mode="NEW" if body.action == "NEW_CASE"
                                       else "EXISTING", extraction_version=x.version, evidence_ids=ids,
                                       linked_by=actor.id, linked_at=now()))
            log(session, case_id, actor, "INTAKE_LINKED", f"intake {r.id} draft v{x.version} "
                f"{'new case' if body.action == 'NEW_CASE' else 'linked'}: {len(ids)} customer-reported values")
            session.flush()
            return 201, case_view(session, case_id)
        return run_idempotent(sessions, f"intake_confirm:{intake_id}", key, actor, run)

    def case_view(session: Session, case_id: str) -> dict:
        case = session.get(QualityCase, case_id)
        links = session.scalars(select(IntakeCaseLink).where(IntakeCaseLink.case_id == case_id)
                                .order_by(IntakeCaseLink.id)).all()
        d0 = session.scalar(select(TriageAssessment.id).where(TriageAssessment.case_id == case_id).limit(1))
        return {"case_id": case.id, "origin": case.origin, "channel": case.channel, "owner_id": case.owner_id,
                "data_origin": case.data_origin, "d0": "DONE" if d0 else "PENDING",
                "assignees": sorted(session.scalars(select(Assignment.user_id).where(Assignment.case_id == case_id))),
                "internal_data": internal_data(session, case_id),
                "intakes": [{"intake_id": k.intake_id, "mode": k.mode, "draft_version": k.extraction_version,
                             "evidence_ids": k.evidence_ids, "linked_by": k.linked_by, "linked_at": k.linked_at}
                            for k in links]}

    @router.get("/cases/{case_id}/intakes")
    def case_intakes(case_id: str, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)
            return case_view(session, case_id)

    return router
