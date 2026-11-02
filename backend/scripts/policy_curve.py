"""Offline (python -m scripts.policy_curve): WHOLE_FIRST under different per-call cost caps, composed from the recorded A (HYBRID) and C (WHOLE) runs.
For each cap the server's own decision function says which path a contract takes; that contract's recorded result
on that path is used (mean over runs). Flags a contract where the cap would also cut HYBRID's own input (the recorded
request would then differ)."""
import glob
import json
from pathlib import Path

from app import intake_extract, limits
from scripts import cuad_eval, evalkit

man = json.loads(cuad_eval.MANIFEST.read_text(encoding="utf-8"))
t = cuad_eval.task(man["questions"])


def runs(split, c):
    out = []
    for rp in sorted(glob.glob(f"../docs/evaluations/ev/cuad_{split}_{c}_LIVE*.json")):
        r = json.loads(Path(rp).read_text(encoding="utf-8"))
        tp = {}
        for q in r["rows"]:
            if q["status"] == "OK" and q["aligned"] is not False:
                tp[q["contract"]] = tp.get(q["contract"], 0) + q["tp"]
        tr = {json.loads(x)["id"]: json.loads(x) for x in
              (cuad_eval.CUAD_DIR / "traces" / r["summary"]["trace"]).read_text(encoding="utf-8").splitlines()[1:]}
        cost = {k: sum(evalkit.cost_usd(c_["usage"]) for c_ in v["calls"]) for k, v in tr.items()}
        peak = {k: max(c_["usage"].get("prompt_tokens", 0) for c_ in v["calls"]) for k, v in tr.items()}
        out.append((tp, cost, peak))
    return out


caps = [0, 0.15, 0.10, 0.08, 0.06, 0.04]
for split in ("heldout", "heldout_long"):
    A, C = runs(split, "A"), runs(split, "C")
    rows = man["subset"][split]
    gold = {}
    for rp in glob.glob(f"../docs/evaluations/ev/cuad_{split}_C_LIVE.json"):
        for q in json.loads(Path(rp).read_text(encoding="utf-8"))["rows"]:
            if q["status"] == "OK" and q["aligned"] is not False:
                gold[q["contract"]] = gold.get(q["contract"], 0) + q["gold_spans"]
    print(f"\n{split} ({len(A)} HYBRID run(s), {len(C)} WHOLE run(s)); gold spans {sum(gold.values())}")
    print("cap($/call) docs->HYBRID  recall   cost($)  flagged")
    for cap in caps:
        limits.OVERRIDES["MAX_COST_PER_MODEL_CALL_USD"] = cap
        hits = cost = 0.0
        nav, flagged = 0, []
        for r in rows:
            mode, why = intake_extract.whole_first(cuad_eval.files_of(r, "pdf"), t)
            src = A if mode == "HYBRID" else C
            hits += sum(x[0].get(r["id"], 0) for x in src) / len(src)
            cost += sum(x[1].get(r["id"], 0) for x in src) / len(src)
            if mode == "HYBRID":
                nav += 1
                if max(x[2].get(r["id"], 0) for x in A) > why["max_input_tokens"]:
                    flagged.append(r["pages"])
        print(f"{'off' if not cap else cap:>10} {nav:>12} {hits / sum(gold.values()):8.3f} {cost:9.3f}  {flagged}")
    limits.OVERRIDES.pop("MAX_COST_PER_MODEL_CALL_USD", None)
