"""Intent-classification golden set: offline keyword rules always, the LIVE model when MODEL_API_KEY is set.

The LIVE side calls app.agent.classify, the same function the agent runs, with a fixed situation card. A match is
exact set equality of intents. Writes docs/evaluations/intent_eval.json. Run from backend/:
    python -m scripts.intent_eval            (LIVE calls may incur charges: one per goal)
"""

import json
import sys
import time
from pathlib import Path

from app import EVAL_DIR
from app.agent import FINAL_8D_REPORT, PLANNER_VERSION, classify, intents_of
from app.model_provider import MetaProvider, ProviderError

GOLDEN = Path(__file__).with_name("intent_golden.json")
SITUATION = {"user": "alice", "role": "AUTHOR", "case": "L", "d0_route": None,
             "state": dict.fromkeys(["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]),
             "documents": [], "closure_ready": False, "my_tasks": [], "may_draft_documents": True,
             "recent_turns": [], "recent_refusals": [], "final_8d_report": FINAL_8D_REPORT}  # as Executor.situation


def evaluate(items: list[dict], provider=None) -> dict:
    rows = []
    for it in items:
        want = sorted(it["intents"])
        row = {"goal": it["goal"], "split": it.get("split", "tuning"), "expected": want,
               "offline": sorted(intents_of(it["goal"]))}
        row["offline_ok"] = row["offline"] == want
        if provider is not None:
            t0 = time.perf_counter()
            try:
                out = classify(provider, SITUATION, it["goal"])
                got = sorted(out["intents"])  # what the agent runs: the model's reading, no rule added (2026-11-04)
                row.update(live=got, model_raw=sorted(out["intents"]), clarify=out["clarify"], live_ok=got == want)
            except ProviderError as exc:
                row.update(live=None, live_error=str(exc), live_ok=False)
            row["live_ms"] = round((time.perf_counter() - t0) * 1000)
        rows.append(row)
    n = len(rows)
    out = {"planner_version": PLANNER_VERSION, "n": n,
           "offline_correct": sum(r["offline_ok"] for r in rows), "rows": rows,
           # "tuning" sentences were seen while writing the rules and the prompt; "holdout" ones were not
           "by_split": {sp: {"n": sum(r["split"] == sp for r in rows),
                             "offline": sum(r["offline_ok"] for r in rows if r["split"] == sp),
                             **({"live": sum(r["live_ok"] for r in rows if r["split"] == sp)} if provider else {})}
                        for sp in ("tuning", "holdout")}}
    if provider is not None:
        lat = sorted(r["live_ms"] for r in rows)
        out.update(model=provider.model, live_correct=sum(r["live_ok"] for r in rows),
                   live_ms_median=lat[n // 2], live_ms_max=lat[-1])
    else:
        out["live"] = "NOT_RUN (no MODEL_API_KEY)"
    return out


def main() -> int:
    items = json.loads(GOLDEN.read_text(encoding="utf-8"))
    result = evaluate(items, MetaProvider.from_env())
    (EVAL_DIR / "intent_eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for sp, v in result["by_split"].items():
        print(f"{sp}: offline {v['offline']}/{v['n']}" + (f", LIVE {v['live']}/{v['n']}" if "live" in v else ""))
    print(f"offline {result['offline_correct']}/{result['n']}", end="")
    if "live_correct" in result:
        print(f" | LIVE {result['live_correct']}/{result['n']} median {result['live_ms_median']} ms "
              f"max {result['live_ms_max']} ms ({result['model']}, planner {PLANNER_VERSION})")
        for r in result["rows"]:
            if not r["live_ok"]:
                print(f"  LIVE miss: {r['goal']!r} expected {r['expected']} got {r.get('live')} "
                      f"{r.get('live_error', '')}".rstrip())
    else:
        print(f" | {result['live']}")
    for r in result["rows"]:
        if not r["offline_ok"]:
            print(f"  offline miss: {r['goal']!r} expected {r['expected']} got {r['offline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
