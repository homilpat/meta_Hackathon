"""What of a customer file may leave, and in what form (spec v5.8 §23.5: an upload is not an egress approval).

Three tiers per file:
  RAW     the original text and images go to the external model: a shipped SYNTHETIC fixture, or a file a quality
          manager (QA_PRODUCTION, not the person who asked) approved for external processing, with a reason.
  MASKED  everything else, by default: only words of an allowlist (form labels and function words) stay; every other
          word, number and date becomes a token ([T3], [N2], [D1]); no images. The model can still find which line or
          cell holds which field, but not what the phenomenon, quantity or customer is. Tokens are mapped back on the
          server; the map never leaves.
  LOCAL   when an in-house model is configured (LOCAL_MODEL_URL, OpenAI-compatible), unapproved files go to it as is
          and nothing leaves the site.
The masked payload that was actually sent is kept (with its hash) on the extraction, so what left can be shown.
"""

import json
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import IntakeEgressEvent, IntakeFile, IntakeRecord
from app.fields import FreeText
from app.workflow import Actor, now, require_role

APPROVER_ROLE = "QA_PRODUCTION"
# Form words that may stay readable: field labels and connectives, never values. Matching is case-insensitive.
ALLOW = {"a", "an", "the", "of", "on", "in", "at", "by", "for", "to", "and", "or", "with", "from", "after", "before", "per", "is", "are", "was", "were", "be", "been", "this", "that", "these", "those", "as", "customer", "contact", "reference", "ref", "issued", "issue", "date", "delivery", "delivered", "found", "found:", "phenomenon", "request", "requested", "reply", "replies", "lot", "lots", "serial", "range", "part", "number", "no", "qty", "quantity", "defective", "inspected", "unit", "units", "total", "page", "fig", "figure", "table", "photo", "chart", "caption", "note", "notes", "remark", "remarks", "supplier", "audit", "finding", "standard", "clause", "department", "evidence", "due", "containment", "root", "cause", "corrective", "action", "actions", "report", "complaint", "supplement", "requirement", "attachment", "item", "items", "please", "within", "hours", "days", "week", "weeks", "result", "results", "status", "record", "records", "hold", "verification", "verified", "test", "고객", "고객사", "담당자", "참조번호", "발행", "발행일", "납품", "납품일", "발견", "발견일", "현상", "요청", "요청사항", "회신", "기한", "품번", "제품", "일련번호", "수량", "검사", "불량", "단위", "합계", "그림", "표", "사진", "차트", "비고", "보완", "자료", "결과", "원인", "추정", "조치", "봉쇄", "시정", "감사", "지적", "기준", "부서", "증거", "첨부", "및", "의", "에서"}
WORD = re.compile(r"[A-Za-z가-힣]+(?:[-'][A-Za-z가-힣]+)*|\d+(?:[.,:/-]\d+)*")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")


class Masker:
    """One token per distinct word for one model call; the same word always gets the same token."""

    def __init__(self):
        self.to_token: dict[str, str] = {}
        self.to_word: dict[str, str] = {}
        self.n = {"T": 0, "N": 0, "D": 0}

    def token(self, w: str) -> str:
        if w not in self.to_token:
            kind = "D" if DATE.fullmatch(w) else "N" if w[0].isdigit() else "T"
            self.n[kind] += 1
            t = f"[{kind}{self.n[kind]}]"
            self.to_token[w], self.to_word[t] = t, w
        return self.to_token[w]

    def mask(self, text: str) -> str:
        return WORD.sub(lambda m: m.group(0) if m.group(0).lower() in ALLOW else self.token(m.group(0)), text or "")

    def unmask(self, text: str) -> str:
        return re.sub(r"\[[TND]\d+\]", lambda m: self.to_word.get(m.group(0), m.group(0)), text or "")

    def unmask_obj(self, obj):
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, list):
            return [self.unmask_obj(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        return obj


MASK_NOTE = ("Some words were replaced by tokens like [T3], [N2] or [D1] before sending. Copy tokens exactly as they "
             "appear in values and excerpts; never guess what a token stands for.")


def approved(session: Session, f: IntakeFile) -> bool:
    last = session.scalar(select(IntakeEgressEvent).where(IntakeEgressEvent.file_id == f.id,
                                                          IntakeEgressEvent.event != "REQUESTED")
                          .order_by(IntakeEgressEvent.id.desc()).limit(1))
    return last is not None and last.event == "APPROVED"


def tier_of(session: Session, f: IntakeFile) -> Literal["RAW", "PROTECTED"]:
    """RAW may leave as is; PROTECTED leaves only masked, or stays for a local model."""
    return "RAW" if f.data_origin == "SYNTHETIC" or approved(session, f) else "PROTECTED"


def egress_view(session: Session, f: IntakeFile) -> dict:
    events = session.scalars(select(IntakeEgressEvent).where(IntakeEgressEvent.file_id == f.id)
                             .order_by(IntakeEgressEvent.id)).all()
    return {"tier": tier_of(session, f), "approved": approved(session, f),
            "events": [{"event": e.event, "actor_id": e.actor_id, "actor_role": e.actor_role, "reason": e.reason,
                        "at": e.created_at} for e in events]}


class EgressAsk(BaseModel):
    reason: FreeText


class EgressDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reason: FreeText


def make_egress_router(sessions: sessionmaker, current_user) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    def own_file(session: Session, intake_id: int, file_id: int, actor: Actor) -> IntakeFile:
        r = session.get(IntakeRecord, intake_id)
        f = session.get(IntakeFile, file_id)
        if r is None or r.owner_id != actor.id or f is None or f.intake_id != intake_id:
            raise HTTPException(404, "File not found")
        return f

    def pending(session: Session) -> list[IntakeFile]:
        out = []
        for f in session.scalars(select(IntakeFile).order_by(IntakeFile.id)):
            last = session.scalar(select(IntakeEgressEvent).where(IntakeEgressEvent.file_id == f.id)
                                  .order_by(IntakeEgressEvent.id.desc()).limit(1))
            if last is not None and last.event == "REQUESTED":
                out.append(f)
        return out

    def add(session: Session, f: IntakeFile, event: str, actor: Actor, reason: str) -> None:
        session.add(IntakeEgressEvent(file_id=f.id, event=event, actor_id=actor.id, actor_role=actor.role,
                                      reason=reason, created_at=now()))

    @router.post("/intakes/{intake_id}/files/{file_id}/egress-request", status_code=201)
    def ask(intake_id: int, file_id: int, body: EgressAsk, actor: Who) -> dict:
        with sessions.begin() as session:
            f = own_file(session, intake_id, file_id, actor)
            if tier_of(session, f) == "RAW":
                raise HTTPException(409, "this file may already be sent as is")
            if f in pending(session):
                raise HTTPException(409, "a request is already waiting for a decision")
            add(session, f, "REQUESTED", actor, body.reason)
            session.flush()
            return egress_view(session, f)

    @router.get("/egress-approvals")
    def queue(actor: Who) -> list[dict]:
        require_role(actor, APPROVER_ROLE)
        with sessions() as session:
            out = []
            for f in pending(session):
                ask_ev = session.scalar(select(IntakeEgressEvent).where(IntakeEgressEvent.file_id == f.id)
                                        .order_by(IntakeEgressEvent.id.desc()).limit(1))
                out.append({"file_id": f.id, "intake_id": f.intake_id, "name": f.name, "media_type": f.media_type,
                            "size": f.size, "sha256": f.sha256, "requested_by": ask_ev.actor_id,
                            "reason": ask_ev.reason, "requested_at": ask_ev.created_at})
            return out

    @router.get("/egress-approvals/{file_id}/content")
    def content(file_id: int, actor: Who) -> Response:
        """The approver may read a file only while its approval is pending (to judge what it contains)."""
        require_role(actor, APPROVER_ROLE)
        with sessions() as session:
            f = session.get(IntakeFile, file_id)
            if f is None or f not in pending(session):
                raise HTTPException(404, "No pending approval for this file")
            return Response(f.content, media_type=f.media_type, headers={
                "Content-Disposition": f'attachment; filename="egress-{file_id}"', "X-Content-Type-Options": "nosniff"})

    @router.post("/egress-approvals/{file_id}", status_code=201)
    def decide(file_id: int, body: EgressDecision, actor: Who) -> dict:
        require_role(actor, APPROVER_ROLE)
        with sessions.begin() as session:
            f = session.get(IntakeFile, file_id)
            if f is None or f not in pending(session):
                raise HTTPException(409, "No pending approval for this file")
            asked = session.scalar(select(IntakeEgressEvent).where(IntakeEgressEvent.file_id == f.id)
                                   .order_by(IntakeEgressEvent.id.desc()).limit(1))
            if asked.actor_id == actor.id:
                raise HTTPException(403, "the person who asked cannot approve")
            add(session, f, body.decision, actor, body.reason)
            session.flush()
            return egress_view(session, f)

    return router


def masked_payload_record(parts: list[dict]) -> dict:
    import hashlib

    text = json.dumps(parts, ensure_ascii=False)
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text[:20000]}
