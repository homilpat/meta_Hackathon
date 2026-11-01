"""LIVE comparison on the held-out documents (scripts/holdout_docs.py): WHOLE vs HYBRID (server selection +
table of contents/map + the model asking for parts). Several LIVE calls; may incur charges. Run from backend/:
    python -m scripts.holdout_live [MODE ...] [DOC ...]      e.g. HYBRID H3 (default: both modes, all documents)
Writes docs/evaluations/holdout_live.json.
"""

import json
import sys
import time

from app import EVAL_DIR, docparse, intake_extract, limits
from app.model_provider import MetaProvider, ProviderError
from scripts.holdout_docs import DOCS


def norm(s: str) -> str:
    return "".join((s or "").lower().split())


def main() -> int:
    provider = MetaProvider.from_env()
    if provider is None:
        print("NOT_RUN: no MODEL_API_KEY")
        return 2
    args = sys.argv[1:]
    modes = [a for a in args if a in ("WHOLE", "HYBRID")] or ["WHOLE", "HYBRID"]
    names = [a for a in args if a in DOCS] or list(DOCS)
    path = EVAL_DIR / "holdout_live.json"
    out = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name in names:
        media, make = DOCS[name]
        data, truth = make()
        els, cov, blobs = docparse.parse(media, data, docparse.Budget(1000))
        files = [{"file_id": 1, "name": f"{name}.{'pdf' if media.endswith('pdf') else 'docx'}", "tier": "RAW",
                  "data_origin": "SYNTHETIC", "elements": els, "coverage": cov, "images": blobs}]
        for mode in modes:
            limits.OVERRIDES["EXTRACT_MODE"] = mode
            t0 = time.perf_counter()
            try:
                raw, _, info = intake_extract.extract(provider, files)
            except ProviderError as exc:
                out[f"{name}/{mode}"] = {"error": str(exc)}
                print(name, mode, "FAILED", exc)
                continue
            d = intake_extract.draft(raw, files)
            got = {f: d["fields"][f]["status"] in ("FOUND", "NEEDS_CONFIRMATION")
                   and norm(v) in norm(d["fields"][f]["value"]) for f, v in truth.items()}
            res = {"caught": sum(got.values()), "of": len(got), "missed": [f for f, ok in got.items() if not ok],
                   "prompt_tokens": info["usage"].get("prompt_tokens"), "seconds": round(time.perf_counter() - t0, 1),
                   "rounds": info.get("rounds"), "pieces": info.get("pieces")}
            out[f"{name}/{mode}"] = res
            print(name, mode, f"{res['caught']}/{res['of']}", "missed", res["missed"], "prompt", res["prompt_tokens"],
                  f"{res['seconds']}s", "asked", [r.get("asked") for r in (res["rounds"] or [])][1:])
    limits.OVERRIDES.pop("EXTRACT_MODE", None)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
