"""S4 endpoints: train/register the SPI model, score a case's boards, read predictions + SHAP."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import impact, ml, ncr
from app.db import Evidence, ModelVersion, Prediction, XaiArtifact
from app.workflow import Actor, log, now, require_case, require_role, run_idempotent

NOTE = ("Model output on SYNTHETIC_LABEL data; not an inspection result. SHAP attributes the model "
        "score to SPI features and is not evidence of a physical defect cause.")


class TrainIn(BaseModel):
    seed: int = 11


class PredictIn(BaseModel):
    model_version_id: int | None = None


def model_out(mv: ModelVersion) -> dict:
    return {"model_version_id": mv.id, "name": mv.name, "algorithm": mv.algorithm, "label_kind": mv.label_kind,
            "seed": mv.seed, "features": mv.features, "split": mv.split, "metrics": mv.metrics,
            "threshold": mv.threshold, "train_data_sha256": mv.train_data_sha256,
            "feature_schema_sha256": mv.feature_schema_sha256, "artifact_sha256": mv.artifact_sha256,
            "library_versions": mv.library_versions, "trained_at": mv.trained_at}


def prediction_out(session: Session, p: Prediction) -> dict:
    mv = session.get(ModelVersion, p.model_version_id)
    x = session.scalar(select(XaiArtifact).where(XaiArtifact.prediction_id == p.id))
    return {
        "prediction_id": p.id, "evidence_id": f"PRED-{p.id}", "xai_evidence_id": f"XAI-{x.id}",
        "case_id": p.case_id, "target_key": p.target_key, "risk_score": p.risk_score, "threshold": p.threshold,
        "above_threshold": p.above_threshold, "features": p.features, "input_evidence_ids": p.input_evidence_ids,
        "input_sha256": p.input_sha256, "created_at": p.created_at,
        "model": {k: model_out(mv)[k] for k in ("model_version_id", "name", "algorithm", "label_kind",
                                                "artifact_sha256", "feature_schema_sha256")},
        "xai": {"method": x.method, "baseline": x.baseline, "raw_score": x.raw_score,
                "additivity_error": x.additivity_error, "library_version": x.library_version,
                "contributions": dict(sorted(x.contributions.items(), key=lambda kv: -abs(kv[1])))},
        "note": NOTE,
    }


def make_ml_router(sessions: sessionmaker, current_user: Callable[..., Actor]) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]
    IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)]

    @router.post("/models/train")
    def train_model(body: TrainIn, actor: Who) -> dict:
        require_role(actor, "AUTHOR")
        trained = ml.train(body.seed)  # deterministic: same inputs give the same artifact hash
        with sessions.begin() as session:
            mv = session.scalar(select(ModelVersion).where(
                ModelVersion.artifact_sha256 == trained["artifact_sha256"],
                ModelVersion.train_data_sha256 == trained["train_data_sha256"]))
            if mv is None:
                mv = ModelVersion(**trained, trained_at=now())
                session.add(mv)
                session.flush()
            return model_out(mv)

    @router.get("/models")
    def list_models(actor: Who) -> list[dict]:
        with sessions() as session:
            return [model_out(m) for m in session.scalars(select(ModelVersion).order_by(ModelVersion.id))]

    @router.get("/models/{model_id}/card", response_class=PlainTextResponse)
    def card(model_id: int, actor: Who) -> str:
        with sessions() as session:
            mv = session.get(ModelVersion, model_id)
            if mv is None:
                raise HTTPException(404, "Model not found")
            return ml.model_card(model_out(mv))

    @router.post("/cases/{case_id}/predictions")
    def predict(case_id: str, body: PredictIn, key: IdemKey, actor: Who):
        require_role(actor, "AUTHOR")

        def run(session: Session) -> tuple[int, dict]:
            require_case(session, case_id, actor)
            q = select(ModelVersion).order_by(ModelVersion.id.desc()).limit(1)
            if body.model_version_id is not None:
                q = select(ModelVersion).where(ModelVersion.id == body.model_version_id)
            mv = session.scalar(q)
            if mv is None:
                raise HTTPException(409, "No trained model; POST /models/train first")
            ml.assert_no_leakage(mv.features)
            boards = ncr.latest_spi_by_board(ncr._evidence(session, case_id))
            if not boards:
                raise HTTPException(422, "Case has no SPI evidence to score")
            out = []
            for (panel, board), spi in sorted(boards.items()):
                feats = ml.board_features([("spi_measurements", i["rec"]) for i in spi])
                scored = ml.predict_explain(mv.artifact_text, feats)
                ev_ids = [i["ev"] for i in spi]
                p = Prediction(case_id=case_id, model_version_id=mv.id, target_key=[panel, board],
                               risk_score=scored["risk_score"], threshold=mv.threshold,
                               above_threshold=scored["risk_score"] >= mv.threshold, features=feats,
                               input_evidence_ids=ev_ids, created_at=now(),
                               input_sha256=ml.sha256_json({"features": feats, "evidence_ids": ev_ids}))
                session.add(p)
                session.flush()
                x = XaiArtifact(prediction_id=p.id, method=ml.XAI_METHOD, baseline=scored["baseline"],
                                contributions=scored["contributions"], raw_score=scored["raw_score"],
                                additivity_error=scored["additivity_error"],
                                library_version=f"lightgbm {mv.library_versions['lightgbm']}", created_at=now())
                session.add(x)
                session.flush()
                rec = prediction_out(session, p)
                session.add_all([
                    Evidence(case_id=case_id, source_event_id=None, evidence_id=f"PRED-{p.id}",
                             classification="MODEL_PREDICTION", validity="MODEL_OUTPUT",
                             content_sha256=ml.sha256_json({k: rec[k] for k in ("risk_score", "features",
                                                                                 "input_sha256", "model")})),
                    Evidence(case_id=case_id, source_event_id=None, evidence_id=f"XAI-{x.id}",
                             classification="XAI_EXPLANATION", validity="MODEL_OUTPUT",
                             content_sha256=ml.sha256_json(rec["xai"]))])
                impact.link(session, case_id, {(ev, f"PRED-{p.id}") for ev in ev_ids} | {(f"PRED-{p.id}", f"XAI-{x.id}")})
                out.append(rec)
            log(session, case_id, actor, "PREDICTIONS_CREATED",
                f"model v{mv.id} ({mv.artifact_sha256[:12]}) scored {len(out)} boards")
            session.flush()
            return 201, {"model_version_id": mv.id, "predictions": out}

        return run_idempotent(sessions, f"predict:{case_id}", key, actor, run)

    @router.get("/cases/{case_id}/predictions")
    def list_predictions(case_id: str, actor: Who) -> list[dict]:
        with sessions() as session:
            require_case(session, case_id, actor)
            rows = session.scalars(select(Prediction).where(Prediction.case_id == case_id).order_by(Prediction.id))
            return [prediction_out(session, p) for p in rows]

    @router.get("/cases/{case_id}/predictions/{prediction_id}")
    def get_prediction(case_id: str, prediction_id: int, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)
            p = session.get(Prediction, prediction_id)
            if p is None or p.case_id != case_id:
                raise HTTPException(404, "Prediction not found")
            return prediction_out(session, p)

    return router
