"""Functional test of document intake on a few self-made SYNTHETIC files (spec §26.3, §26.7). Not a manufacturing
benchmark: the files and their truths were written by the same team as the parser, so they show that the pipeline
does what it should on known layouts, nothing about real customer documents. Run from backend/:

    python -m scripts.fixture_eval                       parser and vision checks (real code, no model) and the
                                                         replay of any saved extraction traces -> docs/evaluations/ev
    python -m scripts.fixture_eval collect --live        new LIVE extraction traces (paid; QO_EVAL_LIVE_BUDGET_USD)
                                  [--mode M]          read mode (default HYBRID; e.g. AI_CHOICE, WHOLE_FIRST)

Truths are written by hand from the generator (scripts/make_intake_fixtures.py, scripts/holdout_docs.py) and each
locator was checked once against the parser output; they are not produced by the code under test.
Split: dev = the files the automated tests were built on; validation = the LIVE-only files, never used to build
tests (the held-out H1-H3 are scored by scripts/holdout_live.py).
"""

import json
import sys
import time
from pathlib import Path

from app import docparse, intake_extract
from app.intake import FIXTURE_DIR
from app.model_provider import ProviderError
from scripts import evalkit
from scripts.cuad_eval import Recorder, Replay, StaleTrace

PDF, DOCX = "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TRACES = evalkit.DATA_DIR / "fixtures" / "traces"

# Parser truth: what the server alone must get right (no model involved)
PARSE = {
    "complaint_HM-CC-2026-0417.pdf": {"split": "dev", "coverage": {
        "tables": "RECONSTRUCTED", "charts": "IMAGE_ONLY", "scan": "NEEDS_VISION", "scan_pages": 1},
        "cells": {"pdf:p1:t1:r2:c1": "L02", "pdf:p1:t1:r2:c3": "12", "pdf:p1:t1:r2:c4": "boards",
                  "pdf:p1:t1:r1:c3": "Defective qty"},
        "captions": {"pdf:p1:img1": "pdf:p1:l16", "pdf:p2:img1": "pdf:p2:l2"},
        "scan_elements": ["pdf:p3:scan"], "flags": ["pdf:p1:l16"], "vision_image": "pdf:p1:img1"},
    "supplement_HM-CC-2026-0417.docx": {"split": "dev", "coverage": {"tables": "OK", "charts": "OK", "scan": "NONE"},
        "cells": {"docx:t1:r3:c1": "L03", "docx:t1:r3:c2": "480", "docx:t1:r3:c3": "12"},
        "merged": {"docx:t1:r1:c1": 4},
        "captions": {"docx:img1": "docx:p5", "docx:chart1": "docx:p8"}, "duplicates": {"docx:img2": "docx:img1"},
        "chart": {"docx:chart1": {"values": [2.0, 3.0, 7.0], "total": 12.0, "source": "CHART_CACHE"}}},
    "chart_workbook_mismatch.docx": {"split": "dev", "coverage": {"charts": "MISMATCH"},
        "chart": {"docx:chart1": {"values": [2.0, 3.0, 7.0], "workbook_values": [2, 3, 8]}}},
    "live_complaint_DS-QN-2026-0099.pdf": {"split": "validation", "coverage": {"scan": "NONE", "scan_pages": 0},
        "cells": {"pdf:p1:t1:r2:c1": "L05", "pdf:p1:t1:r2:c3": "7"}, "captions": {"pdf:p1:img1": "pdf:p1:l16"}},
    "live_supplement_DS-QN-2026-0099.docx": {"split": "validation", "coverage": {"tables": "OK"},
        "cells": {"docx:t1:r2:c1": "L06", "docx:t1:r2:c2": "350"}},
    "live_scan_DS-QN-2026-0099.pdf": {"split": "validation",
        "coverage": {"text": "NONE", "scan": "NEEDS_VISION", "scan_pages": 1}, "scan_elements": ["pdf:p1:scan"]},
}
# Extraction truth per file set: field -> (status, value it must contain or None, locators allowed as its source)
CASES = {
    "complaint": {"split": "dev", "files": ["complaint_HM-CC-2026-0417.pdf"], "fields": {
        "customer_ref": ("FOUND", "HM-CC-2026-0417", ["pdf:p1:l3"]),
        "lot": ("FOUND", "L02", ["pdf:p1:t1:r2:c1", "pdf:p1:l12"]),
        "defective_qty": ("FOUND", "12", ["pdf:p1:t1:r2:c3", "pdf:p1:l14"]),
        "qty_unit": ("FOUND", "boards", ["pdf:p1:t1:r2:c4", "pdf:p1:l15"]),
        "part_number": ("FOUND", "PCB-ECU-200", ["pdf:p1:l4"]),
        "delivery_date": ("FOUND", "2026-10-20", ["pdf:p1:l4"]), "found_date": ("FOUND", "2026-10-28", ["pdf:p1:l4"]),
        "inspected_qty": ("MISSING", None, []), "reply_deadline": ("NEEDS_CONFIRMATION", "Friday", ["pdf:p1:l7"]),
        "customer_cause_claim": ("FOUND", "solder paste", ["pdf:p1:l6"])},
        "links": {"pdf:p1:img1": "pdf:p1:l16"}},
    "complaint+supplement": {"split": "dev", "files": ["complaint_HM-CC-2026-0417.pdf",
                                                       "supplement_HM-CC-2026-0417.docx"], "fields": {
        "lot": ("CONFLICT", None, []), "inspected_qty": ("FOUND", "480", ["docx:t1:r3:c2"])}},
    "live_complaint": {"split": "validation", "files": ["live_complaint_DS-QN-2026-0099.pdf"], "fields": {
        "customer_ref": ("FOUND", "DS-QN-2026-0099", ["pdf:p1:l3"]),
        "lot": ("FOUND", "L05", ["pdf:p1:t1:r2:c1", "pdf:p1:l12"]),
        "defective_qty": ("FOUND", "7", ["pdf:p1:t1:r2:c3", "pdf:p1:l14"]),
        "inspected_qty": ("MISSING", None, []),
        "reply_deadline": ("FOUND", "2026-11-07", ["pdf:p1:l7"])}},
    "live_complaint+supplement": {"split": "validation", "files": ["live_complaint_DS-QN-2026-0099.pdf",
                                                                   "live_supplement_DS-QN-2026-0099.docx"],
                                  "fields": {"lot": ("CONFLICT", None, []),
                                             "inspected_qty": ("FOUND", "350", ["docx:t1:r2:c2"])}},
}


def media(name: str) -> str:
    return PDF if name.endswith(".pdf") else DOCX


def files_of(names: list[str]) -> list[dict]:
    out = []
    for k, n in enumerate(names, 1):
        data = (FIXTURE_DIR / n).read_bytes()
        els, cov, blobs = docparse.parse(media(n), data)
        out.append({"file_id": k, "name": n, "tier": "RAW", "data_origin": "SYNTHETIC", "elements": els,
                    "coverage": cov, "images": blobs, "sha256": evalkit.sha256_bytes(data)})
    return out


def parse_rows() -> list[dict]:
    rows = []
    for name, t in PARSE.items():
        els, cov, _ = docparse.parse(media(name), (FIXTURE_DIR / name).read_bytes())
        by = {e["id"]: e for e in els}
        checks = {f"coverage.{k}": cov.get(k) == v for k, v in t.get("coverage", {}).items()}
        checks |= {f"cell {k}": by.get(k, {}).get("text") == v for k, v in t.get("cells", {}).items()}
        checks |= {f"merged {k}": by.get(k, {}).get("span") == v for k, v in t.get("merged", {}).items()}
        checks |= {f"caption {k}": by.get(k, {}).get("caption_id") == v for k, v in t.get("captions", {}).items()}
        checks |= {f"duplicate {k}": by.get(k, {}).get("duplicate_of") == v for k, v in t.get("duplicates", {}).items()}
        for k, want in t.get("chart", {}).items():
            s = (by.get(k, {}).get("series") or [{}])[0]
            checks |= {f"chart {k}.{x}": (s.get(x) if x != "source" else by[k].get("source")) == v
                       for x, v in want.items()}
        checks |= {f"scan {k} needs vision": by.get(k, {}).get("status") == "NEEDS_VISION"
                   for k in t.get("scan_elements", [])}
        if t.get("flags"):
            d = intake_extract.draft(None, [{"file_id": 1, "elements": els}])
            checks |= {f"injection flagged {k}": k in {x["element_id"] for x in d["flags"]} for k in t["flags"]}
        rows.append({"part": "parse", "case": name, "split": t["split"], "run_mode": "OFFLINE_REAL_CODE",
                     "checks": checks, "passed": sum(checks.values()), "of": len(checks),
                     "failed": [k for k, v in checks.items() if not v]})
    return rows


def vision_rows(tmp: Path) -> list[dict]:
    """The specialist vision tool is not connected: the honest answer is NOT_CONFIGURED with no detection."""
    from fastapi.testclient import TestClient

    from app.db import Base
    from app.main import create_app
    from tests.test_intake_in1 import upload
    from tests.v5_util import H

    app = create_app(f"sqlite:///{tmp / 'vision.db'}")
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    name = "complaint_HM-CC-2026-0417.pdf"
    body = upload(c, [(name, (FIXTURE_DIR / name).read_bytes())]).json()
    c.post(f"/intakes/{body['intake_id']}/analyze", headers=H("alice"))  # no provider: parse only, OFFLINE draft
    resp = c.post("/vision/requests", json={"analysis_type": "DEFECT_DETECTION", "intake_id": body["intake_id"],
                                            "file_id": body["files"][0]["file_id"],
                                            "element_id": PARSE[name]["vision_image"]}, headers=H("alice"))
    r = resp.json()
    again = c.get("/vision/requests", params={"intake_id": body["intake_id"]}, headers=H("alice")).json()
    checks = {"request accepted (201)": resp.status_code == 201, "status NOT_CONFIGURED": r.get("status") == "NOT_CONFIGURED", "no result": r.get("result") is None,
              "no result type": r.get("result_type") is None, "re-read the same": again == [r]}
    return [{"part": "vision", "case": name, "split": "dev", "run_mode": "OFFLINE_REAL_CODE", "checks": checks,
             "passed": sum(checks.values()), "of": len(checks), "failed": [k for k, v in checks.items() if not v]}]


def score_extraction(case: str, raw: dict | None, files: list[dict]) -> dict:
    """Field status, value and locator against the truth; a FOUND value that is wrong is a wrong confirmation."""
    t = CASES[case]
    d = intake_extract.draft(raw, files)
    checks, wrong = {}, 0
    for field, (status, value, at) in t["fields"].items():
        got = d["fields"][field]
        checks[f"{field} status"] = got["status"] == status
        if value is not None:
            ok = got["value"] is not None and intake_extract.norm(value) in intake_extract.norm(got["value"])
            checks[f"{field} value"] = ok
            wrong += got["status"] == "FOUND" and not ok
        if at:
            checks[f"{field} locator"] = bool(got["sources"]) and all(s["element_id"] in at for s in got["sources"])
    for img, cap in t.get("links", {}).items():
        checks[f"link {img}"] = any(lk["element_id"] == img and cap in lk["related_element_ids"] for lk in d["links"])
    return {"checks": checks, "passed": sum(checks.values()), "of": len(checks), "wrong_confirmations": wrong,
            "failed": [k for k, v in checks.items() if not v]}


def extraction_rows() -> list[dict]:
    rows = []
    paths = sorted(TRACES.glob("*.jsonl")) if TRACES.exists() else []
    if not paths:
        return [{"part": "extraction", "case": c, "split": t["split"], "run_mode": "NOT_RUN",
                 "why": "no saved extraction trace (earlier LIVE checks kept scores, not raw replies)"}
                for c, t in CASES.items()]
    for p in paths:
        lines = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        for rec in lines[1:]:
            files = files_of(CASES[rec["case"]]["files"])
            status = "OK"
            try:
                raw, _, _ = intake_extract.extract(Replay(rec["calls"]), files, "RAW", rec["read_mode"])
            except StaleTrace as exc:
                raw, status = rec["raw"], f"STALE_TRACE: {exc}"
            except ProviderError:
                raw, status = None, "FAILED"
            rows.append({"part": "extraction", "case": rec["case"], "split": CASES[rec["case"]]["split"],
                         "run_mode": lines[0]["header"]["run_mode"], "status": status, "trace": p.name,
                         "read_mode": rec["read_mode"], "usage": rec["usage"],
                         **(score_extraction(rec["case"], raw, files) if status == "OK" else {})})
    return rows


def collect(args: list[str]) -> int:
    provider, budget, why = evalkit.live_gate(args)
    if provider is None:
        print("NOT_RUN:", why)
        return 2
    TRACES.mkdir(parents=True, exist_ok=True)
    mode = args[args.index("--mode") + 1] if "--mode" in args else "HYBRID"  # e.g. AI_CHOICE, WHOLE_FIRST
    out = TRACES / f"{provider.mode}-{evalkit.now().replace(':', '')}.jsonl"
    spent = 0.0
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"header": evalkit.run_info("scripts.fixture_eval", run_mode=provider.mode,
                                                       model=provider.model, budget_usd=budget)}) + "\n")
        for case, t in CASES.items():
            if spent >= budget:
                print("STOPPED: budget reached")
                break
            rec = Recorder(provider)
            t0 = time.perf_counter()
            try:
                raw, _, info = intake_extract.extract(rec, files_of(t["files"]), "RAW", mode)
            except ProviderError as exc:
                raw, info = None, {"error": str(exc)}
            usage = info.get("usage", {})
            spent += evalkit.cost_usd(usage) + evalkit.cost_usd((info.get("auto") or {}).get("usage") or {})
            f.write(json.dumps({"case": case, "read_mode": mode, "chosen": info.get("mode"), "choice": info.get("auto"),
                                "calls": rec.calls, "raw": raw, "usage": usage,
                                "seconds": round(time.perf_counter() - t0, 2)}, ensure_ascii=False) + "\n")
    print("trace", out, f"spent {spent:.3f} USD")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["collect"]:
        return collect(args[1:])
    import tempfile

    with evalkit.no_network() as attempts:
        rows = parse_rows() + vision_rows(Path(tempfile.mkdtemp())) + extraction_rows()
    done = [r for r in rows if "of" in r]
    summary = {
        "what": "SYNTHETIC functional fixtures, not a manufacturing benchmark and never combined with CUAD",
        "by_part": {part: {split: f"{sum(r['passed'] for r in done if r['part'] == part and r['split'] == split)}/"
                                  f"{sum(r['of'] for r in done if r['part'] == part and r['split'] == split)}"
                           for split in ("dev", "validation")} for part in ("parse", "vision", "extraction")},
        "extraction_not_run": [r["case"] for r in rows if r["run_mode"] == "NOT_RUN"],
        "wrong_confirmations": sum(r.get("wrong_confirmations", 0) for r in rows),
        "network_attempts": len(attempts), "model_calls": 0,
        "not_evaluated": ["what an image shows (no vision model; NOT_CONFIGURED is the expected answer)",
                          "whether a question to the customer is well worded (human review)"],
        "run": evalkit.run_info("scripts.fixture_eval")}
    print(evalkit.write_report("fixture_eval", summary, rows))
    print(json.dumps(summary["by_part"]), "not run:", summary["extraction_not_run"])
    return 0 if all(not r.get("failed") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
