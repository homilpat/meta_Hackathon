"""Experience Memory with the AI reading what words missed, and its comparison (user decision 2026-11-03), against rules alone, on
the synthetic line case L and a fixed set of earlier cases written in other words and languages. Gold is written
below before any run. Run from backend/:

    python -m scripts.experience_eval --double | --live      (LIVE: QO_EVAL_LIVE_BUDGET_USD; 2 calls per run)

Metrics:
- recall: gold relevant cases found (any mode);
- false KNOWN: a case shown as KNOWN that is not gold KNOWN (the server decides; must stay 0);
- negative precedent kept as a warning;
- disagreements: the AI's comparison against the server's own checks.
TEST_DOUBLE results check the pipeline only and are reported apart.
"""

import json
import sys
import tempfile
from pathlib import Path

from scripts import evalkit

COMMON = {"site": "SITE-A", "process_type": "PCB_SMT", "acl_roles": ["*"], "status": "ACTIVE", "bank_eligibility": "OK",
          "available_at": "2025-12-01T00:00:00+00:00", "reason": "", "field_checks": []}
LOW = {"spi_pattern": "SPI_VOLUME_LOW", "aoi_pattern": "AOI_FAIL_CONFIRMED",
       "equipment_conditions": ["CLEANING_INTERVAL_EXCEEDED"]}
APPLIES = [{"key": "process_type", "expected": "PCB_SMT"}, {"key": "spi_pattern", "expected": "SPI_VOLUME_LOW"},
           {"key": "equipment_condition", "expected": "CLEANING_INTERVAL_EXCEEDED"}]
GOOD = {"outcome": "VERIFIED_EFFECTIVE", "recurrence": "NONE", "cause_status": "VERIFIED", "features": LOW,
        "applicability": APPLIES, "outcome_evidence": {"metric": "lot mean SPI volume", "follow_up_days": 60}}
# (key, symptom, cause, action, overrides, gold): gold KNOWN / NEGATIVE / ABSENT (must not appear)
CASES = [  # BM25 overlap with case L's query checked when written: K1, K2, K4, N1 share no term (the glossary
    # misses their wording); K3 and K5 share glossary terms (rules find them)
    ("EVAL:K1", "땜이 덜 묻어나옴", "마스크 구멍이 막힘", "마스크 새것으로 바꿈", {}, "KNOWN"),
    ("EVAL:K2", "ペースト塗布が薄い", "版の目詰まり", "版を新品に交換", {}, "KNOWN"),
    ("EVAL:K3", "锡膏印得偏薄", "网板孔堵塞", "换新网板", {}, "KNOWN"),
    ("EVAL:K4", "Starved joints and skimpy prints", "Plugged mask openings", "Fitted a new mask", {}, "KNOWN"),
    ("EVAL:K5", "솔더 도포량 부족, 스텐실 세척 주기 초과", "스텐실 개구부 막힘", "스텐실 교체", {}, "KNOWN"),
    ("EVAL:N1", "땜이 덜 묻어나옴", "마스크 구멍이 막힘", "한 번 털어내기만 함",
     {"recurrence": "RECURRED", "recurrence_note": "3주 뒤 재발"}, "NEGATIVE"),
    ("EVAL:D1", "땜이 너무 많이 묻어나옴", "마스크 들뜸", "마스크 고정",
     {"features": {"spi_pattern": "SPI_VOLUME_HIGH", "aoi_pattern": "AOI_FAIL_CONFIRMED", "equipment_conditions": []}},
     "ABSENT"),
]


class Double:
    """TEST_DOUBLE: picks every case it is shown except the high-volume one; the comparison calls all the same."""
    mode, model = "TEST_DOUBLE", "scripted"

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        body = json.loads(messages[-1]["content"])
        if "conditions" not in body["earlier"][0]:
            return {"message": {"content": json.dumps({"same_problem": [
                {"entry_key": e["entry_key"], "reason": "same symptom"} for e in body["earlier"]
                if "많이" not in e["symptom"]]})}, "usage": {}}
        return {"message": {"content": json.dumps({"cases": [
            {"entry_key": e["entry_key"], "same": [c["check"] for c in e["conditions"]], "different": [],
             "proposed_mode": "KNOWN", "note": "same symptom"} for e in body["earlier"]]})}, "usage": {}}


def main(args) -> int:
    from sqlalchemy.orm import Session

    from app import experience
    from tests.v5_util import line_client

    if "--double" in args:
        provider = Double()
    else:
        provider, _, why = evalkit.live_gate(args)
        if provider is None:
            print("NOT_RUN:", why)
            return 2
    c = line_client(Path(tempfile.mkdtemp()))
    with Session(c.app_ref.state.engine) as s:
        experience.ensure_entries(s)
        for key, sym, cause, act, over, _ in CASES:
            experience._add(s, key, "EVAL", key, **{**COMMON, **GOOD, "symptom_text": sym, "cause_text": cause,
                                                    "action_code": "EVAL", "action_text": act,
                                                    "recurrence_note": "", **over})
        s.commit()
        rules = experience.retrieve(s, "L", "AUTHOR")
        ai = experience.ai_retrieve(s, "L", "AUTHOR", "", provider)
    gold = {k: g for k, *_, g in CASES}

    def score(out):
        got = {m["entry_key"]: m for m in out["matches"] if m["entry_key"].startswith("EVAL:")}
        return {"found": sorted(got), "recall": sum(k in got for k, g in gold.items() if g != "ABSENT"),
                "relevant": sum(g != "ABSENT" for g in gold.values()),
                "false_known": [k for k, m in got.items() if m["mode"] == "KNOWN" and gold[k] != "KNOWN"],
                "negative_kept": all(got[k]["role"] == "NEGATIVE_PRECEDENT" for k, g in gold.items()
                                     if g == "NEGATIVE" and k in got),
                "absent_leaked": [k for k, g in gold.items() if g == "ABSENT" and k in got],
                "modes": {k: m["mode"] for k, m in got.items()}}
    a = ai["ai"]
    out = {"run_mode": provider.mode, "model": provider.model, "rules_alone": score(rules), "with_ai": score(ai),
           "ai": {"status": a["status"], "read": a["read"], "picked": a["picked"], "reasons": a["reasons"],
                  "review": a["review"]},
           "found_by_ai": sorted(m["entry_key"] for m in ai["matches"] if m.get("found_by") == "AI_MATCH"),
           "disagreements": {m["entry_key"]: m["ai_review"]["disagreements"] for m in ai["matches"]
                             if m.get("ai_review", {}).get("disagreements")},
           "cost_usd": round(sum(evalkit.cost_usd(u) for u in a["usage"]), 4), "gold": gold,
           "run": evalkit.run_info("scripts.experience_eval")}
    path = evalkit.EVAL_DIR / "ev" / f"experience_eval_{provider.mode}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps({k: out[k] for k in ("run_mode", "rules_alone", "with_ai", "found_by_ai", "cost_usd")},
                     ensure_ascii=False))
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
