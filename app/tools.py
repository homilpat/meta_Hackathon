"""Read-only evidence tools exposed to the model. Scoped to one case chosen by the server."""

import json
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import (
    DataQualityIssue,
    Evidence,
    Prediction,
    QualityCase,
    SourceAsset,
    SourceEvent,
    XaiArtifact,
)

APPROVED = ("SYNTHETIC", "APPROVED_FOR_EXTERNAL")


class ToolError(Exception):
    """Bad arguments or unknown tool. Safe to show to the model."""


class ToolDenied(ToolError):
    """Data not approved for external processing. Fail closed: no rows are returned."""


def _fn(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or [],
                       "additionalProperties": False}}}


SPECS = [
    _fn("get_case_summary", "Start here. Server-computed facts for every AOI FAIL (human verdict, repair, mean SPI "
        "volume with a ready calc), boards without AOI, data-issue counts and model scores, each with "
        "evidence_ids. Latest source version per row. Use other tools only for details.", {}),
    _fn("get_case_context", "Case id, source assets with versions and hashes, and event counts per type.", {}),
    _fn("get_manufacturing_events",
        "List events with their evidence_id and record. Filter by entity_type, panel_id, board_id.",
        {"entity_type": {"type": "string"}, "panel_id": {"type": "string"}, "board_id": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
    _fn("get_evidence", "Fetch evidence rows by evidence_id (max 20).",
        {"evidence_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 20}}, ["evidence_ids"]),
    _fn("check_data_integrity", "List recorded data-quality issues (duplicates, missing AOI, corrections).", {}),
    _fn("get_prediction", "SPI-only risk model scores for this case's boards (citable as PRED-n). "
        "Model output on a SYNTHETIC_LABEL, not an inspection result.",
        {"panel_id": {"type": "string"}, "board_id": {"type": "string"}}),
    _fn("explain_prediction", "TreeSHAP attribution of one prediction's score (citable as XAI-n). "
        "Explains the model, not the physical cause.", {"prediction_id": {"type": "integer"}}, ["prediction_id"]),
]
HISTORY_SPECS = [
    _fn("retrieve_historical_cases", "Eligible past incidents (same site, approved, available before this case, "
        "external-approved) ranked by pattern similarity. Similarity is not causal evidence.", {}),
    _fn("get_historical_case_outcome", "Checks, actions and verified outcome statuses for one eligible precedent.",
        {"historical_case_id": {"type": "string"}}, ["historical_case_id"]),
]
ARGS = {s["function"]["name"]: set(s["function"]["parameters"]["properties"]) for s in SPECS + HISTORY_SPECS}


class EvidenceTools:
    def __init__(self, session: Session, case_id: str, use_history: bool = False):
        self.session, self.case_id, self.use_history = session, case_id, use_history

    def specs(self) -> list[dict]:
        return SPECS + HISTORY_SPECS if self.use_history else SPECS

    def call(self, name: str, args: dict) -> dict:
        if name not in ARGS or (not self.use_history and name in {s["function"]["name"] for s in HISTORY_SPECS}):
            raise ToolError(f"unknown tool {name!r}")
        if not isinstance(args, dict) or set(args) - ARGS[name]:
            raise ToolError(f"invalid arguments for {name}")
        return getattr(self, name)(**args)

    def _rows(self, *conditions) -> list[dict]:
        rows = self.session.execute(
            select(Evidence, SourceEvent, SourceAsset)
            .join(SourceEvent, Evidence.source_event_id == SourceEvent.id)
            .join(SourceAsset, SourceEvent.source_asset_id == SourceAsset.id)
            .where(Evidence.case_id == self.case_id, *conditions).order_by(Evidence.id)).all()
        if any((e.data_origin, e.sensitivity) != APPROVED for _, e, _ in rows):
            raise ToolDenied("denied: source not approved for external processing")
        return [{"evidence_id": v.evidence_id, "entity_type": e.entity_type, "entity_key": e.entity_key,
                 "source_version": a.source_version, "validity": v.validity,
                 "record": json.loads(e.raw_json)} for v, e, a in rows]

    def get_case_summary(self) -> dict:
        """One compact call instead of paging raw events: fewer rounds and tokens, numbers the server can recheck."""
        from app import ncr
        self._rows()  # same egress gate as raw evidence
        items = ncr.current(ncr._evidence(self.session, self.case_id))
        aoi, spi = ncr._aoi(items), ncr.latest_spi_by_board(items)
        preds = {tuple(p.target_key): p for p in self._predictions()}
        fails = []
        for key in sorted(k for k, i in aoi.items() if i["rec"]["result"] == "FAIL"):
            human, repair = (ncr._linked(items, t, key) for t in ("human_verifications", "repair_dispositions"))
            rows = spi.get(key[:2], [])
            p = preds.get(key[:2])
            fails.append({
                "board": "/".join(key[:2]), "aoi": [key[2], aoi[key]["ev"]],
                "human": [human["rec"]["result"], human["ev"]] if human else None,
                "repair": [repair["rec"]["disposition"], repair["ev"]] if repair else None,
                "spi": {"mean_mm3": round(sum(i["rec"]["volume_mm3"] for i in rows) / len(rows), 4),
                        "evidence_ids": [i["ev"] for i in rows],
                        "calc": {"op": "mean", "field": "volume_mm3"}} if rows else None,
                "model": [f"PRED-{p.id}", round(p.risk_score, 4), round(p.threshold, 4)] if p else None})
        issues = Counter(i.code for i in self.session.scalars(
            select(DataQualityIssue).where(DataQualityIssue.case_id == self.case_id)))
        lots = [{"lot": lot, "stencil": v["lot"]["rec"]["stencil_id"], "lot_ev": v["lot"]["ev"], "aoi": len(v["aoi"]),
                 "fail": len(v["fails"]), "not_cleared": len(v["open"]),
                 "unshipped_panels": sum(x["rec"]["status"] != "SHIPPED" for x in v["ship"]),
                 "shipped_panels": sum(x["rec"]["status"] == "SHIPPED" for x in v["ship"])}
                for lot, v in sorted(ncr.lot_view(items, aoi).items())]
        return {"aoi_evidence_ids": [i["ev"] for i in aoi.values()], "lots": lots, "aoi_fail": fails,
                "no_aoi_record": [["/".join(b["key"]), b["ev"]] for b in ncr._uninspected(items, aoi)],
                "data_issues": dict(issues),
                "legend": "[value, evidence_id]; model = [PRED id, score, threshold] (model output, not inspection)"}

    def get_case_context(self) -> dict:
        case = self.session.get(QualityCase, self.case_id)
        assets = self.session.scalars(select(SourceAsset).where(SourceAsset.case_id == self.case_id)).all()
        counts = Counter(r[0] for r in self.session.execute(
            select(SourceEvent.entity_type).where(SourceEvent.case_id == self.case_id)))
        return {"case_id": case.id, "domain": case.domain, "data_origin": case.data_origin,
                "event_counts": dict(counts),
                "assets": [{"asset_id": a.asset_id, "source_version": a.source_version,
                            "content_sha256": a.content_sha256} for a in assets],
                "note": "Cite only evidence_id values returned by tools."}

    def get_manufacturing_events(self, entity_type: str | None = None, panel_id: str | None = None,
                                 board_id: str | None = None, limit: int = 25) -> dict:
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ToolError("limit must be 1..50")
        rows = [r for r in self._rows()
                if (entity_type is None or r["entity_type"] == entity_type)
                and (panel_id is None or r["entity_key"][0] == panel_id)
                and (board_id is None or (len(r["entity_key"]) > 1 and r["entity_key"][1] == board_id))]
        return {"total_matching": len(rows), "events": rows[:limit]}

    def get_evidence(self, evidence_ids: list[str]) -> dict:
        if not isinstance(evidence_ids, list) or len(evidence_ids) > 20 or not all(
                isinstance(i, str) for i in evidence_ids):
            raise ToolError("evidence_ids must be a list of at most 20 strings")
        found = self._rows(Evidence.evidence_id.in_(evidence_ids))
        have = {r["evidence_id"] for r in found}
        return {"evidence": found, "not_found": sorted(set(evidence_ids) - have)}

    def _predictions(self) -> list[Prediction]:
        self._rows()  # same egress gate as raw evidence: derived values inherit their sources' rights
        return list(self.session.scalars(select(Prediction).where(Prediction.case_id == self.case_id)
                                         .order_by(Prediction.id)))

    def get_prediction(self, panel_id: str | None = None, board_id: str | None = None) -> dict:
        rows = [p for p in self._predictions()
                if (panel_id is None or p.target_key[0] == panel_id)
                and (board_id is None or p.target_key[1] == board_id)]
        return {"predictions": [{"evidence_id": f"PRED-{p.id}", "prediction_id": p.id, "target_key": p.target_key,
                                 "risk_score": round(p.risk_score, 4), "threshold": round(p.threshold, 4),
                                 "above_threshold": p.above_threshold, "input_evidence_ids": p.input_evidence_ids}
                                for p in rows],
                "note": "Model output on SYNTHETIC_LABEL data; not an inspection result."}

    def explain_prediction(self, prediction_id: int) -> dict:
        if not isinstance(prediction_id, int):
            raise ToolError("prediction_id must be an integer")
        p = next((p for p in self._predictions() if p.id == prediction_id), None)
        if p is None:
            raise ToolError("prediction not found in this case")
        x = self.session.scalar(select(XaiArtifact).where(XaiArtifact.prediction_id == p.id))
        return {"evidence_id": f"XAI-{x.id}", "method": x.method, "baseline_log_odds": round(x.baseline, 4),
                "contributions_log_odds": {k: round(v, 4) for k, v in
                                           sorted(x.contributions.items(), key=lambda kv: -abs(kv[1]))},
                "note": "SHAP attributes the model score; it is not evidence of a physical defect cause."}

    def retrieve_historical_cases(self) -> dict:
        from app import history
        self._rows()
        return history.retrieve(self.session, history.case_profile(self.session, self.case_id))

    def get_historical_case_outcome(self, historical_case_id: str) -> dict:
        found = next((p for p in self.retrieve_historical_cases()["precedents"]
                      if p["historical_case_id"] == historical_case_id), None)
        if found is None:
            raise ToolError("precedent not found or not eligible for this case")
        return found

    def check_data_integrity(self) -> dict:
        issues = self.session.scalars(select(DataQualityIssue).where(
            DataQualityIssue.case_id == self.case_id).order_by(DataQualityIssue.id)).all()
        return {"issue_counts": dict(Counter(i.code for i in issues)),
                "issues": [{"code": i.code, "severity": i.severity, "detail": i.detail,
                            "evidence_id": f"EV-{i.event_id}"} for i in issues[:50]]}
