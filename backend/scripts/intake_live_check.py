"""Meta LIVE check of document understanding on the separate LIVE fixture (never used by the automated tests).

Runs the same server parser, Muse extraction and server checks as POST /intakes/{id}/analyze, then compares the
checked draft with what the fixture actually says. Writes docs/evaluations/intake_live.json. Run from backend/:
    python -m scripts.intake_live_check            (one LIVE call; may incur charges)
"""

import json
import sys
import time

from app import EVAL_DIR, docparse, intake_extract
from app.intake import FIXTURE_DIR
from app.model_provider import MetaProvider, ProviderError

FIXTURE = FIXTURE_DIR / "live_complaint_DS-QN-2026-0099.pdf"
EXPECTED = {"customer_ref": "DS-QN-2026-0099", "lot": "L05", "defective_qty": "7", "part_number": "PCB-BMS-310 rev A",
            "delivery_date": "2026-10-20", "found_date": "2026-10-28"}
EXPECTED_STATUS = {"inspected_qty": "MISSING", "customer_cause_claim": "FOUND"}


def main() -> int:
    provider = MetaProvider.from_env()
    if provider is None:
        print("NOT_RUN: no MODEL_API_KEY")
        return 2
    data = FIXTURE.read_bytes()
    elements, coverage, blobs = docparse.parse("application/pdf", data)
    files = [{"file_id": 1, "name": FIXTURE.name, "data_origin": "SYNTHETIC", "elements": elements, "images": blobs}]
    t0 = time.perf_counter()
    try:
        raw, _ = intake_extract.extract(provider, files)
    except ProviderError as exc:
        print(f"FAILED: {exc}")
        return 1
    ms = round((time.perf_counter() - t0) * 1000)
    d = intake_extract.draft(raw, files)
    rows = []
    for k, want in EXPECTED.items():
        got = d["fields"][k]
        rows.append({"field": k, "want": want, "got": got["value"], "status": got["status"],
                     "ok": got["status"] == "FOUND" and (got["value"] or "").replace(" ", "").lower().find(
                         want.replace(" ", "").lower()) >= 0,
                     "locator": [s["element_id"] for s in got["sources"]]})
    for k, want in EXPECTED_STATUS.items():
        rows.append({"field": k, "want_status": want, "status": d["fields"][k]["status"],
                     "kind": d["fields"][k]["kind"], "ok": d["fields"][k]["status"] == want})
    checks = {"deadline_absolute": d["fields"]["reply_deadline"]["status"] == "FOUND",
              "no_rate_note": any("불량률" in n for n in d["notes"]),
              "injection_flagged": any(f["element_id"].startswith("pdf:p1:") for f in d["flags"]),
              "image_linked": any(lk["element_id"].startswith("pdf:p") and "img" in lk["element_id"] for lk in d["links"]),
              "rejected_values": sum(len(v["rejected"]) for v in d["fields"].values())}
    out = {"model": provider.model, "mode": provider.mode, "latency_ms": ms, "fixture": FIXTURE.name,
           "fields_ok": sum(r["ok"] for r in rows), "fields_total": len(rows), "rows": rows, "checks": checks,
           "documents": d["documents"], "questions": d["questions"], "coverage": coverage}
    (EVAL_DIR / "intake_live.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"LIVE {provider.model}: fields {out['fields_ok']}/{out['fields_total']} in {ms} ms; checks {checks}")
    for r in rows:
        if not r["ok"]:
            print("  miss:", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
