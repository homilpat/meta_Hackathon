"""Specialist vision tool boundary (spec v5.8 §24.3). The contract a defect detection / segmentation /
classification / measurement model will be called through. No model is connected (MVP): a request is checked and
recorded, and answered NOT_CONFIGURED. Muse never stands in for it, and nothing here makes a defect judgement.

Four kinds of statement about an image stay apart everywhere: what the customer reported (CUSTOMER_REPORTED), what
Muse read from its context (AI_OBSERVATION), what a vision model returned (VISION_RESULT, none yet), and what a
person inspected (HUMAN_INSPECTION, the existing human verifications).
"""

import hashlib
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import docparse
from app.db import IntakeCaseLink, IntakeFile, IntakeParse, VisionRequest
from app.intake import require_intake
from app.workflow import Actor, now, require_case, run_idempotent

AnalysisType = Literal["DEFECT_DETECTION", "SEGMENTATION", "CLASSIFICATION", "MEASUREMENT"]
SOURCE_TYPES = {"CUSTOMER_REPORTED": "고객 보고", "AI_OBSERVATION": "AI 문맥 해석 (Muse, 결함 판정 아님)",
                "VISION_RESULT": "전문 비전 모델 결과", "HUMAN_INSPECTION": "사람 검사 판정"}
NOT_CONFIGURED = ("전문 비전 모델이 연결되지 않았습니다 (NOT_CONFIGURED). 검출·분할·분류·측정 결과는 없으며, "
                  "고객 보고와 사람의 검사로 판단하세요.")


class Region(BaseModel):
    bbox: list[float] = Field(min_length=4, max_length=4)  # x, y, width, height in the declared coordinate system
    label: str
    score: float = Field(ge=0, le=1)  # a model score, not a probability guarantee or a cause
    measurement: dict | None = None  # {"value", "unit", "calibration_ref"}


class VisionResult(BaseModel):
    """What a connected adapter must return (P2). Checked before anything is stored."""
    analysis_id: str
    input_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    model: str
    model_version: str
    settings: dict
    coordinate_system: Literal["IMAGE_PIXELS_TOP_LEFT"]
    preprocessing: list[str]
    regions: list[Region]
    status: Literal["OK", "PARTIAL", "FAILED"]
    limitations: list[str]


# analysis type -> adapter(image bytes, request) -> VisionResult. Empty: every request is NOT_CONFIGURED.
ADAPTERS: dict[str, Callable[[bytes, dict], VisionResult]] = {}


class VisionIn(BaseModel):
    intake_id: int | None = None
    case_id: str | None = None
    file_id: int
    element_id: str = Field(max_length=60)
    analysis_type: AnalysisType
    reported_phenomenon: str | None = Field(None, max_length=300)  # what the customer reported, kept as theirs

    @model_validator(mode="after")
    def one_scope(self):
        if (self.intake_id is None) == (self.case_id is None):
            raise ValueError("give exactly one of intake_id or case_id")
        return self


def request_out(v: VisionRequest) -> dict:
    return {"request_id": v.id, "intake_id": v.intake_id, "case_id": v.case_id, "file_id": v.file_id,
            "file_sha256": v.file_sha256, "element_id": v.element_id, "image_sha256": v.image_sha256,
            "page": v.page, "analysis_type": v.analysis_type, "reported_phenomenon": v.reported_phenomenon,
            "reported_as": "CUSTOMER_REPORTED" if v.reported_phenomenon else None, "requested_by": v.requested_by,
            "status": v.status, "result": v.result, "result_type": "VISION_RESULT" if v.result else None,
            "message": NOT_CONFIGURED if v.status == "NOT_CONFIGURED" else None, "created_at": v.created_at}


def usable(result: dict | None, image_sha256: str) -> bool:
    """A stored result describes only the exact image it was computed on: a replaced image never reuses it."""
    return bool(result) and result.get("input_sha256") == image_sha256


def target(session: Session, body: VisionIn, actor: Actor) -> tuple[IntakeFile, dict, bytes]:
    """The file and image element the request is about, after access checks; the image hash is recomputed now."""
    if body.intake_id is not None:
        require_intake(session, body.intake_id, actor)
        intake_id = body.intake_id
    else:
        require_case(session, body.case_id, actor)
        f = session.get(IntakeFile, body.file_id)
        link = f and session.scalar(select(IntakeCaseLink).where(IntakeCaseLink.intake_id == f.intake_id,
                                                                 IntakeCaseLink.case_id == body.case_id))
        if not link:
            raise HTTPException(404, "File not linked to this case")
        intake_id = f.intake_id
    f = session.get(IntakeFile, body.file_id)
    if f is None or f.intake_id != intake_id:
        raise HTTPException(404, "File not found")
    pp = session.scalar(select(IntakeParse).where(IntakeParse.file_id == f.id,
                                                  IntakeParse.parser_version == docparse.PARSER_VERSION))
    el = next((e for e in (pp.elements if pp else []) if e["id"] == body.element_id), None)
    if el is None or el["kind"] != "image":
        raise HTTPException(422, "element is not an image of this file (analyze the files first)")
    blob = docparse.parse(f.media_type, f.content)[2].get(el["id"])
    if blob is None or hashlib.sha256(blob).hexdigest() != el["sha256"]:
        raise HTTPException(409, "the image no longer matches the parsed element; analyze again")
    return f, el, blob


def make_vision_router(sessions: sessionmaker, current_user) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    @router.get("/vision/status")
    def status(actor: Who) -> dict:
        return {"configured": sorted(ADAPTERS), "status": "CONFIGURED" if ADAPTERS else "NOT_CONFIGURED",
                "analysis_types": list(AnalysisType.__args__), "source_types": SOURCE_TYPES,
                "message": None if ADAPTERS else NOT_CONFIGURED}

    @router.post("/vision/requests", status_code=201)
    def request(body: VisionIn, key: IdemKey, actor: Who):
        def run(session: Session) -> tuple[int, dict]:
            f, el, blob = target(session, body, actor)
            adapter, result, state = ADAPTERS.get(body.analysis_type), None, "NOT_CONFIGURED"
            if adapter is not None:  # P2: egress follows the file's origin, exactly as for the language model
                if f.data_origin != "SYNTHETIC":
                    raise HTTPException(403, "file not approved for external processing")
                out = VisionResult.model_validate(adapter(blob, body.model_dump()))
                if out.input_sha256 != el["sha256"]:
                    raise HTTPException(502, "vision result is for a different image; not stored")
                result, state = out.model_dump(), out.status
            v = VisionRequest(intake_id=f.intake_id, case_id=body.case_id, file_id=f.id, file_sha256=f.sha256,
                              element_id=el["id"], image_sha256=el["sha256"], page=el.get("page"),
                              analysis_type=body.analysis_type, reported_phenomenon=body.reported_phenomenon,
                              requested_by=actor.id, status=state, result=result, created_at=now())
            session.add(v)
            session.flush()
            return 201, request_out(v)
        return run_idempotent(sessions, "vision_request", key, actor, run)

    @router.get("/vision/requests")
    def requests(actor: Who, intake_id: int | None = None, case_id: str | None = None) -> list[dict]:
        with sessions() as session:
            if intake_id is not None:
                require_intake(session, intake_id, actor)
                q = select(VisionRequest).where(VisionRequest.intake_id == intake_id)
            elif case_id is not None:
                require_case(session, case_id, actor)
                q = select(VisionRequest).where(VisionRequest.case_id == case_id)
            else:
                raise HTTPException(422, "give intake_id or case_id")
            return [request_out(v) for v in session.scalars(q.order_by(VisionRequest.id))]

    return router
