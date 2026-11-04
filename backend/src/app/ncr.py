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

from app import spc
from app.db import Evidence, ModelVersion, Prediction, SourceAsset, SourceEvent, XaiArtifact

BUILDER = "DETERMINISTIC_TEMPLATE_NO_AI"
TEMPLATE_VERSION = "v5.g5"  # one statistic per SPC claim; v5.g4 added 5W2H / IS-IS NOT; s6.1 before
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


def lot_view(items: list[dict], aoi: dict) -> dict[str, dict]:
    """Per lot (line datasets only): lot record, panels, shipments, AOI FAIL keys and the ones not cleared."""
    lots = {i["key"][0]: {"lot": i, "panels": set(), "ship": [], "aoi": [], "fails": [], "open": []}
            for i in items if i["type"] == "lots"}
    panel_lot = {i["key"][0]: i["rec"].get("lot_id") for i in items if i["type"] == "panels"}
    for i in items:
        if i["type"] == "panels" and panel_lot[i["key"][0]] in lots:
            lots[panel_lot[i["key"][0]]]["panels"].add(i["key"][0])
        if i["type"] == "shipments" and i["rec"]["lot_id"] in lots:
            lots[i["rec"]["lot_id"]]["ship"].append(i)
    for key, a in aoi.items():
        v = lots.get(panel_lot.get(key[0]))
        if v is None:
            continue
        v["aoi"].append(key)
        if a["rec"]["result"] == "FAIL":
            v["fails"].append(key)
            human = _linked(items, "human_verifications", key)
            if not human or human["rec"]["result"] != "FALSE_ALARM":
                v["open"].append(key)
    return lots


def template_version(builder: str, claims: list) -> str | None:
    """Template a stored version was built with (from its own content, so older approvals keep their label)."""
    if builder != BUILDER:
        return None  # built from a model run, not the template
    if not any(c.text.startswith("5W2H ") for c in claims):
        return "s6.1"
    return "v5.g4" if any("LCL" in c.text and "UCL" in c.text for c in claims) else TEMPLATE_VERSION


def lot_index(items: list[dict]) -> dict[str, str | None]:
    """evidence id -> lot, from the row itself or its panel (never guessed from the id text)."""
    panel_lot = {i["rec"]["panel_id"]: i["rec"]["lot_id"] for i in items
                 if i["type"] == "panels" and i["rec"].get("lot_id")}
    return {i["ev"]: i["rec"].get("lot_id") or panel_lot.get(i["rec"].get("panel_id")) for i in items}


def problem_definition(items: list[dict]) -> dict:
    """D2 5W2H and IS / IS NOT over current source rows. Slots the data cannot fill are UNKNOWN."""
    lots = lot_index(items)
    aoi = [i for i in items if i["type"] == "aoi_inspections"]
    confirmed = [i for i in items if i["type"] == "human_verifications" and i["rec"]["result"] == "DEFECT_CONFIRMED"]
    inspected = {(i["rec"]["panel_id"], i["rec"]["board_id"]) for i in aoi}
    uninspected = [b for b in items if b["type"] == "boards"
                   and (b["rec"]["panel_id"], b["rec"]["board_id"]) not in inspected]
    lot_rows = {i["rec"]["lot_id"]: i["ev"] for i in items if i["type"] == "lots"}
    is_lots = sorted({lots[i["ev"]] for i in confirmed} - {None})
    versions: dict[str, int] = {}
    for i in items:
        versions[i["type"]] = max(versions.get(i["type"], 0), i["version"])
    times = sorted(i["rec"]["event_time"] for i in confirmed)
    hv = [i["ev"] for i in confirmed]

    def slot(value, ids, known=True):
        return {"value": value, "evidence_ids": ids,
                "status": "KNOWN" if known and value not in (None, [], {}) else "UNKNOWN"}

    return {
        "what": slot(f"{len(confirmed)} human-confirmed defects" if confirmed else None, hv),
        "where": slot(is_lots, hv, bool(lot_rows)),
        "when": slot({"first": times[0], "last": times[-1]} if times else None, hv),
        "who_detected": slot("AOI inspection, then human verification" if aoi else None, [i["ev"] for i in aoi[:1]]),
        "how_many": slot({"confirmed": len(confirmed), "denominator_aoi_inspections": len(aoi),
                          "boards_without_aoi": len(uninspected)} if aoi else None, [i["ev"] for i in aoi]),
        "is": slot({"lots": is_lots}, hv, bool(lot_rows) and bool(is_lots)),
        "is_not": slot({"lots": sorted(set(lot_rows) - set(is_lots))},
                       [ev for lot, ev in sorted(lot_rows.items()) if lot not in is_lots], bool(lot_rows)),
        "unknown_scope": [f"board {b['rec']['panel_id']}/{b['rec']['board_id']} has no AOI record"
                          for b in uninspected],
        "effective_source_versions": versions,
        "note": "Computed from current source rows. A count is a source-DB match, not physical ground truth.",
    }


def _five_w2h(items: list[dict], add: Callable[..., None]) -> None:
    """The D2 problem statement as claims, so it is part of the reviewed and hash-approved NCR."""
    p = problem_definition(items)
    rev = ", ".join(f"{k} v{v}" for k, v in sorted(p["effective_source_versions"].items()))
    if p["what"]["status"] == "KNOWN":
        n = p["how_many"]["value"]["confirmed"]
        add("CALCULATED", f"5W2H What: {n} defects confirmed by human verification.", p["what"]["evidence_ids"],
            float(n), "count")
        add("OBSERVED", f"5W2H When: first confirmed defect at {p['when']['value']['first']}, last at "
            f"{p['when']['value']['last']}.", p["when"]["evidence_ids"])
    else:
        add("UNKNOWN", "5W2H What/When: no human-confirmed defect in the sources; an AOI FAIL or SPC signal is not "
            "a confirmed defect.", [])
    if p["how_many"]["status"] == "KNOWN":
        hm = p["how_many"]["value"]
        add("CALCULATED", f"5W2H How many / how detected: {hm['confirmed']} confirmed of "
            f"{hm['denominator_aoi_inspections']} AOI inspections (AOI, then human verification); "
            f"{hm['boards_without_aoi']} boards have no AOI record, so their status is unknown. Source versions: "
            f"{rev}.", p["how_many"]["evidence_ids"], float(hm["denominator_aoi_inspections"]), "count")
    if p["is"]["status"] == "KNOWN":
        add("OBSERVED", f"IS: confirmed defects are in lot {', '.join(p['is']['value']['lots'])}.",
            p["is"]["evidence_ids"])
    else:
        add("UNKNOWN", "IS / IS NOT by lot: not determinable (no lot records or no confirmed defect).", [])
    if p["is"]["status"] == "KNOWN" and p["is_not"]["value"]["lots"]:
        add("OBSERVED", f"IS NOT: no human-confirmed defect recorded in lot {', '.join(p['is_not']['value']['lots'])}.",
            p["is_not"]["evidence_ids"])


def build_claims(session: Session, case_id: str) -> list[dict]:
    items = current(_evidence(session, case_id))
    claims, add = _collector()
    spi_by_board = latest_spi_by_board(items)
    aoi = _aoi(items)
    fails = sorted(k for k, i in aoi.items() if i["rec"]["result"] == "FAIL")
    if aoi:
        add("CALCULATED", f"{len(fails)} of {len(aoi)} AOI inspections reported FAIL.",
            [i["ev"] for i in aoi.values()], float(len(fails)), "count")
    for lot, v in sorted(lot_view(items, aoi).items()):
        if v["aoi"]:
            add("CALCULATED", f"Lot {lot}: {len(v['fails'])} of {len(v['aoi'])} AOI inspections reported FAIL; "
                f"{len(v['open'])} not cleared as false alarms.", [aoi[k]["ev"] for k in v["aoi"]],
                float(len(v["fails"])), "count")
    if m := spc.from_items(items):
        lim = m["limits"]
        for key, name in (("cl", "centre line"), ("lcl", "LCL"), ("ucl", "UCL")):  # one statistic per claim
            add("CALCULATED", f"SPC X-bar chart of SPI volume per board (n={m['n']} pins), {name} from reference "
                f"lot {m['reference_lot']}: {lim[key]} mm3.", m["reference_ev"], lim[key], "mm3")
        for lot, v in sorted(m["lots"].items()):
            if a := v["first_alarm"]:
                add("CALCULATED", f"Lot {lot}: {v['alarms']} of {v['boards']} boards signal on Western Electric/R "
                    f"rules; first at {a['panel']}/{a['board']} ({', '.join(a['rules'])}) with X-bar {a['xbar']} mm3. "
                    "A statistical signal, not a defect finding.", a["ev"], a["xbar"], "mm3")
            add("CALCULATED", f"Cpk of SPI volume in lot {lot} against the fictional {spc.LSL}-{spc.USL} mm3 spec: "
                f"{v['cpk']} (within-board sigma).", v["ev"], v["cpk"], "Cpk")
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
    _five_w2h(items, add)
    add("UNKNOWN", "Problem description (8D D2) only. Containment scope is the D3 plan; model scores, SHAP and "
        "cause candidates belong to the D4 RCA hypothesis.", [])
    return claims


def build_containment(session: Session, case_id: str) -> list[dict]:
    """Containment PLAN draft from AOI/human/repair and lot/shipment records. Proposals, nothing is executed here."""
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
    boards = {}
    for i in items:
        if i["type"] == "boards":
            boards.setdefault(i["key"][0], 0)
            boards[i["key"][0]] += 1
    for lot, v in sorted(lot_view(items, aoi).items()):
        if not v["fails"]:
            continue
        if not v["open"]:
            add("OBSERVED", f"No lot-level hold proposed for lot {lot}: all {len(v['fails'])} AOI FAILs were "
                "verified FALSE_ALARM.", [aoi[k]["ev"] for k in v["fails"]])
            continue
        why = [aoi[k]["ev"] for k in v["open"]]
        wip = [x for x in v["ship"] if x["rec"]["status"] != "SHIPPED"]
        out = [x for x in v["ship"] if x["rec"]["status"] == "SHIPPED"]
        if wip:
            add("PROPOSAL", f"Proposed, not executed: hold the {len(wip)} unshipped panels of lot {lot} "
                f"({sum(boards.get(x['key'][0], 0) for x in wip)} boards) pending QA disposition; {len(v['open'])} "
                "AOI FAILs in this lot are not cleared as false alarms.", [*why, *(x["ev"] for x in wip)])
        if out:
            add("PROPOSAL", f"Proposed, not executed: QA to decide customer notification or field containment for "
                f"the {len(out)} already SHIPPED panels of lot {lot} "
                f"({sum(boards.get(x['key'][0], 0) for x in out)} boards).", [*why, *(x["ev"] for x in out)])
    add("UNKNOWN", "Lot and shipment scope beyond the recorded panels is not determined. "
        "Execution status: NOT_EXECUTED; any hold must be performed and recorded by Production.", [])
    return claims


def build_rca(session: Session, case_id: str) -> list[dict]:
    """Cause HYPOTHESIS draft for boards with a confirmed or unverified AOI FAIL. Never a confirmed cause."""
    items = current(_evidence(session, case_id))
    claims, add = _collector()
    spi_by_board, aoi = latest_spi_by_board(items), _aoi(items)
    lots = lot_view(items, aoi)
    in_lot = {p for v in lots.values() if v["open"] for p in v["panels"]}  # covered by the lot hypothesis below
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
        if panel in in_lot:
            continue
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
    for lot, v in sorted(lots.items()):
        if not v["open"]:
            continue
        rec = v["lot"]["rec"]
        eq = [i for i in items if i["type"] == "equipment_events" and i["key"][0] == rec["stencil_id"]]
        inside = [i for k, rows in spi_by_board.items() if k[0] in v["panels"] for i in rows]
        rest = [i for k, rows in spi_by_board.items() if k[0] not in v["panels"] for i in rows]
        if inside and rest:
            a, b = (round(mean(i["rec"]["volume_mm3"] for i in x), 4) for x in (inside, rest))
            add("CALCULATED", f"Mean SPI solder volume in lot {lot} is {a} mm3 over {len(inside)} pins.",
                [i["ev"] for i in inside], a, "mm3")
            add("CALCULATED", f"Mean SPI solder volume in the other lots is {b} mm3 over {len(rest)} pins.",
                [i["ev"] for i in rest], b, "mm3")
        add("OBSERVED", f"Lot {lot} ran on line {rec['line_id']} with stencil {rec['stencil_id']} and paste lot "
            f"{rec['paste_lot']}.", [v["lot"]["ev"]])
        for e in eq:
            add("OBSERVED", f"Equipment record for {rec['stencil_id']}: {e['rec']['status']}.", [e["ev"]])
        add("HYPOTHESIS", f"Candidate cause (UNCONFIRMED): condition of stencil {rec['stencil_id']} used for lot {lot}. "
            "A lower lot SPI mean and the equipment record are consistent with it but do not establish causation.",
            [v["lot"]["ev"], *(e["ev"] for e in eq)])
        add("PROPOSAL", f"Proposed verification, not executed: inspect stencil {rec['stencil_id']} apertures and "
            f"compare SPI on a run with a fresh stencil, paste lot {rec['paste_lot']} unchanged.",
            [v["lot"]["ev"], *(e["ev"] for e in eq)])
    add("UNKNOWN", "No verification result is recorded. Cause status: UNCONFIRMED until a Process Engineer "
        "records the verification outcome.", [])
    return claims


BUILDERS = {"NCR": build_claims, "CONTAINMENT": build_containment, "RCA": build_rca}
DOC_NOTE = {"CONTAINMENT": "Plan draft. Execution status: NOT_EXECUTED.",
            "RCA": "Cause hypothesis. Cause status: UNCONFIRMED."}


WORDING_PROMPT = """You write the sentences of a {doc} draft for a manufacturing quality engineer, in plain, polite Korean.
Each claim gives its class and the facts as a sentence. Rewrite only the sentence. Keep every number, unit, LOT, board,
part and code exactly as written (L02, P03/B4, U7, 0.1128, mm³, FAIL). Add no number, cause or finished action:
a HYPOTHESIS stays a candidate, UNKNOWN says what is not known, a PROPOSAL is not yet done.
Ordinary English words become Korean (false alarm -> 오검출, pins -> 핀, within-board sigma -> 보드 내 표준편차, lot -> LOT).
Fixed forms the server reads: "N of M AOI inspections" -> "AOI 검사 M건 중 N건" ("N confirmed of M" -> "AOI 검사 M건 중 확정 N건");
"centre line" -> "중심선"; keep LCL and UCL as written; a count of confirmed defects says "확정".
Return ONLY the JSON: claims with claim_id and text for every claim."""
WORDING_SCHEMA = {"type": "json_schema", "json_schema": {"name": "wording", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["claims"],
    "properties": {"claims": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["claim_id", "text"],
        "properties": {"claim_id": {"type": "string"}, "text": {"type": "string"}}}}}}}}


def ai_wording(provider, doc_type: str, claims: list[dict], check: Callable[[list[dict]], dict[str, str]] | None = None,
               repairs: int = 2) -> tuple[list[dict], str]:
    """The AI writes every sentence (user 2026-11-04); the server only checks each one carries exactly the numbers
    and codes of the facts it was given, then runs the draft check (`check`: claim id -> problem) on the result. A
    sentence that fails either goes back to the AI with the reason; one still failing
    after the repairs keeps the facts sentence. Returns (claims, builder)."""
    from app.translate import TOKEN, kept  # translate imports workflow, which imports this module

    facts = {c["claim_id"]: c for c in claims}
    out: dict[str, str] = {}
    todo = list(facts)
    msgs = [{"role": "system", "content": WORDING_PROMPT.format(doc=doc_type)},
            {"role": "user", "content": json.dumps({"claims": [
                {"claim_id": i, "class": facts[i]["classification"], "text": facts[i]["text"]} for i in todo]},
                ensure_ascii=False)}]
    for _ in range(1 + repairs):
        try:
            msg = provider.chat(msgs, [], response_format=WORDING_SCHEMA)["message"]
            items = json.loads(msg.get("content") or "")["claims"]
        except Exception:  # noqa: BLE001 - any model failure leaves the facts sentences in place
            break
        wrong = []
        for it in items if isinstance(items, list) else []:
            cid, text = (it.get("claim_id"), str(it.get("text") or "").strip()) if isinstance(it, dict) else (None, "")
            if cid not in todo:
                continue
            if kept(facts[cid]["text"], text) and not DONE_CLAIM.search(text):
                out[cid] = text
            else:
                want, got = sorted(TOKEN.findall(facts[cid]["text"])), sorted(TOKEN.findall(text))
                wrong.append({"claim_id": cid, "problem": f"numbers and codes must be exactly {want}; you wrote {got}"})
        if check and out:  # the same claim validator a stored draft meets (recomputed values, lots, units)
            for cid, problem in check([{**c, "text": out.get(c["claim_id"], c["text"])} for c in claims]).items():
                if cid in out:
                    del out[cid]
                    wrong.append({"claim_id": cid, "problem": problem})
        todo = [i for i in facts if i not in out]  # a sentence the draft check refused is open again
        if not todo:
            break
        msgs += [msg, {"role": "user", "content": json.dumps(
            {"fix_only_these": wrong or [{"claim_id": i, "problem": "missing from your answer"} for i in todo]},
            ensure_ascii=False)}]
    if not out:
        return claims, BUILDER
    return [{**c, "text": out.get(c["claim_id"], c["text"])} for c in claims], f"TEMPLATE_AI_WORDING:{provider.model}"


def generator_note(builder: str) -> str:
    if builder == BUILDER:
        return "no AI model used"
    if builder.startswith("HUMAN_EDIT:"):
        return f"edited by a person from {builder.split(':', 1)[1]}; re-validated by the server ClaimValidator"
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
