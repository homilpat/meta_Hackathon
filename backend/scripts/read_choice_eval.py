"""AI_CHOICE (spec v5.14 AI-CFG-03) judged on recorded outcomes: for each CUAD contract read both ways in the
earlier LIVE runs (C = WHOLE, A = HYBRID; heldout and heldout_long), the better method is the one with the higher
recall there (a tie: either is right, and HYBRID is the cheaper). Meta is asked only to choose (one small call per
contract; no extraction is re-run); WHOLE_FIRST's rule is scored on the same contracts. Run from backend/:

    python -m scripts.read_choice_eval --double | --live        (LIVE: QO_EVAL_LIVE_BUDGET_USD)

Not a measure of extraction itself: it reuses the extraction outcomes recorded in docs/evaluations/ev/cuad_*_LIVE.json.
"""

import json
import sys

from app import EVAL_DIR, intake_extract
from scripts import cuad_eval, evalkit

TIE = 0.02  # DEFAULT: recall differences within 2 points count as a tie (one or two passages of ~50 questions)


def recall_by_contract(split: str, cond: str) -> dict[str, float]:
    rows = json.loads((EVAL_DIR / "ev" / f"cuad_{split}_{cond}_LIVE.json").read_text(encoding="utf-8"))["rows"]
    by: dict[str, list[int]] = {}
    for r in rows:
        t = by.setdefault(r["contract"], [0, 0])
        t[0] += r.get("tp") or 0
        t[1] += (r.get("tp") or 0) + (r.get("fn") or 0)
    return {k: (tp / n if n else 1.0) for k, (tp, n) in by.items()}


class Double:
    mode, model = "TEST_DOUBLE", "scripted-whole"

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        return {"message": {"content": json.dumps({"method": "WHOLE", "reason": "scripted"})}, "usage": {}}


def main(args) -> int:
    provider = Double() if "--double" in args else evalkit.live_gate(args)[0]
    if provider is None:
        print("NOT_RUN:", evalkit.live_gate(args)[2])
        return 2
    manifest = json.loads(cuad_eval.MANIFEST.read_text(encoding="utf-8"))
    t = cuad_eval.task(manifest["questions"])
    rows, usage = [], []
    for split in ("heldout", "heldout_long"):
        whole, hybrid = recall_by_contract(split, "C"), recall_by_contract(split, "A")
        for row in manifest["subset"][split]:
            cid = row["id"]
            if cid not in whole or cid not in hybrid:
                continue
            best = "TIE" if abs(whole[cid] - hybrid[cid]) <= TIE else "WHOLE" if whole[cid] > hybrid[cid] else "HYBRID"
            files = cuad_eval.files_of(row, "pdf")
            rule, _ = intake_extract.whole_first(files, t)
            ai, info = intake_extract.ai_choice(provider, files, t)
            usage.append(info.get("usage") or {})
            rows.append({"split": split, "contract": cid, "pages": row["pages"], "recall_whole": round(whole[cid], 3),
                         "recall_hybrid": round(hybrid[cid], 3), "better": best, "rule": rule, "ai": ai,
                         "ai_by": info["proposed_by"], "candidates": info["candidates"], "reason": info["reason"],
                         "rule_right": best in ("TIE", rule), "ai_right": best in ("TIE", ai),
                         "cost_whole": info["whole"]["usd"], "cost_hybrid_at_most": info["hybrid_at_most"]["usd"]})
            print(cid, row["pages"], best, rule, ai, info["proposed_by"])

    def tot(k):
        return sum(r[k] for r in rows)
    lost = {k: round(sum(max(0.0, r["recall_whole"] - r["recall_hybrid"]) if r[k] == "HYBRID" else
                         max(0.0, r["recall_hybrid"] - r["recall_whole"]) for r in rows), 3) for k in ("rule", "ai")}
    summary = {"run_mode": provider.mode, "model": provider.model, "contracts": len(rows),
               "rule_right": tot("rule_right"), "ai_right": tot("ai_right"),
               "ai_asked": sum(r["ai_by"] == "AI" for r in rows),
               "recall_lost_vs_better": lost, "tie_band": TIE,
               "ai_hybrid_choices": sum(r["ai"] == "HYBRID" for r in rows),
               "est_cost_of_choices_usd": {k: round(sum(r["cost_hybrid_at_most"] if r[k] == "HYBRID" else r["cost_whole"]
                                                        for r in rows), 4) for k in ("rule", "ai")},
               "choice_calls_usd": round(sum(evalkit.cost_usd(u) for u in usage), 4),
               "source": "recorded outcomes of cuad_{heldout,heldout_long}_{A,C}_LIVE.json",
               "run": evalkit.run_info("scripts.read_choice_eval")}
    print(evalkit.write_report(f"read_choice_eval_{provider.mode}", summary, rows))
    print(json.dumps({k: summary[k] for k in ("contracts", "rule_right", "ai_right", "ai_asked", "recall_lost_vs_better",
                                              "est_cost_of_choices_usd", "choice_calls_usd")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
