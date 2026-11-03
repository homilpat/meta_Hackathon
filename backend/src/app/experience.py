"""Experience Memory: verified prior responses for the same or a similar problem (G8, FR-26A..H).

Entries are a versioned, append-only projection over records that already exist: the S5 historical bank (via its
own eligibility rules), a few SYNTHETIC experience fixtures with follow-up/recurrence data, and cases closed in this
system (D4 confirmed causes, D5 actions, D6 results). Retrieval filters scope and access FIRST (site, process,
ACL, availability, ACTIVE), then ranks by BM25 over the natural-language text, then by verified outcome and
matched structured factors. No similarity percentage is produced and nothing is learned into a model.

Modes: KNOWN = a verified-effective, non-recurrent prior response whose applicability conditions all hold now;
ANALOGICAL = similar symptoms/conditions, shown with differences and with failed/recurrent precedents;
NO_RELEVANT_HISTORY = nothing relevant, no historical remedy offered (the ordinary D0-D8 investigation goes on).
A recommendation is never a cause confirmation, a D5 approval or an execution; a person decides what to do with it.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import actions, causes, history, ncr, retrieval
from app.db import (
    Action,
    EffectivenessResult,
    ExperienceEntry,
    ExperienceRetrieval,
    HistoricalCase,
    HistoricalOutcome,
    ProcessContext,
    RecommendationDecision,
)
from app.fields import FreeText
from app.workflow import Actor, log, require_case

METHOD = f"experience-1 prefilter>bm25({retrieval.VERSION})>verified-outcome>factors"
SITE = {history.CASE_SITE: "SITE-A", "SYNTHETIC_SITE_B": "SITE-B"}  # bank naming -> process-context naming
PROCESS = {history.PROCESS: "PCB_SMT"}
POSITIVE = "VERIFIED_EFFECTIVE"
NEGATIVE = ("FAILED", "INSUFFICIENT", "INCONCLUSIVE")
BANK_OUTCOME = {"VERIFIED": POSITIVE, "FAILED": "FAILED", "INSUFFICIENT": "INSUFFICIENT", "UNKNOWN": "UNKNOWN"}
BANK_APPLICABILITY = {  # what a bank action presupposes, in structured factors the current case can be checked on
    "STENCIL_CLEAN": [("spi_pattern", "SPI_VOLUME_LOW")], "STENCIL_REPLACE": [("spi_pattern", "SPI_VOLUME_HIGH")],
    "PRINTER_PRESSURE_ADJUST": [("aoi_pattern", "AOI_FALSE_ALARM")],
    "SPI_RECALIBRATION": [("spi_pattern", "SPI_VOLUME_SCATTER")],
    "AOI_THRESHOLD_TUNE": [("aoi_pattern", "AOI_FALSE_ALARM")],
    "REFLOW_PROFILE_CHANGE": [("spi_pattern", "SPI_VOLUME_SCATTER")]}
LOW_STENCIL = "Paste volume drifted low panel by panel within one lot; insufficient-solder defects confirmed by " \
              "operators late in the lot; the stencil cleaning interval was exceeded in the equipment log."
# SYNTHETIC experience fixtures with follow-up data the S5 bank does not carry (recurrence, conditions).
FIXTURES = [
    {"key": "EXP:X01", "site": "SITE-A", "acl": ["*"], "symptom": LOW_STENCIL,
     "features": {"spi_pattern": "SPI_VOLUME_LOW", "aoi_pattern": "AOI_FAIL_CONFIRMED",
                  "equipment_conditions": ["CLEANING_INTERVAL_EXCEEDED"]},
     "cause": "Worn stencil run past its cleaning interval (confirmed by a fresh-stencil comparison run)",
     "cause_status": "VERIFIED", "action_code": "STENCIL_REPLACE_AND_INTERVAL",
     "action": "Replace the worn stencil and enforce the cleaning interval with a print counter",
     "outcome": POSITIVE, "outcome_evidence": {"metric": "lot mean SPI volume (mm3)", "before": 0.104,
                                               "after": 0.120, "n": 384, "follow_up_days": 90},
     "recurrence": "NONE", "applicability": [("process_type", "PCB_SMT"), ("spi_pattern", "SPI_VOLUME_LOW"),
                                             ("equipment_condition", "CLEANING_INTERVAL_EXCEEDED")],
     "field_checks": ["Inspect the current stencil apertures for wear before reusing this response",
                      "Confirm the paste lot is within shelf life (not covered by the prior case)"]},
    {"key": "EXP:X02", "site": "SITE-A", "acl": ["*"], "symptom": LOW_STENCIL,
     "features": {"spi_pattern": "SPI_VOLUME_LOW", "aoi_pattern": "AOI_FAIL_CONFIRMED",
                  "equipment_conditions": ["CLEANING_INTERVAL_EXCEEDED"]},
     "cause": "Clogged apertures after the cleaning interval was exceeded", "cause_status": "VERIFIED",
     "action_code": "STENCIL_CLEAN", "action": "Wipe-clean the stencil once without changing the interval",
     "outcome": POSITIVE, "outcome_evidence": {"metric": "lot mean SPI volume (mm3)", "before": 0.106,
                                               "after": 0.118, "n": 192, "follow_up_days": 21},
     "recurrence": "RECURRED", "recurrence_note": "Low volume returned after 3 weeks; the interval was not enforced",
     "applicability": [("process_type", "PCB_SMT"), ("spi_pattern", "SPI_VOLUME_LOW")], "field_checks": []},
    {"key": "EXP:X03", "site": "SITE-A", "acl": ["*"],
     "symptom": "Low paste volume on every board of a lot with insufficient-solder defects; squeegee blade wear "
                "found; stencil within its cleaning interval.",
     "features": {"spi_pattern": "SPI_VOLUME_LOW", "aoi_pattern": "AOI_FAIL_CONFIRMED",
                  "equipment_conditions": ["SQUEEGEE_WEAR"]},
     "cause": "Worn squeegee blade (confirmed by blade swap)", "cause_status": "VERIFIED",
     "action_code": "SQUEEGEE_REPLACE", "action": "Replace the squeegee blade and add it to the PM checklist",
     "outcome": POSITIVE, "outcome_evidence": {"metric": "lot mean SPI volume (mm3)", "before": 0.101,
                                               "after": 0.121, "n": 256, "follow_up_days": 60},
     "recurrence": "NONE", "applicability": [("process_type", "PCB_SMT"), ("spi_pattern", "SPI_VOLUME_LOW"),
                                             ("equipment_condition", "SQUEEGEE_WEAR")], "field_checks": []},
    {"key": "EXP:X04", "site": "SITE-A", "acl": ["PROCESS_ENGINEER"],
     "symptom": "Low paste volume traced to a supplier paste formulation change (supplier-restricted record).",
     "features": {"spi_pattern": "SPI_VOLUME_LOW", "aoi_pattern": "AOI_FAIL_CONFIRMED", "equipment_conditions": []},
     "cause": "Supplier changed flux ratio", "cause_status": "VERIFIED", "action_code": "PASTE_SUPPLIER_CHANGE",
     "action": "Qualify an alternative paste lot", "outcome": POSITIVE,
     "outcome_evidence": {"metric": "lot mean SPI volume (mm3)", "before": 0.103, "after": 0.119, "n": 128},
     "recurrence": "NONE", "applicability": [("process_type", "PCB_SMT"), ("spi_pattern", "SPI_VOLUME_LOW")],
     "field_checks": []},
    {"key": "EXP:X05", "site": "SITE-B", "acl": ["*"], "symptom": LOW_STENCIL,
     "features": {"spi_pattern": "SPI_VOLUME_LOW", "aoi_pattern": "AOI_FAIL_CONFIRMED",
                  "equipment_conditions": ["CLEANING_INTERVAL_EXCEEDED"]},
     "cause": "Worn stencil (SITE-B)", "cause_status": "VERIFIED", "action_code": "STENCIL_REPLACE_AND_INTERVAL",
     "action": "Replace the stencil (SITE-B wet-wipe process)", "outcome": POSITIVE, "outcome_evidence": {},
     "recurrence": "NONE", "applicability": [("process_type", "PCB_SMT")], "field_checks": []},
]
FIXTURE_AT = "2025-12-01T00:00:00+00:00"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _add(session: Session, key: str, source_kind: str, source_ref: str, **f) -> ExperienceEntry:
    prev = latest(session, key)
    body = {"entry_key": key, "source_kind": source_kind, "source_ref": source_ref, **f}
    row = ExperienceEntry(**body, version=(prev.version + 1) if prev else 1, source_sha256=sha(body),
                          indexed_at=now())
    session.add(row)
    session.flush()
    return row


def latest(session: Session, key: str) -> ExperienceEntry | None:
    return session.scalar(select(ExperienceEntry).where(ExperienceEntry.entry_key == key)
                          .order_by(ExperienceEntry.version.desc()).limit(1))


def ensure_entries(session: Session) -> None:
    """Project the S5 bank and the experience fixtures once (idempotent)."""
    if session.scalar(select(ExperienceEntry.id).where(ExperienceEntry.source_kind != "CLOSED_CASE").limit(1)):
        return
    history.ensure_bank(session)
    for h in session.scalars(select(HistoricalCase).order_by(HistoricalCase.id)):
        for o in session.scalars(select(HistoricalOutcome).where(HistoricalOutcome.historical_case_id == h.id)):
            if not o.action:
                continue
            _add(session, f"HIST:{h.historical_case_id}:{o.action}", "HISTORICAL_BANK", h.historical_case_id,
                 status="ACTIVE", site=SITE.get(h.site, h.site), process_type=PROCESS.get(h.process_stage,
                                                                                         h.process_stage),
                 acl_roles=["*"] if h.sensitivity == "APPROVED_FOR_EXTERNAL" else ["NONE"],
                 symptom_text=f"{h.summary} {h.measurement_pattern} {h.aoi_pattern}",
                 features={"spi_pattern": h.measurement_pattern, "aoi_pattern": h.aoi_pattern,
                           "equipment_conditions": []},
                 cause_text=o.check_result, cause_status="VERIFIED" if o.check_status == "VERIFIED" else "UNKNOWN",
                 action_code=o.action, action_text=o.action.replace("_", " ").lower(),
                 outcome=BANK_OUTCOME.get(o.outcome_status, "UNKNOWN"),
                 outcome_evidence={"metric": o.metric, "before": o.before, "after": o.after, "n": o.sample_count},
                 recurrence="UNKNOWN", recurrence_note="the S5 bank does not track recurrence",
                 applicability=[{"key": k, "expected": v} for k, v in
                                [("process_type", "PCB_SMT"), *BANK_APPLICABILITY.get(o.action, [])]],
                 field_checks=list(h.limitations), available_at=h.available_at,
                 bank_eligibility=history.eligibility(h, history.Profile(as_of="9999")) or "OK", reason="")
    for x in FIXTURES:
        _add(session, x["key"], "EXPERIENCE_FIXTURE", x["key"].split(":")[1], status="ACTIVE", site=x["site"],
             process_type="PCB_SMT", acl_roles=x["acl"], symptom_text=x["symptom"], features=x["features"],
             cause_text=x["cause"], cause_status=x["cause_status"], action_code=x["action_code"],
             action_text=x["action"], outcome=x["outcome"], outcome_evidence=x["outcome_evidence"],
             recurrence=x["recurrence"], recurrence_note=x.get("recurrence_note", ""),
             applicability=[{"key": k, "expected": v} for k, v in x["applicability"]],
             field_checks=x["field_checks"], available_at=FIXTURE_AT, bank_eligibility="OK", reason="")


def active_entries(session: Session) -> list[ExperienceEntry]:
    ensure_entries(session)
    rows = session.scalars(select(ExperienceEntry).order_by(ExperienceEntry.id)).all()
    last = {}
    for r in rows:
        last[r.entry_key] = r
    return list(last.values())


# --- the current case ----------------------------------------------------------------------------------

def case_features(session: Session, case_id: str) -> dict:
    pc = session.scalar(select(ProcessContext).where(ProcessContext.case_id == case_id))
    if pc is None:
        raise HTTPException(409, "record the process context first; experience retrieval is scoped by site/process")
    prof = history.case_profile(session, case_id)
    items = ncr.current(ncr._evidence(session, case_id))
    pairs = prof.pairs()
    eq = sorted({i["rec"]["status"] for i in items if i["type"] == "equipment_events"})
    what = ncr.problem_definition(items)["what"]
    conf = [h.text for h in causes.confirmed(session, case_id)]
    text = " ".join([f"{a} {b}" for a, b in sorted(pairs)] + eq + conf +
                     [str(what.get("value") or ""), "paste volume low insufficient solder" if any(
                         a == "SPI_VOLUME_LOW" for a, _ in pairs) else ""])
    return {"site": pc.site, "process_type": pc.process_type, "as_of": prof.as_of,
            "spi_patterns": sorted({a for a, _ in pairs}), "aoi_patterns": sorted({b for _, b in pairs}),
            "equipment_conditions": eq, "has_equipment_evidence": any(i["type"] == "equipment_events" for i in items),
            "confirmed_causes": conf, "text": text}


def check(entry: ExperienceEntry, cur: dict) -> list[dict]:
    out = []
    for a in entry.applicability:
        k, want = a["key"], a["expected"]
        if k == "process_type":
            st, now_ = ("PASS" if cur["process_type"] == want else "FAIL"), cur["process_type"]
        elif k == "spi_pattern":
            st, now_ = ("PASS" if want in cur["spi_patterns"] else "FAIL"), cur["spi_patterns"]
        elif k == "aoi_pattern":
            st, now_ = ("PASS" if want in cur["aoi_patterns"] else "FAIL"), cur["aoi_patterns"]
        elif k == "equipment_condition":
            now_ = cur["equipment_conditions"]
            st = "PASS" if want in now_ else ("FAIL" if cur["has_equipment_evidence"] else "UNKNOWN")
        else:
            st, now_ = "UNKNOWN", None
        out.append({"check": k, "prior": want, "current": now_, "status": st})
    return out


def _scope(e: ExperienceEntry, cur: dict, role: str) -> str | None:
    if e.status != "ACTIVE":
        return "REVOKED"
    if "*" not in e.acl_roles and role not in e.acl_roles:
        return "ACCESS"
    if e.bank_eligibility != "OK" and e.bank_eligibility != "NOT_YET_AVAILABLE":
        return e.bank_eligibility
    if e.site != cur["site"]:
        return "OTHER_SITE"
    if e.process_type != cur["process_type"]:
        return "OTHER_PROCESS"
    # bank/fixture records replay against the case's data timeline; a case closed here is known at retrieval time
    if e.available_at > (now() if e.source_kind == "CLOSED_CASE" else cur["as_of"]):
        return "NOT_YET_AVAILABLE"
    return None


def retrieve(session: Session, case_id: str, role: str, q: str = "", k: int = 6, include: frozenset = frozenset(),
             with_misses: bool = False) -> dict:
    """Deterministic retrieval; the same call backs the UI, the API and the model's read-only tool. include: entry
    keys the AI judged to describe the same problem although they share no word with the query (they still pass
    scope, access and the factor gate, and the mode comes from their records). with_misses: also return the entries
    that passed scope and the factor gate but shared no word ("_text_missed"), for the AI to read."""
    cur = case_features(session, case_id)
    rejected: dict[str, int] = {}
    cands = []
    for e in active_entries(session):
        if e.source_kind == "CLOSED_CASE" and e.source_ref.split("#")[0] == case_id:
            continue  # a case is not its own precedent
        if why := _scope(e, cur, role):
            rejected[why] = rejected.get(why, 0) + 1
        else:
            cands.append(e)
    query = f"{q} {cur['text']}".strip()
    misses: list[dict] = []
    scores = retrieval.bm25(query, [f"{e.symptom_text} {e.cause_text} {e.action_text}" for e in cands])
    matches = []
    for (score, terms), e in zip(scores, cands, strict=True):
        f = e.features
        matched = [k for k, v in (("spi_pattern", f.get("spi_pattern") in cur["spi_patterns"]),
                                  ("aoi_pattern", f.get("aoi_pattern") in cur["aoi_patterns"]),
                                  ("equipment_condition", bool(set(f.get("equipment_conditions") or [])
                                                                & set(cur["equipment_conditions"])))) if v]
        if not ({"spi_pattern", "equipment_condition"} & set(matched)):  # AOI FAIL alone is generic
            rejected["NOT_SIMILAR"] = rejected.get("NOT_SIMILAR", 0) + 1
            continue
        if score <= 0 and e.entry_key not in include:  # the same conditions in other words: the AI may read these
            rejected["NO_SHARED_WORD"] = rejected.get("NO_SHARED_WORD", 0) + 1
            misses.append({"entry_key": e.entry_key, "symptom": e.symptom_text, "cause": e.cause_text,
                           "action": e.action_text})
            continue
        checks = check(e, cur)
        recurrent = e.recurrence == "RECURRED"
        known = (e.outcome == POSITIVE and e.recurrence == "NONE" and e.cause_status == "VERIFIED"
                 and all(c["status"] == "PASS" for c in checks))
        role_ = ("NEGATIVE_PRECEDENT" if e.outcome in NEGATIVE or recurrent else
                 "UNKNOWN_EFFECT" if e.outcome != POSITIVE else "PRIOR_RESPONSE")
        warnings = []
        if e.outcome in NEGATIVE:
            warnings.append(f"{e.action_text}: outcome {e.outcome}; not a proven solution")
        if recurrent:
            warnings.append(f"{e.action_text}: problem recurred ({e.recurrence_note}); do not reuse as is")
        if e.outcome == "UNKNOWN":
            warnings.append(f"{e.action_text}: effect never verified; not ranked as a success")
        if e.outcome == POSITIVE and e.recurrence == "NOT_YET_OBSERVED":
            warnings.append(f"{e.action_text}: effect verified at D6, recurrence not yet observed; "
                            "an effect-verified reference case, not a known fix")
        level = ("NEGATIVE" if role_ == "NEGATIVE_PRECEDENT" else "UNVERIFIED_EFFECT" if e.outcome != POSITIVE else
                 "VERIFIED_NO_RECURRENCE" if e.recurrence == "NONE" else
                 "EFFECT_VERIFIED_REFERENCE" if e.recurrence == "NOT_YET_OBSERVED" else "EFFECT_VERIFIED_RECURRENCE_UNKNOWN")
        differing = [c for c in checks if c["status"] != "PASS"]
        matches.append({
            "entry_key": e.entry_key, "version": e.version, "source_kind": e.source_kind, "source_ref": e.source_ref,
            "source_sha256": e.source_sha256, "mode": "KNOWN" if known else "ANALOGICAL", "role": role_,
            "evidence_level": level,
            "symptom": e.symptom_text, "cause": e.cause_text, "cause_status": e.cause_status,
            "action_code": e.action_code, "action": e.action_text, "outcome": e.outcome,
            "outcome_evidence": e.outcome_evidence, "recurrence": e.recurrence, "matched_factors": matched,
            "matched_terms": terms, "bm25": score, "applicability_checks": checks,
            "differing_factors": [f"{c['check']}: prior {c['prior']}, now {c['current']} ({c['status']})"
                                  for c in differing],
            "field_checks": e.field_checks, "warnings": warnings, "requires_revalidation": not known})
    matches.sort(key=lambda m: (m["mode"] != "KNOWN", m["role"] != "PRIOR_RESPONSE", -len(m["matched_factors"]),
                                -m["bm25"], m["entry_key"]))
    neg = [m for m in matches if m["role"] == "NEGATIVE_PRECEDENT"][:5]  # warnings are never cut by the top-k
    matches = [m for m in matches if m["role"] != "NEGATIVE_PRECEDENT"][:k] + neg
    recs = [m for m in matches if m["role"] == "PRIOR_RESPONSE"]
    mode = ("KNOWN" if any(m["mode"] == "KNOWN" for m in matches) else
            "ANALOGICAL" if matches else "NO_RELEVANT_HISTORY")
    top = recs[0] if recs else None
    prompt = None
    if top:
        diff = "; ".join(top["differing_factors"]) or "none of the checked conditions"
        prompt = (f"A similar prior issue was found ({top['source_ref']}); the verified prior response was "
                  f"\"{top['action']}\". Current conditions differ at: {diff}. Review this approach first?")
    return {"mode": mode, "query": query, "method": METHOD, "case_features": {k: v for k, v in cur.items()
                                                                              if k != "text"},
            "recommendations": recs, "negative_precedents": [m for m in matches if m["role"] == "NEGATIVE_PRECEDENT"],
            "unknown_effect": [m for m in matches if m["role"] == "UNKNOWN_EFFECT"], "matches": matches,
            "rejected": rejected, "prompt": prompt,
            "choices": ["REVIEW_PRIOR_RESPONSE", "INVESTIGATE_MORE", "CONSIDER_ALTERNATIVE"] if matches else [],
            "note": ("No relevant history: no historical remedy is offered; continue the evidence-based D0-D8 "
                     "investigation." if mode == "NO_RELEVANT_HISTORY" else
                     "Similarity is not causal proof; a prior response is reviewed, then D4/D5/D6 gates still apply."),
            "data_origin": "SYNTHETIC", **({"_text_missed": misses} if with_misses else {})}


# --- the AI's part (user decision 2026-11-03): wider search terms and a comparison the records check ----------
# The server keeps scope, access, the factor gate and the mode. The model sees the case's structured factors and
# the candidates' texts, never other cases' evidence ids; what it says about a condition is compared with the
# server's own check of that condition, and a disagreement is shown, not followed.
MAX_MISSES = 20  # DEFAULT: candidates the AI reads per retrieval (each passed scope, access and the factor gate)
PICK_PROMPT = """The server found earlier quality cases whose structured conditions match the current case but whose
text shares no word with it (other languages or shop-floor wording). Read each and list only those that describe
the same problem as the current case, with a one-sentence reason. Leave out any you are not sure about."""


def pick_schema(misses: list[dict]) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "experience_pick", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["same_problem"],
        "properties": {"same_problem": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["entry_key", "reason"],
            "properties": {"entry_key": {"type": "string", "enum": [m["entry_key"] for m in misses]},
                           "reason": {"type": "string"}}}}}}}}


REVIEW_PROMPT = """Compare the current quality case with each earlier case found by the server. For each, list which
of its listed conditions hold now and which differ, using only the condition names given, and say whether the
earlier response looks directly reusable (KNOWN) or only similar (ANALOGICAL), with a one-sentence note. The server
decides with its own records; you only compare."""


def review_schema(matches: list[dict]) -> dict:
    keys = sorted({c["check"] for m in matches for c in m["applicability_checks"]}) or ["none"]
    return {"type": "json_schema", "json_schema": {"name": "experience_review", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["cases"],
        "properties": {"cases": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["entry_key", "same", "different", "proposed_mode", "note"],
            "properties": {"entry_key": {"type": "string", "enum": [m["entry_key"] for m in matches] or ["none"]},
                           "same": {"type": "array", "items": {"type": "string", "enum": keys}},
                           "different": {"type": "array", "items": {"type": "string", "enum": keys}},
                           "proposed_mode": {"type": "string", "enum": ["KNOWN", "ANALOGICAL"]},
                           "note": {"type": "string"}}}}}}}}


def _ask(provider, prompt: str, payload: dict, schema: dict, protected: bool, masker):
    from app.egress import MASK_NOTE

    r = provider.chat([{"role": "system", "content": prompt + ("\n" + MASK_NOTE if protected else "")},
                       {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}], [],
                      response_format=schema)
    return masker.unmask_obj(json.loads(r["message"].get("content") or "")), r.get("usage") or {}


def ai_retrieve(session: Session, case_id: str, role: str, q: str, provider) -> dict:
    """1. the AI reads the entries that match the case's conditions but share no word with it, and picks those that
    describe the same problem (server ids only); 2. the server retrieves again with them, records deciding each
    mode; 3. the AI compares each match, and the server checks that comparison against its own conditions.
    Never raises for model problems; the rule result stands."""
    from app.db import QualityCase
    from app.egress import Masker
    from app.inspection_layout import header_terms, languages, mask_header
    from app.model_provider import ProviderError

    base = retrieve(session, case_id, role, q, with_misses=True)
    misses = base.pop("_text_missed")[:MAX_MISSES]
    info = {"mode": provider.mode if provider else "OFFLINE", "model": getattr(provider, "model", None),
            "read": [m["entry_key"] for m in misses], "picked": [], "reasons": {}, "review": None, "usage": [],
            "status": "OFFLINE"}
    if provider is None:
        return {**base, "ai": info}
    protected = session.get(QualityCase, case_id).data_origin != "SYNTHETIC"
    masker = Masker()
    cur = base["case_features"]
    terms_ok = header_terms(languages([q, *cur["confirmed_causes"], *(m["symptom"] for m in misses)]))

    def m(t):
        return mask_header(t, terms_ok, masker) if protected else t
    current = {"problem": m(q), **{k: cur[k] for k in ("spi_patterns", "aoi_patterns", "equipment_conditions",
                                                       "process_type")},
               "confirmed_causes": [m(t) for t in cur["confirmed_causes"]]}
    out = base
    if misses:
        try:
            reply, usage = _ask(provider, PICK_PROMPT, {"current": current, "earlier": [
                {"entry_key": x["entry_key"], "symptom": m(x["symptom"]), "cause": m(x["cause"]),
                 "action": m(x["action"])} for x in misses]}, pick_schema(misses), protected, masker)
            info["usage"].append(usage)
            known = {x["entry_key"] for x in misses}
            picked = [r for r in reply.get("same_problem") or [] if isinstance(r, dict) and r.get("entry_key") in known]
            info.update(picked=[r["entry_key"] for r in picked], status="OK",
                        reasons={r["entry_key"]: str(r.get("reason", ""))[:300] for r in picked})
        except (ProviderError, ValueError, KeyError, TypeError) as exc:
            info.update(status="FAILED", error=type(exc).__name__)
            return {**base, "ai": info}
        out = retrieve(session, case_id, role, q, include=frozenset(info["picked"]))
    else:
        info["status"] = "OK"
    for x in out["matches"]:
        x["found_by"] = "AI_MATCH" if x["entry_key"] in info["picked"] else "RULES"
        if x["found_by"] == "AI_MATCH":
            x["ai_reason"] = info["reasons"][x["entry_key"]]
    if out["matches"]:
        cands = [{"entry_key": x["entry_key"], "symptom": m(x["symptom"]), "cause": m(x["cause"]),
                  "action": m(x["action"]), "conditions": [{"check": c["check"], "prior": c["prior"]}
                                                           for c in x["applicability_checks"]]}
                 for x in out["matches"]]
        try:
            reply, usage = _ask(provider, REVIEW_PROMPT, {"current": current, "earlier": cands},
                                review_schema(out["matches"]), protected, masker)
            info["usage"].append(usage)
            info["review"] = check_review(out["matches"], reply)
        except (ProviderError, ValueError, KeyError, TypeError) as exc:
            info["review"] = {"status": "FAILED", "error": type(exc).__name__}
    return {**out, "ai": info}


def check_review(matches: list[dict], reply: dict) -> dict:
    """The AI's comparison against the server's own checks: kept per match, disagreements named, mode untouched."""
    by = {x["entry_key"]: x for x in matches}
    dropped = 0
    for r in (reply.get("cases") if isinstance(reply, dict) else None) or []:
        x = by.get(r.get("entry_key")) if isinstance(r, dict) else None
        if x is None:
            dropped += 1
            continue
        status = {c["check"]: c["status"] for c in x["applicability_checks"]}
        same = [c for c in r.get("same") or [] if c in status]
        diff = [c for c in r.get("different") or [] if c in status]
        disagree = [f"{c}: AI 같음, 기록 {status[c]}" for c in same if status[c] != "PASS"] + \
                   [f"{c}: AI 다름, 기록 PASS" for c in diff if status[c] == "PASS"]
        if r.get("proposed_mode") == "KNOWN" and x["mode"] != "KNOWN":
            disagree.append("AI는 KNOWN을 제안했지만 기록(효과·재발·적용 조건)상 ANALOGICAL입니다")
        x["ai_review"] = {"same": same, "different": diff, "proposed_mode": r.get("proposed_mode"),
                          "note": str(r.get("note", ""))[:300], "server_mode": x["mode"], "disagreements": disagree}
    return {"status": "OK", "reviewed": sum("ai_review" in x for x in matches), "dropped": dropped,
            "disagreements": sum(len(x.get("ai_review", {}).get("disagreements", [])) for x in matches)}


# --- accumulation -------------------------------------------------------------------------------------

OUTCOME_OF = {"EFFECTIVE": POSITIVE, "NOT_EFFECTIVE": "FAILED", "INCONCLUSIVE": "INCONCLUSIVE"}


def index_case(session: Session, case_id: str, closure_id: int) -> list[str]:
    """After D8 CLOSED: one entry per D5 action with its verified D6 outcome. Recurrence is not yet observable."""
    cur = case_features(session, case_id)
    causes_ = causes.confirmed(session, case_id)
    keys = []
    for a in session.scalars(select(Action).where(Action.case_id == case_id, Action.stage == "D5")
                             .order_by(Action.id)):
        res = session.scalar(select(EffectivenessResult).where(EffectivenessResult.action_id == a.id)
                             .order_by(EffectivenessResult.id.desc()).limit(1))
        outcome = OUTCOME_OF.get(res.decision, "UNKNOWN") if res else "UNKNOWN"
        named = [h.text for h in causes_ if h.id in a.cause_ids]
        key = f"CASE:{case_id}:A{a.id}"
        _add(session, key, "CLOSED_CASE", f"{case_id}#closure{closure_id}", status="ACTIVE", site=cur["site"],
             process_type=cur["process_type"], acl_roles=["*"],
             symptom_text=f"{' '.join(cur['spi_patterns'])} {' '.join(cur['aoi_patterns'])} "
                          f"{' '.join(cur['equipment_conditions'])} {' '.join(named)}",
             features={"spi_pattern": (cur["spi_patterns"] or [None])[0],
                       "aoi_pattern": (cur["aoi_patterns"] or [None])[0],
                       "equipment_conditions": cur["equipment_conditions"]},
             cause_text="; ".join(named) or "no confirmed cause", cause_status="VERIFIED" if named else "UNKNOWN",
             action_code=a.action_type, action_text=a.description, outcome=outcome,
             outcome_evidence={"effectiveness_result": res.id if res else None,
                               "observed": res.observed if res else None, "action_status": actions.status(session,
                                                                                                         a.id)},
             recurrence="NOT_YET_OBSERVED", recurrence_note="closed in this system; no follow-up window yet",
             applicability=[{"key": "process_type", "expected": cur["process_type"]},
                            *({"key": "spi_pattern", "expected": p} for p in cur["spi_patterns"][:1]),
                            *({"key": "equipment_condition", "expected": c} for c in cur["equipment_conditions"])],
             field_checks=[], available_at=now(), bank_eligibility="OK", reason="")
        keys.append(key)
    return keys


def revoke(session: Session, key: str, reason: str) -> ExperienceEntry:
    e = latest(session, key)
    if e is None:
        raise HTTPException(404, "experience entry not found")
    if e.status == "REVOKED":
        raise HTTPException(409, "already revoked")
    fields = {c.key: getattr(e, c.key) for c in ExperienceEntry.__table__.columns
              if c.key not in ("id", "entry_key", "version", "source_kind", "source_ref", "source_sha256",
                               "indexed_at", "status", "reason")}
    return _add(session, key, e.source_kind, e.source_ref, **fields, status="REVOKED", reason=reason)


def revoke_case(session: Session, case_id: str, reason: str) -> list[str]:
    keys = [e.entry_key for e in active_entries(session)
            if e.source_kind == "CLOSED_CASE" and e.source_ref.split("#")[0] == case_id and e.status == "ACTIVE"]
    for k in keys:
        revoke(session, k, reason)
    return keys


# --- routes -------------------------------------------------------------------------------------------

class RetrieveIn(BaseModel):
    q: str = Field(default="", max_length=500)  # optional free-text wording of the problem
    ai: bool = False  # Meta widens the search terms and compares; the server's records still decide


class DecisionIn(BaseModel):
    retrieval_id: int
    entry_key: str
    decision: Literal["REVIEW_PRIOR_RESPONSE", "INVESTIGATE_MORE", "CONSIDER_ALTERNATIVE"]
    reason: FreeText


class RevokeIn(BaseModel):
    reason: FreeText


def decision_out(session: Session, d: RecommendationDecision) -> dict:
    e = latest(session, d.entry_key)
    stale = e is None or e.status != "ACTIVE" or e.source_sha256 != d.entry_sha256
    return {"decision_id": d.id, "retrieval_id": d.retrieval_id, "entry_key": d.entry_key,
            "entry_version": d.entry_version, "decision": d.decision, "reason": d.reason, "actor_id": d.actor_id,
            "at": d.created_at, "stale": stale,
            "stale_reason": None if not stale else (f"entry is now {e.status} v{e.version}: {e.reason}" if e else
                                                    "entry missing"),
            "note": "A choice, not an approval: D4 verification, D5 selection and D6 effectiveness still apply."}


def retrieval_out(r: ExperienceRetrieval) -> dict:
    return {"retrieval_id": r.id, "actor_id": r.actor_id, "at": r.created_at, "case_snapshot_sha256": r.query_sha256,
            **r.results}


def make_experience_router(sessions: sessionmaker, current_user: Callable[..., Actor], provider=None) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.post("/cases/{case_id}/experience/retrievals", status_code=201)
    def run_retrieval(case_id: str, actor: Who, body: RetrieveIn | None = None) -> dict:
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            b = body or RetrieveIn()
            out = ai_retrieve(session, case_id, actor.role, b.q, provider) if b.ai else \
                retrieve(session, case_id, actor.role, b.q)
            r = ExperienceRetrieval(case_id=case_id, query_text=out["query"], query_sha256=sha(out["case_features"]),
                                    mode=out["mode"], results=out, method_version=METHOD, actor_id=actor.id,
                                    created_at=now())
            session.add(r)
            session.flush()
            log(session, case_id, actor, "EXPERIENCE_RETRIEVED", f"#{r.id} mode={out['mode']} "
                f"recommended={[m['entry_key'] for m in out['recommendations']]} "
                f"negative={[m['entry_key'] for m in out['negative_precedents']]} rejected={out['rejected']}")
            return retrieval_out(r)

    @router.get("/cases/{case_id}/experience")
    def case_experience(case_id: str, actor: Who) -> dict:
        with sessions() as session:
            require_case(session, case_id, actor)
            r = session.scalar(select(ExperienceRetrieval).where(ExperienceRetrieval.case_id == case_id)
                               .order_by(ExperienceRetrieval.id.desc()).limit(1))
            ds = session.scalars(select(RecommendationDecision).where(RecommendationDecision.case_id == case_id)
                                 .order_by(RecommendationDecision.id)).all()
            return {"latest": retrieval_out(r) if r else None, "decisions": [decision_out(session, d) for d in ds]}

    @router.post("/cases/{case_id}/experience/decisions", status_code=201)
    def decide(case_id: str, body: DecisionIn, actor: Who) -> dict:
        if actor.role not in ("AUTHOR", "PROCESS_ENGINEER"):
            raise HTTPException(403, "AUTHOR or PROCESS_ENGINEER role required")
        with sessions.begin() as session:
            require_case(session, case_id, actor)
            r = session.get(ExperienceRetrieval, body.retrieval_id)
            if r is None or r.case_id != case_id:
                raise HTTPException(404, "retrieval not found for this case")
            m = next((x for x in r.results["matches"] if x["entry_key"] == body.entry_key), None)
            if m is None:
                raise HTTPException(422, "entry was not retrieved for this case")
            if body.decision == "REVIEW_PRIOR_RESPONSE" and m["role"] != "PRIOR_RESPONSE":
                raise HTTPException(422, f"{body.entry_key} is a {m['role']}; it cannot be reviewed as a proven "
                                         "prior response (choose INVESTIGATE_MORE or CONSIDER_ALTERNATIVE)")
            e = latest(session, body.entry_key)
            if e is None or e.status != "ACTIVE" or e.source_sha256 != m["source_sha256"]:
                raise HTTPException(409, "the entry changed or was revoked since retrieval; retrieve again")
            d = RecommendationDecision(case_id=case_id, retrieval_id=r.id, entry_key=e.entry_key,
                                       entry_version=e.version, entry_sha256=e.source_sha256,
                                       case_snapshot_sha256=r.query_sha256, decision=body.decision,
                                       reason=body.reason, actor_id=actor.id, created_at=now())
            session.add(d)
            session.flush()
            log(session, case_id, actor, f"EXPERIENCE_{body.decision}",
                f"{e.entry_key} v{e.version} ({m['mode']}, outcome {m['outcome']}) retrieval #{r.id}: {body.reason}")
            out = decision_out(session, d)
            if body.decision == "REVIEW_PRIOR_RESPONSE":  # a starting point to edit, nothing is created
                out["suggested_d5_option"] = {"stage": "D5", "action_type": "OTHER", "description": m["action"],
                                              "details": {"feasibility": "to assess on this line",
                                                          "risk_analysis": "; ".join(m["differing_factors"]) or
                                                          "conditions matched; confirm field checks",
                                                          "side_effects": "to assess"},
                                              "requires": ["a CONFIRMED D4 cause", *m["field_checks"]]}
            return out

    @router.get("/experience/entries")
    def entries(actor: Who) -> list[dict]:
        with sessions.begin() as session:
            return [{"entry_key": e.entry_key, "version": e.version, "status": e.status, "source_kind": e.source_kind,
                     "source_ref": e.source_ref, "site": e.site, "outcome": e.outcome, "recurrence": e.recurrence,
                     "action": e.action_text, "indexed_at": e.indexed_at, "reason": e.reason}
                    for e in active_entries(session) if "*" in e.acl_roles or actor.role in e.acl_roles]

    @router.post("/experience/entries/{key}/revoke", status_code=201)
    def revoke_entry(key: str, body: RevokeIn, actor: Who) -> dict:
        if actor.role != "REVIEWER":
            raise HTTPException(403, "REVIEWER role required")
        with sessions.begin() as session:
            ensure_entries(session)
            e = revoke(session, key, f"{body.reason} (revoked by {actor.id})")
            return {"entry_key": e.entry_key, "version": e.version, "status": e.status, "reason": e.reason,
                    "revoked_by": actor.id}

    return router
