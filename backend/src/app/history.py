"""S5 historical-case harness: synthetic precedent bank, eligibility filter, retrieval, next-evidence planner.

Precedents are retrieval candidates for choosing the next check. Similarity is a ranking, not causal
inference, and a past outcome never confirms the current case's cause. Nothing here retrains a model.
"""

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import HistoricalCase, HistoricalEvidence, HistoricalOutcome, SourceEvent
from app.ml import NOMINAL, SPEC, board_features
from app.ncr import _evidence, latest_spi_by_board

BANK_VERSION = "s5-history-1"
CASE_SITE = "SYNTHETIC_SITE_A"  # ponytail: one demo site for all synthetic cases; real sites come with real auth
PROCESS = "PCB_ASSEMBLY"
APPROVED = ("SYNTHETIC", "APPROVED_FOR_EXTERNAL")

CHECKS = {
    "OPERATOR_ADJUDICATION": ("Quality operator", "Have an operator adjudicate the AOI call on the physical board"),
    "AOI_RERUN": ("AOI technician", "Run or retrieve the AOI inspection for the board with no AOI record"),
    "STENCIL_APERTURE_INSPECTION": ("Process engineer", "Inspect stencil apertures for clogging at the affected pads"),
    "STENCIL_THICKNESS_CHECK": ("Process engineer", "Measure stencil thickness and aperture size against spec"),
    "SPI_CALIBRATION_LOG": ("Metrology", "Pull the SPI calibration and verification log for the shift"),
    "AOI_LIBRARY_REVIEW": ("AOI programmer", "Review the AOI library / threshold for the flagged component"),
    "REFLOW_PROFILE_LOG": ("Process engineer", "Pull the reflow oven profile log for the lot"),
    "XRAY_CROSS_SECTION": ("Failure analysis", "X-ray or cross-section the confirmed defective joint"),
}
# words that identify an action in free text, used to catch failed fixes being recommended
ACTION_TERMS = {
    "STENCIL_CLEAN": "stencil clean", "PRINTER_PRESSURE_ADJUST": "printer pressure",
    "SPI_RECALIBRATION": "recalibrat", "AOI_THRESHOLD_TUNE": "aoi threshold",
    "STENCIL_REPLACE": "replace the stencil", "REFLOW_PROFILE_CHANGE": "reflow profile change",
}
NEGATION = ("do not", "don't", "avoid", "not adopt", "not repeat", "not recommended")


def _h(hid, *, ver=1, site=CASE_SITE, sens="APPROVED_FOR_EXTERNAL", status="APPROVED", process=PROCESS,
       spi, aoi, incident, available, summary, evidence, outcomes, limitations, superseded_by=None, family=None):
    return {"historical_case_id": hid, "snapshot_version": ver, "family": family or hid, "site": site,
            "source_origin": "SYNTHETIC", "sensitivity": sens, "review_status": status, "process_stage": process,
            "measurement_pattern": spi, "aoi_pattern": aoi, "incident_at": incident, "available_at": available,
            "summary": summary, "evidence": evidence, "outcomes": outcomes, "limitations": limitations,
            "superseded_by": superseded_by}


def _o(check, check_result, check_status, action=None, action_status="NONE", status="UNKNOWN", metric=None,
       before=None, after=None, n=None, verified_at=None):
    return {"check": check, "check_result": check_result, "check_status": check_status, "action": action,
            "action_status": action_status, "outcome_status": status, "metric": metric, "before": before,
            "after": after, "sample_count": n, "verified_at": verified_at}


def bank() -> list[dict]:
    """Hand-curated SYNTHETIC precedents incl. failed, insufficient, unknown, retracted, draft,
    cross-site, confidential, future and wrong-process records."""
    d = "2025-{}T00:00:00+00:00".format
    return [
        _h("H01", spi="SPI_VOLUME_LOW", aoi="AOI_FAIL_CONFIRMED", incident=d("03-02"), available=d("03-20"),
           summary="Low paste volume with confirmed insufficient-solder defects.",
           evidence=["SPI volume low on affected pads", "Operator confirmed insufficient solder"],
           outcomes=[_o("STENCIL_APERTURE_INSPECTION", "Clogged apertures found on affected pads", "VERIFIED",
                        "STENCIL_CLEAN", "EXECUTED", "VERIFIED", "insufficient-solder rate", 0.021, 0.004, 1200,
                        d("03-19"))],
           limitations=["Single line, single shift"]),
        _h("H02", spi="SPI_VOLUME_LOW", aoi="AOI_FALSE_ALARM", incident=d("04-11"), available=d("05-02"),
           summary="Low SPI readings with AOI calls that operators judged false alarms.",
           evidence=["SPI volume low", "Operator: FALSE_ALARM on 9 of 10 calls"],
           outcomes=[_o("OPERATOR_ADJUDICATION", "Most AOI calls were false positives", "VERIFIED",
                        "PRINTER_PRESSURE_ADJUST", "EXECUTED", "FAILED", "AOI alarm rate", 0.08, 0.08, 900,
                        d("05-01"))],
           limitations=["Pressure change did not reduce alarms; underlying cause not established"]),
        _h("H03", spi="SPI_VOLUME_SCATTER", aoi="AOI_FAIL_CONFIRMED", incident=d("05-07"), available=d("05-28"),
           summary="Scattered SPI volumes; SPI instrument drift found.",
           evidence=["SPI repeatability out of tolerance"],
           outcomes=[_o("SPI_CALIBRATION_LOG", "Calibration overdue, gauge R&R failed", "VERIFIED",
                        "SPI_RECALIBRATION", "EXECUTED", "VERIFIED", "SPI repeatability %", 14.0, 4.0, 300,
                        d("05-27"))],
           limitations=["Defect rate after recalibration not tracked separately"]),
        _h("H04", spi="NORMAL", aoi="AOI_FALSE_ALARM", incident=d("06-01"), available=d("06-25"),
           summary="Normal SPI, AOI false alarms on one component library.",
           evidence=["Operator: FALSE_ALARM"],
           outcomes=[_o("AOI_LIBRARY_REVIEW", "Threshold tighter than library default", "VERIFIED",
                        "AOI_THRESHOLD_TUNE", "EXECUTED", "INSUFFICIENT", "false-call rate", 0.05, 0.03, 40,
                        d("06-24"))],
           limitations=["Only 40 boards observed after the change"]),
        _h("H05", spi="SPI_VOLUME_HIGH", aoi="AOI_FAIL_CONFIRMED", incident=d("07-03"), available=d("07-30"),
           summary="High paste volume with confirmed bridging.",
           evidence=["SPI volume high", "Operator confirmed bridge"],
           outcomes=[_o("STENCIL_THICKNESS_CHECK", "Stencil 20% thicker than spec", "VERIFIED",
                        "STENCIL_REPLACE", "EXECUTED", "VERIFIED", "bridge rate", 0.015, 0.002, 1500, d("07-29"))],
           limitations=[]),
        _h("H06", spi="SPI_VOLUME_LOW", aoi="AOI_MISSING", incident=d("08-05"), available=d("08-20"),
           summary="AOI skipped on part of a lot; rerun found defects.",
           evidence=["AOI log gap for 12 boards"],
           outcomes=[_o("AOI_RERUN", "Rerun flagged 2 of 12 boards", "VERIFIED")],
           limitations=["No follow-up on the flagged boards"]),
        _h("H07", status="RETRACTED", superseded_by="H08", family="H07", spi="SPI_VOLUME_SCATTER",
           aoi="AOI_FALSE_ALARM", incident=d("08-15"), available=d("09-01"),
           summary="Retracted: claimed reflow profile as root cause without evidence.",
           evidence=[], outcomes=[_o("REFLOW_PROFILE_LOG", "Not reviewed", "UNKNOWN")],
           limitations=["Retracted by quality review"]),
        _h("H08", ver=2, family="H07", spi="SPI_VOLUME_SCATTER", aoi="AOI_FALSE_ALARM", incident=d("08-15"),
           available=d("09-20"), summary="Revision of H07: reflow change attempted, no improvement.",
           evidence=["Operator: FALSE_ALARM"],
           outcomes=[_o("REFLOW_PROFILE_LOG", "Profile within window", "VERIFIED", "REFLOW_PROFILE_CHANGE",
                        "EXECUTED", "FAILED", "AOI alarm rate", 0.06, 0.06, 700, d("09-18"))],
           limitations=["Cause of false alarms still unknown"]),
        _h("H09", status="DRAFT", spi="SPI_VOLUME_LOW", aoi="AOI_FAIL_CONFIRMED", incident=d("09-10"),
           available=d("09-12"), summary="Unreviewed draft.", evidence=[],
           outcomes=[_o("STENCIL_APERTURE_INSPECTION", "Claimed success", "UNKNOWN", "STENCIL_CLEAN", "EXECUTED",
                        "VERIFIED")], limitations=["Not reviewed"]),
        _h("H10", site="SYNTHETIC_SITE_B", spi="SPI_VOLUME_LOW", aoi="AOI_FAIL_CONFIRMED", incident=d("10-01"),
           available=d("10-15"), summary="Other site precedent.", evidence=[],
           outcomes=[_o("STENCIL_APERTURE_INSPECTION", "Clogging", "VERIFIED", "STENCIL_CLEAN", "EXECUTED",
                        "VERIFIED")], limitations=[]),
        _h("H11", site="SYNTHETIC_SITE_B", sens="CONFIDENTIAL", spi="SPI_VOLUME_LOW", aoi="AOI_FAIL_CONFIRMED",
           incident=d("10-05"), available=d("10-20"), summary="CONFIDENTIAL-MARKER customer escalation.",
           evidence=[], outcomes=[_o("XRAY_CROSS_SECTION", "Voids", "VERIFIED")], limitations=[]),
        _h("H12", spi="SPI_VOLUME_LOW", aoi="AOI_FAIL_CONFIRMED", incident="2026-02-01T00:00:00+00:00",
           available="2026-02-20T00:00:00+00:00", summary="Later incident (future relative to demo case).",
           evidence=[], outcomes=[_o("STENCIL_APERTURE_INSPECTION", "Clogging", "VERIFIED", "STENCIL_CLEAN",
                                    "EXECUTED", "VERIFIED")], limitations=[]),
        _h("H13", process="CONFORMAL_COATING", spi="NORMAL", aoi="AOI_FAIL_CONFIRMED", incident=d("11-01"),
           available=d("11-20"), summary="Coating defect; different process.", evidence=[],
           outcomes=[_o("XRAY_CROSS_SECTION", "Coating voids", "VERIFIED")], limitations=[]),
        _h("H14", spi="SPI_VOLUME_HIGH", aoi="AOI_FALSE_ALARM", incident=d("11-10"), available=d("12-01"),
           summary="High SPI readings, operators judged AOI calls false.",
           evidence=["Operator: FALSE_ALARM"],
           outcomes=[_o("OPERATOR_ADJUDICATION", "False positives", "VERIFIED")],
           limitations=["No action taken; no outcome tracked"]),
    ]


def ensure_bank(session: Session) -> None:
    if session.scalar(select(HistoricalCase.id).limit(1)):
        return
    for h in bank():
        row = {k: h[k] for k in ("historical_case_id", "snapshot_version", "family", "site", "source_origin",
                                 "sensitivity", "review_status", "process_stage", "measurement_pattern",
                                 "aoi_pattern", "incident_at", "available_at", "summary", "limitations",
                                 "superseded_by")}
        hc = HistoricalCase(**row, bank_version=BANK_VERSION,
                            source_version_hash=hashlib.sha256(json.dumps(h, sort_keys=True).encode()).hexdigest())
        session.add(hc)
        session.flush()
        session.add_all(HistoricalEvidence(historical_case_id=hc.id, ref_id=f"{h['historical_case_id']}-E{i}",
                                           description=e) for i, e in enumerate(h["evidence"], 1))
        session.add_all(HistoricalOutcome(historical_case_id=hc.id, **o) for o in h["outcomes"])
    session.flush()


@dataclass
class Profile:
    """What the current case shows, per board, with the evidence ids behind each statement."""

    as_of: str
    site: str = CASE_SITE
    process_stage: str = PROCESS
    boards: dict = field(default_factory=dict)  # "P/B" -> {"spi": pattern, "aoi": pattern, "evidence": [...]}

    def pairs(self) -> set[tuple[str, str]]:
        return {(b["spi"], b["aoi"]) for b in self.boards.values() if b["aoi"] != "AOI_PASS"}


def spi_pattern(features: dict) -> str:
    if features["vol_std"] > 0.02:
        return "SPI_VOLUME_SCATTER"
    if features["vol_mean"] < NOMINAL - 0.012 or features["vol_min"] < SPEC[0]:
        return "SPI_VOLUME_LOW"
    if features["vol_mean"] > NOMINAL + 0.012 or features["vol_max"] > SPEC[1]:
        return "SPI_VOLUME_HIGH"
    return "NORMAL"


def case_profile(session: Session, case_id: str) -> Profile:
    items = _evidence(session, case_id)
    as_of = max(session.scalars(select(SourceEvent.ingested_at).where(SourceEvent.case_id == case_id)))
    prof = Profile(as_of=as_of)
    spi = latest_spi_by_board(items)
    aoi: dict[tuple, list[dict]] = {}
    human = {}
    for i in items:
        if i["type"] == "aoi_inspections":
            aoi.setdefault(tuple(i["key"][:2]), []).append(i)
        if i["type"] == "human_verifications":
            human[(*i["key"][:2], i["rec"]["inspection_id"])] = i
    boards = {tuple(i["key"][:2]) for i in items if i["type"] == "boards"}
    for key in sorted(boards):
        ev = [i["ev"] for i in spi.get(key, [])]
        pattern = spi_pattern(board_features([("spi_measurements", i["rec"]) for i in spi[key]])) if key in spi else "NO_SPI"
        fails = [a for a in aoi.get(key, []) if a["rec"]["result"] == "FAIL"]
        if key not in aoi:
            state = "AOI_MISSING"
        elif not fails:
            state = "AOI_PASS"
        else:
            verdicts = [human.get((*key, a["rec"]["inspection_id"])) for a in fails]
            ev += [a["ev"] for a in fails] + [v["ev"] for v in verdicts if v]
            results = {v["rec"]["result"] for v in verdicts if v}
            state = ("AOI_FAIL_UNVERIFIED" if None in verdicts else
                     "AOI_FAIL_CONFIRMED" if "DEFECT_CONFIRMED" in results else "AOI_FALSE_ALARM")
        prof.boards["/".join(key)] = {"spi": pattern, "aoi": state, "evidence": ev}
    return prof


def retrieve(session: Session, profile: Profile, k: int = 5) -> dict:
    """Eligible, ranked precedents plus counts of what was excluded and why (no excluded details)."""
    ensure_bank(session)
    excluded: dict[str, int] = {}
    ranked = []
    for h in session.scalars(select(HistoricalCase).order_by(HistoricalCase.id)):
        reason = eligibility(h, profile)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        why = [f"{h.measurement_pattern} + {h.aoi_pattern} matches board {b}" for b, v in profile.boards.items()
               if (v["spi"], v["aoi"]) == (h.measurement_pattern, h.aoi_pattern)]
        partial = [f"{h.aoi_pattern} matches board {b} (SPI pattern differs)" for b, v in profile.boards.items()
                   if v["aoi"] == h.aoi_pattern and v["spi"] != h.measurement_pattern]
        score = 2 * len(why) + len(partial)
        if score:
            ranked.append((score, h, why + partial))
    ranked.sort(key=lambda t: (-t[0], t[1].historical_case_id))
    precedents = [precedent_out(session, h, score, why) for score, h, why in ranked[:k]]
    return {"as_of": profile.as_of, "bank_version": BANK_VERSION, "precedents": precedents,
            "status": "OK" if precedents else "NO_RELEVANT_PRECEDENT", "excluded": excluded,
            "note": "Similarity ranks retrieval candidates; it is not causal evidence for this case."}


def eligibility(h: HistoricalCase, profile: Profile) -> str | None:
    if (h.source_origin, h.sensitivity) != APPROVED:
        return "NOT_APPROVED_FOR_EXTERNAL"
    if h.site != profile.site:
        return "CROSS_SITE"
    if h.review_status != "APPROVED" or h.superseded_by:
        return "NOT_APPROVED_OR_SUPERSEDED"
    if h.available_at > profile.as_of:
        return "NOT_YET_AVAILABLE"
    if h.process_stage != profile.process_stage:
        return "PROCESS_MISMATCH"
    return None


def precedent_out(session: Session, h: HistoricalCase, score: int | None = None, why: list | None = None) -> dict:
    outcomes = session.scalars(select(HistoricalOutcome).where(HistoricalOutcome.historical_case_id == h.id)).all()
    ev = session.scalars(select(HistoricalEvidence).where(HistoricalEvidence.historical_case_id == h.id)).all()
    return {
        "historical_case_id": h.historical_case_id, "snapshot_version": h.snapshot_version,
        "source_version_hash": h.source_version_hash, "score": score, "why_similar": why or [],
        "pattern": [h.measurement_pattern, h.aoi_pattern], "summary": h.summary, "available_at": h.available_at,
        "evidence_refs": [e.ref_id for e in ev], "limitations": h.limitations,
        "outcomes": [{"check": o.check, "check_result": o.check_result, "check_status": o.check_status,
                      "action": o.action, "action_status": o.action_status, "outcome_status": o.outcome_status,
                      "metric": o.metric, "before": o.before, "after": o.after, "sample_count": o.sample_count}
                     for o in outcomes],
        "negative_precedent": any(o.outcome_status in ("FAILED", "INSUFFICIENT") for o in outcomes),
    }


def plan_next_evidence(profile: Profile, history: dict | None) -> dict:
    """Deterministic planner. history=None is History OFF. Proposes checks, never fixes."""
    known, unknown, hypotheses, checks, warnings = [], [], [], [], []

    def add(code, reason, evidence, precedents=(), discriminates=()):
        if any(c["check"] == code for c in checks):
            return
        who, what = CHECKS[code]
        checks.append({"check": code, "who": who, "what": what, "reason": reason, "evidence_ids": list(evidence),
                       "precedent_ids": list(precedents), "discriminates": list(discriminates)})

    for board, b in profile.boards.items():
        if b["aoi"] == "AOI_MISSING":
            unknown.append({"text": f"No AOI record for {board}; absence is not a PASS.", "evidence_ids": b["evidence"]})
            add("AOI_RERUN", f"{board} has no AOI record", b["evidence"])
        elif b["aoi"] == "AOI_FAIL_UNVERIFIED":
            unknown.append({"text": f"AOI FAIL on {board} has no operator verdict.", "evidence_ids": b["evidence"]})
            add("OPERATOR_ADJUDICATION", f"AOI FAIL on {board} is unadjudicated", b["evidence"],
                discriminates=["real defect", "AOI false call"])
        elif b["aoi"] in ("AOI_FAIL_CONFIRMED", "AOI_FALSE_ALARM"):
            known.append({"text": f"{board}: {b['aoi']}, SPI pattern {b['spi']}.", "evidence_ids": b["evidence"]})
        if b["aoi"] == "AOI_FAIL_CONFIRMED":
            cand = {"SPI_VOLUME_LOW": "paste deposit shortfall (stencil/print)",
                    "SPI_VOLUME_HIGH": "excess paste deposit (stencil/print)",
                    "SPI_VOLUME_SCATTER": "SPI measurement drift or unstable print",
                    "NORMAL": "placement or reflow (SPI looked normal)"}.get(b["spi"], "undetermined")
            hypotheses.append({"text": f"{board}: candidate {cand}; not verified.", "evidence_ids": b["evidence"]})
    if history:
        for p in history["precedents"]:
            if (tuple(p["pattern"]) not in profile.pairs()):
                continue  # partial matches are shown, but do not drive a check (negative-transfer guard)
            boards = [b for b, v in profile.boards.items() if (v["spi"], v["aoi"]) == tuple(p["pattern"])]
            ev = [e for b in boards for e in profile.boards[b]["evidence"]]
            for o in p["outcomes"]:
                done = o["check"] == "OPERATOR_ADJUDICATION" and all(
                    profile.boards[b]["aoi"] in ("AOI_FAIL_CONFIRMED", "AOI_FALSE_ALARM") for b in boards)
                if done:  # the precedent's discriminating check already has an answer here
                    known.append({"text": f"{p['historical_case_id']}'s verified check ({o['check']}) is already "
                                  f"answered for {', '.join(boards)}.", "evidence_ids": ev})
                elif o["check_status"] == "VERIFIED" and o["check"] in CHECKS:
                    add(o["check"], f"In {p['historical_case_id']} this check gave a verified finding "
                        f"({o['check_result']}) for the same pattern", ev, [p["historical_case_id"]])
                if o["action"] and o["outcome_status"] in ("FAILED", "INSUFFICIENT"):
                    warnings.append({"text": f"{p['historical_case_id']}: {o['action']} was executed and its "
                                     f"outcome was {o['outcome_status']}; do not adopt it as a proven fix.",
                                     "precedent_ids": [p["historical_case_id"]]})
                if o["action"] and o["outcome_status"] == "UNKNOWN":
                    warnings.append({"text": f"{p['historical_case_id']}: outcome of {o['action']} is UNKNOWN; "
                                     "not ranked as a success.", "precedent_ids": [p["historical_case_id"]]})
    for board, b in profile.boards.items():
        if b["aoi"] == "AOI_FAIL_CONFIRMED":
            add("XRAY_CROSS_SECTION", f"{board} has a confirmed defect; physical analysis discriminates causes",
                b["evidence"], discriminates=[h["text"] for h in hypotheses if h["text"].startswith(board)])
    if not checks:
        unknown.append({"text": "No discriminating check identified from current evidence.", "evidence_ids": []})
    return {"history": "ON" if history else "OFF", "known": known, "unknown": unknown, "hypotheses": hypotheses,
            "next_checks": checks, "warnings": warnings,
            "precedents_used": sorted({pid for c in checks for pid in c["precedent_ids"]}),
            "note": "Checks are evidence requests, not authorized actions. No root cause is established."}


def failed_actions(precedents: list[dict]) -> dict[str, str]:
    """{action_code: precedent id} for executed actions whose outcome was FAILED or INSUFFICIENT."""
    return {o["action"]: p["historical_case_id"] for p in precedents for o in p["outcomes"]
            if o["action"] and o["outcome_status"] in ("FAILED", "INSUFFICIENT")}


def recommends_failed_action(text: str, precedents: list[dict]) -> str | None:
    low = text.lower()
    if any(n in low for n in NEGATION):
        return None
    for action, pid in failed_actions(precedents).items():
        if ACTION_TERMS.get(action, action.lower()) in low:
            return f"{action} ({pid})"
    return None

