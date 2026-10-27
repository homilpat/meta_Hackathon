"""Deterministic document templates over case evidence: NCR (S2), Containment plan and RCA hypothesis (S6).

No AI/model is involved here. Containment items are proposals, never executed actions; RCA stays a hypothesis.
"""

import hashlib
import html
import json
import re
from collections.abc import Callable
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Evidence, ModelVersion, Prediction, SourceAsset, SourceEvent, XaiArtifact

BUILDER = "DETERMINISTIC_TEMPLATE_NO_AI"
TEMPLATE_VERSION = "s6.1"
CLASSES = ("OBSERVED", "CALCULATED", "HYPOTHESIS", "UNKNOWN", "PROPOSAL")
# A draft may propose; it may not report an action as done or a cause as established.
DONE_CLAIM = re.compile(r"(?i)\b(?:been|was|were|is|are)\s+(?:executed|implemented|contained|quarantined|resolved|fixed)\b"
                        r"|\broot cause\s+(?:is|was|has been)\s+(?:confirmed|identified|established|determined)\b")


def validate_claims(claims: list[dict], known_evidence: set[str]) -> None:
    """Every OBSERVED/CALCULATED claim and every numeric value must cite existing evidence."""
    for claim in claims:
        cid, ids = claim.get("claim_id"), claim.get("evidence_ids") or []
        if claim.get("classification") not in CLASSES or not claim.get("text"):
            raise ValueError(f"{cid}: invalid classification or empty text")
        if DONE_CLAIM.search(claim["text"]):
            raise ValueError(f"{cid}: drafts may not state an action as executed or a cause as confirmed")
        if claim["classification"] in ("OBSERVED", "CALCULATED", "PROPOSAL") and not ids:
            raise ValueError(f"{cid}: {claim['classification']} claim needs evidence_ids")
        if claim.get("value") is not None and not ids:
            raise ValueError(f"{cid}: numeric value needs evidence_ids")
        if unknown := set(ids) - known_evidence:
            raise ValueError(f"{cid}: unknown evidence {sorted(unknown)}")


def content_sha256(case_id: str, version: int, claims: list[dict], builder: str = BUILDER,
                   extra: dict | None = None) -> str:
    body = {"case_id": case_id, "version": version, "builder": builder, "claims": claims, **(extra or {})}
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


def current(items: list[dict]) -> list[dict]:
    """Drop source rows that a later source version corrected (same type and original row id)."""
    top: dict[tuple, int] = {}
    for i in items:
        k = (i["type"], i["rec"]["original_row_id"])
        top[k] = max(top.get(k, 0), i["version"])
    return [i for i in items if i["version"] == top[(i["type"], i["rec"]["original_row_id"])]]


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


def _collector() -> tuple[list[dict], Callable[..., None]]:
    claims: list[dict] = []

    def add(cls: str, text: str, ev: list[str], value: float | None = None, unit: str | None = None):
        claims.append({"claim_id": f"C{len(claims) + 1}", "classification": cls, "text": text,
                       "value": value, "unit": unit, "evidence_ids": ev})

    return claims, add


def _aoi(items: list[dict]) -> dict[tuple, dict]:
    aoi: dict[tuple, dict] = {}
    for i in items:  # first record wins; S1 already flags duplicate inspections
        if i["type"] == "aoi_inspections":
            aoi.setdefault((*i["key"], i["rec"]["inspection_id"]), i)
    return aoi


def _linked(items: list[dict], kind: str, key: tuple) -> dict | None:
    return next((i for i in items if i["type"] == kind and (*i["key"], i["rec"]["inspection_id"]) == key), None)


def _uninspected(items: list[dict], aoi: dict) -> list[dict]:
    inspected = {k[:2] for k in aoi}
    return [b for b in items if b["type"] == "boards" and b["key"] not in inspected]


def build_claims(session: Session, case_id: str) -> list[dict]:
    items = current(_evidence(session, case_id))
    claims, add = _collector()
    spi_by_board = latest_spi_by_board(items)
    aoi = _aoi(items)
    fails = sorted(k for k, i in aoi.items() if i["rec"]["result"] == "FAIL")
    if aoi:
        add("CALCULATED", f"{len(fails)} of {len(aoi)} AOI inspections reported FAIL.",
            [i["ev"] for i in aoi.values()], float(len(fails)), "count")
    for key in fails:
        panel, board, insp = key
        add("OBSERVED", f"AOI inspection {insp} on board {panel}/{board} reported FAIL.", [aoi[key]["ev"]])
        human = _linked(items, "human_verifications", key)
        if human:
            add("OBSERVED", f"Human verification of {insp} on {panel}/{board}: {human['rec']['result']}.",
                [human["ev"]])
        else:
            add("UNKNOWN", f"No human verification recorded for {insp} on {panel}/{board}.", [aoi[key]["ev"]])
        repair = _linked(items, "repair_dispositions", key)
        if repair:
            add("OBSERVED", f"Repair disposition for {insp} on {panel}/{board}: {repair['rec']['disposition']}.",
                [repair["ev"]])
        spi = spi_by_board.get((panel, board), [])
        if spi:
            avg = round(mean(i["rec"]["volume_mm3"] for i in spi), 4)
            add("CALCULATED", f"Mean SPI solder volume on {panel}/{board} is {avg} mm3 over {len(spi)} "
                "pin measurements (latest source version per row).", [i["ev"] for i in spi], avg, "mm3")
    for board in _uninspected(items, aoi):
        add("UNKNOWN", f"No AOI inspection recorded for board {'/'.join(board['key'])}; "
            "a missing record is not a PASS.", [board["ev"]])
    add("UNKNOWN", "Problem description (8D D2) only. Containment scope is the D3 plan; model scores, SHAP and "
        "cause candidates belong to the D4 RCA hypothesis.", [])
    return claims


def build_containment(session: Session, case_id: str) -> list[dict]:
    """Containment PLAN draft from AOI/human/repair records only. Proposals, nothing is executed here."""
    items = current(_evidence(session, case_id))
    claims, add = _collector()
    aoi = _aoi(items)
    for key in sorted(k for k, i in aoi.items() if i["rec"]["result"] == "FAIL"):
        panel, board, insp = key
        human, repair = _linked(items, "human_verifications", key), _linked(items, "repair_dispositions", key)
        refs = [i["ev"] for i in (aoi[key], human, repair) if i]
        verdict = human["rec"]["result"] if human else "not recorded"
        if verdict == "FALSE_ALARM":
            add("OBSERVED", f"No containment proposed for {panel}/{board}: human verification of AOI {insp} "
                "recorded FALSE_ALARM.", refs)
        else:
            add("PROPOSAL", f"Proposed, not executed: segregate board {panel}/{board} and hold the other boards "
                f"of panel {panel} pending QA disposition (AOI {insp} FAIL, human verification {verdict}).", refs)
    for b in _uninspected(items, aoi):
        add("PROPOSAL", f"Proposed, not executed: hold board {'/'.join(b['key'])} until an AOI inspection is "
            "recorded; a missing record is not a PASS.", [b["ev"]])
    add("UNKNOWN", "Lot and shipment scope beyond the recorded panels is not determined. "
        "Execution status: NOT_EXECUTED; any hold must be performed and recorded by Production.", [])
    return claims


def build_rca(session: Session, case_id: str) -> list[dict]:
    """Cause HYPOTHESIS draft for boards with a confirmed or unverified AOI FAIL. Never a confirmed cause."""
    items = current(_evidence(session, case_id))
    claims, add = _collector()
    spi_by_board, aoi = latest_spi_by_board(items), _aoi(items)
    boards = []
    for key in sorted(k for k, i in aoi.items() if i["rec"]["result"] == "FAIL"):
        human = _linked(items, "human_verifications", key)
        if human and human["rec"]["result"] == "FALSE_ALARM":
            continue
        panel, board, insp = key
        boards.append([panel, board])
        spi = spi_by_board.get((panel, board), [])
        if not spi:
            add("UNKNOWN", f"No SPI measurement for {panel}/{board}; a paste-deposit hypothesis cannot be assessed.",
                [aoi[key]["ev"]])
            continue
        ev = [i["ev"] for i in spi]
        avg = round(mean(i["rec"]["volume_mm3"] for i in spi), 4)
        add("CALCULATED", f"Mean SPI solder volume on {panel}/{board} is {avg} mm3 over {len(spi)} pin "
            "measurements (latest source version per row).", ev, avg, "mm3")
        add("HYPOTHESIS", f"Candidate cause (UNCONFIRMED): solder paste deposit variation on {panel}/{board}. "
            f"The SPI values and AOI {insp} FAIL are consistent with it but do not establish causation.",
            [*ev, aoi[key]["ev"]])
        add("PROPOSAL", f"Proposed verification, not executed: stencil aperture inspection and SPI calibration "
            f"log review for {panel}/{board}.", ev)
    for p in session.scalars(select(Prediction).where(Prediction.case_id == case_id).order_by(Prediction.id)):
        if p.target_key in boards:
            mv = session.get(ModelVersion, p.model_version_id)
            x = session.scalar(select(XaiArtifact).where(XaiArtifact.prediction_id == p.id))
            board = "/".join(p.target_key)
            add("CALCULATED", f"SPI risk model {mv.name} v{mv.id} scored {board} at {p.risk_score:.3f} "
                f"(threshold {p.threshold:.3f}, {mv.label_kind}). A correlation signal from model output, not "
                "causal evidence.", [f"PRED-{p.id}", *p.input_evidence_ids], round(p.risk_score, 4), "score")
            top = sorted(x.contributions.items(), key=lambda kv: -abs(kv[1]))[:3]
            add("CALCULATED", f"Largest SHAP contributions to the {board} score: "
                + ", ".join(f"{k} {v:+.2f}" for k, v in top)
                + " (log-odds). SHAP explains the model score, not the physical defect cause.", [f"XAI-{x.id}"])
    add("UNKNOWN", "No verification result is recorded. Cause status: UNCONFIRMED until a Process Engineer "
        "records the verification outcome.", [])
    return claims


BUILDERS = {"NCR": build_claims, "CONTAINMENT": build_containment, "RCA": build_rca}
DOC_NOTE = {"CONTAINMENT": "Plan draft. Execution status: NOT_EXECUTED.",
            "RCA": "Cause hypothesis. Cause status: UNCONFIRMED."}


def generator_note(builder: str) -> str:
    if builder == BUILDER:
        return "no AI model used"
    return "model output, accepted only after server-side ClaimValidator"


def render_html(doc: dict) -> str:
    rows = "".join(
        f"<tr><td>{c['claim_id']}</td><td>{c['classification']}</td><td>{html.escape(c['text'])}</td>"
        f"<td>{html.escape(', '.join(c['evidence_ids']) or '-')}</td></tr>" for c in doc["claims"])
    return (
        f"<!doctype html><meta charset=utf-8><title>{doc['doc_type']} draft</title>"
        f"<h1>{doc['doc_type']} {html.escape(doc['case_id'])} v{doc['version']} — {doc['status']}</h1>"
        f"<p>Template {TEMPLATE_VERSION} · based on: {html.escape(', '.join(doc['based_on']) or '-')} · "
        f"created {html.escape(doc['created_at'])}. {DOC_NOTE.get(doc['doc_type'], '')}</p>"
        f"<p><b>Draft generator: {html.escape(doc['builder'])} ({generator_note(doc['builder'])}). "
        "Synthetic data.</b></p>"
        f"<p>Author: {html.escape(doc['author_id'])} · SHA-256: <code>{doc['content_sha256']}</code></p>"
        "<table border=1 cellpadding=4><tr><th>ID</th><th>Class</th><th>Statement</th><th>Evidence</th></tr>"
        f"{rows}</table>")
