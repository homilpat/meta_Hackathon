"""S2 NCR draft: deterministic template over S1 evidence. No AI/model is involved (that is S3)."""

import hashlib
import html
import json
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Evidence, ModelVersion, Prediction, SourceAsset, SourceEvent, XaiArtifact

BUILDER = "DETERMINISTIC_TEMPLATE_NO_AI"
CLASSES = ("OBSERVED", "CALCULATED", "HYPOTHESIS", "UNKNOWN")


def validate_claims(claims: list[dict], known_evidence: set[str]) -> None:
    """Every OBSERVED/CALCULATED claim and every numeric value must cite existing evidence."""
    for claim in claims:
        cid, ids = claim.get("claim_id"), claim.get("evidence_ids") or []
        if claim.get("classification") not in CLASSES or not claim.get("text"):
            raise ValueError(f"{cid}: invalid classification or empty text")
        if claim["classification"] in ("OBSERVED", "CALCULATED") and not ids:
            raise ValueError(f"{cid}: {claim['classification']} claim needs evidence_ids")
        if claim.get("value") is not None and not ids:
            raise ValueError(f"{cid}: numeric value needs evidence_ids")
        if unknown := set(ids) - known_evidence:
            raise ValueError(f"{cid}: unknown evidence {sorted(unknown)}")


def content_sha256(case_id: str, version: int, claims: list[dict], builder: str = BUILDER) -> str:
    body = {"case_id": case_id, "version": version, "builder": builder, "claims": claims}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _evidence(session: Session, case_id: str) -> list[dict]:
    rows = session.execute(
        select(Evidence, SourceEvent, SourceAsset)
        .join(SourceEvent, Evidence.source_event_id == SourceEvent.id)
        .join(SourceAsset, SourceEvent.source_asset_id == SourceAsset.id)
        .where(Evidence.case_id == case_id, Evidence.validity == "CHECKED")
        .order_by(Evidence.id)).all()
    return [{"ev": v.evidence_id, "type": e.entity_type, "key": tuple(e.entity_key),
             "rec": json.loads(e.raw_json), "version": a.source_version} for v, e, a in rows]


def latest_spi_by_board(items: list[dict]) -> dict[tuple, list[dict]]:
    """SPI evidence per (panel, board): one measurement per source row; the corrected version wins."""
    latest: dict[tuple, dict[str, dict]] = {}
    for i in items:
        if i["type"] == "spi_measurements":
            rows = latest.setdefault(tuple(i["key"][:2]), {})
            old = rows.get(i["rec"]["original_row_id"])
            if old is None or i["version"] > old["version"]:
                rows[i["rec"]["original_row_id"]] = i
    return {k: list(v.values()) for k, v in latest.items()}


def derived_records(session: Session, case_id: str) -> dict[str, dict]:
    """Citable model evidence (PRED-n, XAI-n) with the fields a claim may compute from."""
    out: dict[str, dict] = {}
    for p in session.scalars(select(Prediction).where(Prediction.case_id == case_id)):
        out[f"PRED-{p.id}"] = {"risk_score": p.risk_score, "threshold": p.threshold, "target_key": p.target_key}
        for x in session.scalars(select(XaiArtifact).where(XaiArtifact.prediction_id == p.id)):
            out[f"XAI-{x.id}"] = {"baseline": x.baseline, "raw_score": x.raw_score, **x.contributions}
    return out


def build_claims(session: Session, case_id: str) -> list[dict]:
    items = _evidence(session, case_id)
    claims: list[dict] = []

    def add(cls: str, text: str, ev: list[str], value: float | None = None, unit: str | None = None):
        claims.append({"claim_id": f"C{len(claims) + 1}", "classification": cls, "text": text,
                       "value": value, "unit": unit, "evidence_ids": ev})

    def of(kind: str) -> list[dict]:
        return [i for i in items if i["type"] == kind]

    spi_by_board = latest_spi_by_board(items)
    aoi = {}
    for i in of("aoi_inspections"):  # first record wins; S1 already flags duplicate inspections
        aoi.setdefault((*i["key"], i["rec"]["inspection_id"]), i)
    fails = sorted(k for k, i in aoi.items() if i["rec"]["result"] == "FAIL")
    if aoi:
        add("CALCULATED", f"{len(fails)} of {len(aoi)} AOI inspections reported FAIL.",
            [i["ev"] for i in aoi.values()], float(len(fails)), "count")
    for key in fails:
        panel, board, insp = key
        add("OBSERVED", f"AOI inspection {insp} on board {panel}/{board} reported FAIL.", [aoi[key]["ev"]])
        human = next((i for i in of("human_verifications") if (*i["key"], i["rec"]["inspection_id"]) == key), None)
        if human:
            add("OBSERVED", f"Human verification of {insp} on {panel}/{board}: {human['rec']['result']}.",
                [human["ev"]])
        else:
            add("UNKNOWN", f"No human verification recorded for {insp} on {panel}/{board}.", [aoi[key]["ev"]])
        repair = next((i for i in of("repair_dispositions") if (*i["key"], i["rec"]["inspection_id"]) == key), None)
        if repair:
            add("OBSERVED", f"Repair disposition for {insp} on {panel}/{board}: {repair['rec']['disposition']}.",
                [repair["ev"]])
        spi = spi_by_board.get((panel, board), [])
        if spi:
            avg = round(mean(i["rec"]["volume_mm3"] for i in spi), 4)
            add("CALCULATED", f"Mean SPI solder volume on {panel}/{board} is {avg} mm3 over {len(spi)} "
                "pin measurements (latest source version per row).", [i["ev"] for i in spi], avg, "mm3")
            if not human or human["rec"]["result"] != "FALSE_ALARM":
                add("HYPOTHESIS", f"Solder paste deposit variation on {panel}/{board} is a candidate cause "
                    "to investigate. Not verified; SPI values alone do not establish causation.",
                    [i["ev"] for i in spi])
    inspected = {k[:2] for k in aoi}
    for board in of("boards"):
        if board["key"] not in inspected:
            add("UNKNOWN", f"No AOI inspection recorded for board {'/'.join(board['key'])}; "
                "a missing record is not a PASS.", [board["ev"]])
    for p in session.scalars(select(Prediction).where(Prediction.case_id == case_id).order_by(Prediction.id)):
        mv = session.get(ModelVersion, p.model_version_id)
        x = session.scalar(select(XaiArtifact).where(XaiArtifact.prediction_id == p.id))
        board = "/".join(p.target_key)
        add("CALCULATED", f"SPI risk model {mv.name} v{mv.id} scored {board} at {p.risk_score:.3f} "
            f"(threshold {p.threshold:.3f}, {mv.label_kind}). Model output, not an inspection result.",
            [f"PRED-{p.id}", *p.input_evidence_ids], round(p.risk_score, 4), "score")
        top = sorted(x.contributions.items(), key=lambda kv: -abs(kv[1]))[:3]
        add("CALCULATED", f"Largest SHAP contributions to the {board} score: "
            + ", ".join(f"{k} {v:+.2f}" for k, v in top)
            + " (log-odds). SHAP explains the model score, not the physical defect cause.", [f"XAI-{x.id}"])
    add("UNKNOWN", "Root cause, containment scope and lot impact are not determined; "
        "no investigation has been performed.", [])
    return claims


def generator_note(builder: str) -> str:
    if builder == BUILDER:
        return "no AI model used"
    return "model output, accepted only after server-side ClaimValidator"


def render_html(doc: dict) -> str:
    rows = "".join(
        f"<tr><td>{c['claim_id']}</td><td>{c['classification']}</td><td>{html.escape(c['text'])}</td>"
        f"<td>{html.escape(', '.join(c['evidence_ids']) or '-')}</td></tr>" for c in doc["claims"])
    return (
        "<!doctype html><meta charset=utf-8><title>NCR draft</title>"
        f"<h1>NCR {html.escape(doc['case_id'])} v{doc['version']} — {doc['status']}</h1>"
        f"<p><b>Draft generator: {html.escape(doc['builder'])} ({generator_note(doc['builder'])}). "
        "Synthetic data.</b></p>"
        f"<p>Author: {html.escape(doc['author_id'])} · SHA-256: <code>{doc['content_sha256']}</code></p>"
        "<table border=1 cellpadding=4><tr><th>ID</th><th>Class</th><th>Statement</th><th>Evidence</th></tr>"
        f"{rows}</table>")
