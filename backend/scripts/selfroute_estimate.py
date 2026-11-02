"""Offline (python -m scripts.selfroute_estimate): how often a Self-Route fallback (navigation, then full reading for what is still missing) would trigger,
and what it would cost, from the recorded navigation (A) and full (C) runs. No model, no network."""
import glob
import json
from pathlib import Path

from scripts import cuad_eval, evalkit

man = json.loads(cuad_eval.MANIFEST.read_text(encoding="utf-8"))
for split in ("heldout", "heldout_long"):
    t = {}
    for c in "AC":
        p = max(glob.glob(str(cuad_eval.CUAD_DIR / "traces" / f"{split}-{c}-LIVE-2*.jsonl")))
        t[c] = {json.loads(x)["id"]: json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines()[1:]}
    rep = {c: {q["question"]: q for q in json.loads(Path(f"../docs/evaluations/ev/cuad_{split}_{c}_LIVE.json")
                                                     .read_text(encoding="utf-8"))["rows"]} for c in "AC"}
    trig = 0
    cost = {"A": 0.0, "C": 0.0, "self_route_at_least": 0.0}
    hits = {"A": 0, "C": 0, "self_route_at_most": 0}
    gold = 0
    for r in man["subset"][split]:
        files = cuad_eval.files_of(r, "pdf")
        raw = t["A"][r["id"]]["raw"]
        missing = [q["category"] for q in r["questions"]
                   if not cuad_eval.valid_spans(raw, files, cuad_eval.key(q["category"]))[0]]
        ca = sum(evalkit.cost_usd(c["usage"]) for c in t["A"][r["id"]]["calls"])
        cc = sum(evalkit.cost_usd(c["usage"]) for c in t["C"][r["id"]]["calls"])
        cost["A"] += ca
        cost["C"] += cc
        cost["self_route_at_least"] += ca + (cc if missing else 0)  # full read of the same document when triggered
        for q in r["questions"]:
            k = f"{r['id']}__{cuad_eval.key(q['category'])}"
            if rep["C"][k]["aligned"] is False:
                continue
            gold += rep["C"][k]["gold_spans"]
            hits["A"] += rep["A"][k]["tp"]
            hits["C"] += rep["C"][k]["tp"]
            hits["self_route_at_most"] += rep["C"][k]["tp"] if q["category"] in missing else rep["A"][k]["tp"]
        trig += bool(missing)
    print(f"{split}: fallback triggered in {trig}/10 contracts (some category with no valid quote after navigation)")
    print("  cost  A {:.3f}  C {:.3f}  self-route >= {:.3f}".format(cost["A"], cost["C"], cost["self_route_at_least"]))
    print("  recall A {:.3f}  C {:.3f}  self-route <= {:.3f}".format(hits["A"] / gold, hits["C"] / gold,
                                                          hits["self_route_at_most"] / gold))
