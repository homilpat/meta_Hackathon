import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app import effect, ncr, spc
from app.causes import make_d4_router
from app.closure import make_d7_d8_router
from app.db import (
    Action,
    Assignment,
    DataQualityIssue,
    Evidence,
    ModelRun,
    QualityCase,
    SourceAsset,
    SourceEvent,
    User,
)
from app.effect import make_d6_router
from app.eightd import make_v5_router
from app.ingestion import SyntheticBundle, normalize
from app.ml_api import make_ml_router
from app.model_provider import MODEL, MetaProvider, ModelProvider
from app.synthetic import (
    LINE_VERSION,
    canonical,
    generate,
    generate_line,
    generate_post_window,
    spi_correction,
)
from app.workflow import DEMO_USERS, Actor, log, make_auth, make_router, require_case, require_role


class Health(BaseModel):
    status: str
    stage: str


class Replay(BaseModel):
    seed: int = 7


def store_bundle(session, case_id: str, bundle: SyntheticBundle, events: list[dict], issues: list[dict]) -> None:
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
    for row in events:
        stored = SourceEvent(
            case_id=case_id, source_asset_id=asset_ids[row["asset_id"]],
            event_id=row["id"], original_row_id=row["original_row_id"],
            entity_type=row["entity_type"], entity_key=row["entity_key"],
            event_time=row["event_time"], source_updated_at=row["source_updated_at"],
            ingested_at=row["ingested_at"], data_origin=row["data_origin"],
            sensitivity=row["sensitivity"], validation_status=row["validation_status"],
            raw_json=row["raw_json"],
        )
        session.add(stored)
        session.flush()
        session.add(Evidence(
            case_id=case_id, source_event_id=stored.id, evidence_id=f"EV-{row['id']}",
            classification="OBSERVED", validity=row["validation_status"],
            content_sha256=hashlib.sha256(row["raw_json"].encode()).hexdigest(),
        ))
    for item in issues:
        session.add(DataQualityIssue(case_id=case_id, **item))


class CaseCreate(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    domain: Literal["PCB"] = "PCB"
    data_origin: Literal["SYNTHETIC"] = "SYNTHETIC"


def serialize_sqlite(engine) -> None:
    """Take the write lock at BEGIN, so every check-then-write (review still PENDING? key unused? NCR still
    APPROVED?) runs on the state it changes. pysqlite otherwise reads outside the transaction and two
    concurrent decisions could both pass their checks (found by scripts/concurrency_sim.py)."""
    # ponytail: one writer at a time is SQLite's ceiling; on Postgres use row locks (SELECT ... FOR UPDATE).
    @event.listens_for(engine, "connect")
    def _no_implicit_begin(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def create_app(database_url: str = "sqlite:///qualityops.db",
               provider: ModelProvider | None = None) -> FastAPI:
    app = FastAPI(title="QualityOps AI", version="0.6.0")
    engine = create_engine(database_url, connect_args={"timeout": 30} if database_url.startswith("sqlite") else {})
    if engine.dialect.name == "sqlite":
        serialize_sqlite(engine)
    sessions = sessionmaker(engine)
    app.state.engine = engine

    current_user = make_auth(sessions)
    Who = Annotated[Actor, Depends(current_user)]
    app.state.provider = provider or MetaProvider.from_env()  # None -> investigations return 503
    app.include_router(make_router(sessions, current_user, app.state.provider))
    app.include_router(make_ml_router(sessions, current_user))
    app.include_router(make_v5_router(sessions, current_user))
    app.include_router(make_d4_router(sessions, current_user))
    app.include_router(make_d6_router(sessions, current_user))
    app.include_router(make_d7_d8_router(sessions, current_user))

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
        make = generate_line if bundle.generator_version == LINE_VERSION else generate
        expected = SyntheticBundle.model_validate(make(bundle.seed))
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
            store_bundle(session, case_id, bundle, events, issues)
        return {"asset_count": len(bundle.assets), "event_count": len(events),
                "issue_counts": Counter(i["code"] for i in issues)}

    class PostWindowIn(BaseModel):
        action_id: int
        effective: bool = True  # fixture choice: fresh stencil, or the same drift continues

    @app.post("/cases/{case_id}/synthetic/post-window", status_code=201)
    def post_window(case_id: str, body: PostWindowIn, actor: Who) -> dict:
        """D6 monitoring data: one generated lot (L04) produced after the D5 action's EXECUTED event. SYNTHETIC."""
        require_role(actor, "AUTHOR")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            a = session.get(Action, body.action_id)
            if a is None or a.case_id != case_id or a.stage != "D5":
                raise HTTPException(404, "D5 action not found")
            at = effect.executed_at(session, a.id)
            if at is None:
                raise HTTPException(409, "post-window data follows an EXECUTED corrective action")
            if session.scalar(select(SourceAsset.id).where(SourceAsset.case_id == case_id,
                                                           SourceAsset.asset_id.like("%:post:v1")).limit(1)):
                raise HTTPException(409, "post-window data already recorded for this case")
            seed = session.scalar(select(func.count(SourceAsset.id)).where(SourceAsset.case_id == case_id))
            bundle = SyntheticBundle.model_validate(
                generate_post_window(seed, datetime.fromisoformat(at), body.effective))
            events, issues = normalize(bundle)
            store_bundle(session, case_id, bundle, events, issues)
            log(session, case_id, actor, "POST_WINDOW_DATA", f"action #{a.id} after {at} effective_fixture="
                f"{body.effective} rows={len(events)} (SYNTHETIC)")
        return {"event_count": len(events), "after": at, "generator_version": bundle.generator_version,
                "issue_counts": Counter(i["code"] for i in issues)}

    @app.get("/cases/{case_id}/spc")
    def get_spc(case_id: str, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)
            m = spc.from_items(ncr.current(ncr._evidence(session, case_id)))
        if m is None:
            raise HTTPException(404, "No lot-traced SPI data in this case")
        return m

    @app.post("/monitoring/line-replay", status_code=201)
    def line_replay(body: Replay, actor: Who) -> dict:
        """Replay the synthetic line stream through the SPC monitor; the first phase II alarm opens a case."""
        # ponytail: replays a whole generated run; a live line would push events (e.g. IPC-CFX) into the same monitor.
        require_role(actor, "AUTHOR")
        raw = generate_line(body.seed)
        m = spc.from_bundle(raw)
        alarm = m and m["first_alarm"]
        if not alarm:
            return {"case_id": None, "alarm": None, "limits": m and m["limits"]}
        t = {a["entity_type"]: a["records"] for a in raw["assets"]}
        lot_of = {r["panel_id"]: r["lot_id"] for r in t["panels"]}
        confirmed = sorted(r["event_time"] for r in t["human_verifications"]
                           if r["result"] == "DEFECT_CONFIRMED" and lot_of[r["panel_id"]] == alarm["lot"])
        case_id = f"SPC-{body.seed}-{alarm['panel']}-{alarm['board']}"
        bundle = SyntheticBundle.model_validate(raw)
        events, issues = normalize(bundle)
        lim = m["limits"]
        detail = (f"{'+'.join(alarm['rules'])} at {alarm['panel']}/{alarm['board']} (lot {alarm['lot']}): X-bar "
                  f"{alarm['xbar']} vs limits {lim['lcl']}..{lim['ucl']} mm3 from lot {m['reference_lot']}")
        with sessions.begin() as session:
            if session.get(QualityCase, case_id):
                raise HTTPException(409, f"Case {case_id} already opened for this alarm")
            session.add(QualityCase(id=case_id, domain="PCB", data_origin="SYNTHETIC"))
            session.flush()
            # demo team: the caller plus the first user of each approver role
            team = [actor.id, *(next(u for u, (_, r) in DEMO_USERS.items() if r == role)
                                for role in ("REVIEWER", "QA_PRODUCTION", "PROCESS_ENGINEER"))]
            for u in team:
                if session.get(User, u) is None:
                    session.add(User(id=u, name=DEMO_USERS[u][0], role=DEMO_USERS[u][1]))
                    session.flush()
                session.add(Assignment(case_id=case_id, user_id=u))
            store_bundle(session, case_id, bundle, events, issues)
            log(session, case_id, actor, "SPC_ALARM", detail)
        return {"case_id": case_id, "alarm": alarm, "limits": lim, "reference_lot": m["reference_lot"],
                "first_confirmed_defect_in_lot": confirmed[0] if confirmed else None, "detail": detail}

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

    @app.get("/synthetic/line/{seed}")
    def synthetic_line(seed: int) -> dict:
        return generate_line(seed)

    @app.get("/synthetic/{seed}")
    def synthetic(seed: int) -> dict:
        return generate(seed)

    @app.get("/synthetic/{seed}/spi-correction")
    def synthetic_correction(seed: int, row_id: str = "SPI-P02-B01-1", version: int = 3, line: bool = False) -> dict:
        try:
            return spi_correction(seed, row_id, version=version, line=line)
        except StopIteration:
            raise HTTPException(404, "No such SPI row in the fixture") from None

    @app.get("/provider")
    def provider_status() -> dict:
        """What an investigation would call. No key or secret is ever returned."""
        p = app.state.provider
        # A key alone proves nothing: VERIFIED only after a LIVE run actually passed validation here.
        if p is None:
            status = "NOT_CONFIGURED"
        elif p.mode != "LIVE":
            status = "TEST_DOUBLE"
        else:
            with sessions() as session:
                ok = session.scalar(select(ModelRun.id).where(
                    ModelRun.mode == "LIVE", ModelRun.status == "VALIDATED").limit(1))
            status = "VERIFIED" if ok else "CONFIGURED_NOT_VERIFIED"
        return {"model": p.model if p else MODEL, "mode": p.mode if p else None, "configured": p is not None,
                "live_status": status}

    @app.get("/reference-models/steel")
    def steel_reference() -> dict:
        """Aggregate results of the REAL-data reference model (scripts/steel_model.py); no source rows."""
        path = Path("docs/steel_eval.json")
        if not path.is_file():
            raise HTTPException(404, "Run python -m scripts.steel_model first")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/ui", include_in_schema=False)
    def ui() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    web = Path(__file__).parent / "static" / "web"  # built React UI (web/), if present
    if web.is_dir():
        app.mount("/app", StaticFiles(directory=web, html=True), name="web")
    return app


app = create_app()
