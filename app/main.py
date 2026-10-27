import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Assignment, DataQualityIssue, Evidence, QualityCase, SourceAsset, SourceEvent
from app.ingestion import SyntheticBundle, normalize
from app.ml_api import make_ml_router
from app.model_provider import MODEL, MetaProvider, ModelProvider
from app.synthetic import canonical, generate, spi_correction
from app.workflow import Actor, make_auth, make_router, require_case, require_role


class Health(BaseModel):
    status: str
    stage: str


class CaseCreate(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    domain: Literal["PCB"] = "PCB"
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"


def create_app(database_url: str = "sqlite:///qualityops.db",
               provider: ModelProvider | None = None) -> FastAPI:
    app = FastAPI(title="QualityOps AI", version="0.6.0")
    engine = create_engine(database_url)
    sessions = sessionmaker(engine)
    app.state.engine = engine

    current_user = make_auth(sessions)
    Who = Annotated[Actor, Depends(current_user)]
    app.state.provider = provider or MetaProvider.from_env()  # None -> investigations return 503
    app.include_router(make_router(sessions, current_user, app.state.provider))
    app.include_router(make_ml_router(sessions, current_user))

    @app.get("/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok", stage="S6")

    @app.post("/cases", status_code=201)
    def create_case(payload: CaseCreate, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        with sessions.begin() as session:
            if session.get(QualityCase, payload.case_id):
                raise HTTPException(409, "Case already exists")
            session.add(QualityCase(id=payload.case_id, domain=payload.domain, data_origin=payload.data_origin))
            session.flush()
            session.add(Assignment(case_id=payload.case_id, user_id=actor.id))
        return payload.model_dump()

    @app.get("/cases/{case_id}")
    def get_case(case_id: str, actor: Who) -> dict:
        with sessions() as session:
            case = require_case(session, case_id, actor)
            return {"case_id": case.id, "domain": case.domain, "data_origin": case.data_origin}

    @app.post("/cases/{case_id}/sources", status_code=201)
    def upload_sources(case_id: str, bundle: SyntheticBundle, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        # shortcut: S1 accepts only this reproducible generator; real adapters need their own provenance gate.
        expected = SyntheticBundle.model_validate(generate(bundle.seed))
        if bundle.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise HTTPException(422, "Bundle is not an exact generated synthetic fixture")
        try:
            events, issues = normalize(bundle)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            if session.scalar(select(SourceAsset.id).where(SourceAsset.case_id == case_id).limit(1)):
                raise HTTPException(409, "Sources already uploaded for this case")
            asset_ids = {}
            for source in bundle.assets:
                stored = SourceAsset(
                    case_id=case_id, asset_id=source.asset_id, source_system=source.source_system,
                    entity_type=source.entity_type, source_version=source.source_version,
                    supersedes_asset_id=source.supersedes_asset_id, license_id=source.license_id,
                    data_origin=source.data_origin, sensitivity=source.sensitivity,
                    captured_at=source.captured_at.isoformat(), ingested_at=source.ingested_at.isoformat(),
                    content_sha256=source.content_sha256, raw_json=canonical(source.records),
                )
                session.add(stored)
                session.flush()
                asset_ids[source.asset_id] = stored.id
            for event in events:
                stored = SourceEvent(
                    case_id=case_id, source_asset_id=asset_ids[event["asset_id"]],
                    event_id=event["id"], original_row_id=event["original_row_id"],
                    entity_type=event["entity_type"], entity_key=event["entity_key"],
                    event_time=event["event_time"], source_updated_at=event["source_updated_at"],
                    ingested_at=event["ingested_at"], data_origin=event["data_origin"],
                    sensitivity=event["sensitivity"], validation_status=event["validation_status"],
                    raw_json=event["raw_json"],
                )
                session.add(stored)
                session.flush()
                session.add(Evidence(
                    case_id=case_id, source_event_id=stored.id, evidence_id=f"EV-{event['id']}",
                    classification="OBSERVED", validity=event["validation_status"],
                    content_sha256=hashlib.sha256(event["raw_json"].encode()).hexdigest(),
                ))
            for item in issues:
                session.add(DataQualityIssue(case_id=case_id, **item))
        return {"asset_count": len(bundle.assets), "event_count": len(events),
                "issue_counts": Counter(i["code"] for i in issues)}

    @app.get("/cases/{case_id}/sources")
    def get_sources(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            assets = session.scalars(select(SourceAsset).where(SourceAsset.case_id == case_id).order_by(SourceAsset.id)).all()
            return [{
                "asset_id": a.asset_id, "source_system": a.source_system,
                "source_version": a.source_version, "supersedes_asset_id": a.supersedes_asset_id,
                "content_sha256": a.content_sha256, "license_id": a.license_id,
                "data_origin": a.data_origin, "sensitivity": a.sensitivity,
            } for a in assets]

    @app.get("/cases/{case_id}/events")
    def get_events(case_id: str, actor: Who, entity_type: str | None = None,
                   panel_id: str | None = None, board_id: str | None = None) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            rows = session.execute(
                select(SourceEvent, SourceAsset)
                .join(SourceAsset, SourceEvent.source_asset_id == SourceAsset.id)
                .where(SourceEvent.case_id == case_id).order_by(SourceEvent.id)
            ).all()
            return [{
                "event_id": e.event_id, "entity_type": e.entity_type, "entity_key": e.entity_key,
                "original_row_id": e.original_row_id, "event_time": e.event_time,
                "source_updated_at": e.source_updated_at, "ingested_at": e.ingested_at,
                "data_origin": e.data_origin, "validation_status": e.validation_status,
                "source_asset_id": a.asset_id, "source_version": a.source_version,
                "source_sha256": a.content_sha256, "record": json.loads(e.raw_json),
            } for e, a in rows
                if (entity_type is None or e.entity_type == entity_type)
                and (panel_id is None or e.entity_key[0] == panel_id)
                and (board_id is None or len(e.entity_key) > 1 and e.entity_key[1] == board_id)]

    @app.get("/cases/{case_id}/evidence")
    def get_evidence(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            rows = session.execute(
                select(Evidence, SourceEvent).join(SourceEvent, Evidence.source_event_id == SourceEvent.id)
                .where(Evidence.case_id == case_id).order_by(Evidence.id)
            ).all()
            return [{"evidence_id": v.evidence_id, "event_id": e.event_id,
                     "classification": v.classification, "validity": v.validity,
                     "content_sha256": v.content_sha256} for v, e in rows]

    @app.get("/cases/{case_id}/data-issues")
    def get_issues(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            rows = session.scalars(
                select(DataQualityIssue).where(DataQualityIssue.case_id == case_id).order_by(DataQualityIssue.id)
            ).all()
            return [{"event_id": i.event_id, "code": i.code,
                     "severity": i.severity, "detail": i.detail} for i in rows]

    @app.get("/synthetic/{seed}")
    def synthetic(seed: int) -> dict:
        return generate(seed)

    @app.get("/synthetic/{seed}/spi-correction")
    def synthetic_correction(seed: int, row_id: str = "SPI-P02-B01-1", version: int = 3) -> dict:
        try:
            return spi_correction(seed, row_id, version=version)
        except StopIteration:
            raise HTTPException(404, "No such SPI row in the fixture") from None

    @app.get("/provider")
    def provider_status() -> dict:
        """What an investigation would call. No key or secret is ever returned."""
        p = app.state.provider
        return {"model": p.model if p else MODEL, "mode": p.mode if p else None, "configured": p is not None}

    @app.get("/ui", include_in_schema=False)
    def ui() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    web = Path(__file__).parent / "static" / "web"  # built React UI (web/), if present
    if web.is_dir():
        app.mount("/app", StaticFiles(directory=web, html=True), name="web")
    return app


app = create_app()
