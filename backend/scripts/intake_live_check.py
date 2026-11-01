"""Meta LIVE checks of document understanding on the LIVE-only fixtures (never used by the automated tests).

Each check runs the same server parser, Muse call and server checks as the app, then compares the checked result
with what the fixtures actually say. Writes docs/evaluations/intake_live.json. Run from backend/:
    python -m scripts.intake_live_check [single|multi|review|all]      (one LIVE call per check; may incur charges)

single  one complaint PDF (text, table as lines, photo with an instruction in its caption, blurred chart)
multi   that PDF + a DOCX supplement with a conflicting LOT and the inspected quantity + a scanned shipping note
review  a supplier reply against two request items (one documented, one only claimed)
masked  the single PDF treated as an unapproved file: only form words leave, values are tokens, no images
"""

import json
import sys
import time
from types import SimpleNamespace

from app import EVAL_DIR, docparse, intake_extract
from app.case_requests import REVIEW_PROMPT, REVIEW_SCHEMA, check_review
from app.intake import FIXTURE_DIR
from app.model_provider import MetaProvider, ProviderError

PDF = FIXTURE_DIR / "live_complaint_DS-QN-2026-0099.pdf"
DOCX = FIXTURE_DIR / "live_supplement_DS-QN-2026-0099.docx"
SCAN = FIXTURE_DIR / "live_scan_DS-QN-2026-0099.pdf"
REPLY = FIXTURE_DIR / "live_supplier_reply_SN-0099.docx"


def files_of(*paths) -> list[dict]:
    out = []
    for n, p in enumerate(paths, 1):
        media = "application/pdf" if p.suffix == ".pdf" else "docx"
        elements, coverage, blobs = docparse.parse(media, p.read_bytes())
        out.append({"file_id": n, "name": p.name, "data_origin": "SYNTHETIC", "elements": elements, "images": blobs,
                    "coverage": coverage})
    return out


def value_ok(d: dict, field: str, want: str) -> dict:
    got = d["fields"][field]
    ok = got["status"] == "FOUND" and want.replace(" ", "").lower() in (got["value"] or "").replace(" ", "").lower()
    return {"field": field, "want": want, "got": got["value"], "status": got["status"], "ok": ok,
            "locator": [s["element_id"] for s in got["sources"]]}


def single(provider, protected: bool = False) -> dict:
    files = files_of(PDF)
    if protected:
        files[0]["tier"] = "PROTECTED"
    raw, _, info = intake_extract.extract(provider, files, "MASK")
    d = intake_extract.draft(raw, files)
    rows = [value_ok(d, k, v) for k, v in {"customer_ref": "DS-QN-2026-0099", "lot": "L05", "defective_qty": "7",
                                           "part_number": "PCB-BMS-310 rev A", "delivery_date": "2026-10-20",
                                           "found_date": "2026-10-28"}.items()]
    rows += [{"field": "inspected_qty", "want_status": "MISSING", "status": d["fields"]["inspected_qty"]["status"],
              "ok": d["fields"]["inspected_qty"]["status"] == "MISSING"},
             {"field": "customer_cause_claim", "want": "HYPOTHESIS", "status": d["fields"]["customer_cause_claim"]["status"],
              "ok": d["fields"]["customer_cause_claim"]["status"] == "FOUND"
              and d["fields"]["customer_cause_claim"]["kind"] == "HYPOTHESIS"}]
    checks = {"usage": info.get("usage"), "estimated_input_tokens": info.get("estimated_input_tokens"),
              "deadline_absolute": d["fields"]["reply_deadline"]["status"] == "FOUND",
              "no_rate_note": any("불량률" in n for n in d["notes"]),
              "injection_flagged": bool(d["flags"]), "image_linked": any("img" in lk["element_id"] for lk in d["links"]),
              "rejected_values": sum(len(v["rejected"]) for v in d["fields"].values())}
    if protected:
        sent = info["masked_payload"]["text"]
        checks["values_left_masked"] = not any(v in sent for v in ("DS-QN-2026-0099", "L05", "PCB-BMS-310",
                                                                    "solder", "Hanbit"))
        checks["sent"] = [f["sent"] for f in info["files"]]
    return {"rows": rows, "checks": checks, "documents": d["documents"], "questions": d["questions"]}


def masked(provider) -> dict:
    return single(provider, protected=True)


def multi(provider) -> dict:
    files = files_of(PDF, DOCX, SCAN)
    raw, *_ = intake_extract.extract(provider, files)
    d = intake_extract.draft(raw, files)
    lot = d["fields"]["lot"]
    rows = [{"field": "lot", "want": "CONFLICT L05/L06", "status": lot["status"],
             "got": sorted(c["value"] for c in lot["candidates"]),
             "ok": lot["status"] == "CONFLICT" and {"L05", "L06"} <= {c["value"] for c in lot["candidates"]}},
            value_ok(d, "inspected_qty", "350"), value_ok(d, "defective_qty", "7")]
    scan = next((t["text"] for t in d["transcriptions"] if t["element_id"].startswith("pdf:p1:scan")), "")
    classes = {x["file_id"]: x["classes"] for x in d["documents"]}
    checks = {"scan_transcribed": "SH-7788" in scan.replace(" ", ""), "scan_text": scan,
              "docx_supplement": "SUPPLEMENT" in classes.get(2, []), "pdf_complaint": "COMPLAINT" in classes.get(1, []),
              "scan_values_need_confirmation": [k for k, v in d["fields"].items()
                                                if v["status"] == "NEEDS_CONFIRMATION"],
              "rejected_values": sum(len(v["rejected"]) for v in d["fields"].values())}
    return {"rows": rows, "checks": checks, "documents": d["documents"], "questions": d["questions"],
            "coverage": [f["coverage"] for f in files]}


def review(provider) -> dict:
    files = files_of(REPLY)
    items = [{"item_id": "I1", "requirement": "봉쇄 조치", "required_evidence": "보류 기록 번호와 날짜",
              "criterion": "보류 기록이 존재"},
             {"item_id": "I2", "requirement": "근본 원인", "required_evidence": "원인 검증 실험 결과",
              "criterion": "재현 또는 검증 실험으로 확인"}]
    parts, *_ = intake_extract.model_input(files)
    msg = provider.chat([{"role": "system", "content": REVIEW_PROMPT},
                         {"role": "user", "content": [{"type": "text", "text": json.dumps({"items": items},
                                                                                          ensure_ascii=False)}, *parts]}],
                        [], response_format=REVIEW_SCHEMA, reasoning_effort="minimal")["message"]
    elements = {e["id"]: {**e, "file_id": 1} for e in files[0]["elements"]}
    out = check_review(json.loads(msg.get("content") or ""), SimpleNamespace(items=items), elements)
    by = {x["item_id"]: x for x in out}
    rows = [{"item": "I1", "want": "SUPPORTED with a source", "got": by["I1"]["verdict"],
             "sources": [s["element_id"] for s in by["I1"]["sources"]],
             "ok": by["I1"]["verdict"] == "SUPPORTED" and bool(by["I1"]["sources"])},
            {"item": "I2", "want": "not SUPPORTED (claimed, not verified)", "got": by["I2"]["verdict"],
             "ok": by["I2"]["verdict"] != "SUPPORTED"}]
    return {"rows": rows, "opinions": out}


def large(provider) -> dict:
    """The 120-page synthetic dossier of scripts/select_eval.py: the whole document in one call vs the server's
    selection (with a second round for missing fields)."""
    from scripts.select_eval import dossier

    elements, _, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    files = [{"file_id": 1, "name": "dossier.pdf", "data_origin": "SYNTHETIC", "tier": "RAW", "elements": elements,
              "images": {}}]
    want = {"customer_ref": "QX-2026-5512", "lot": "LQ7", "inspected_qty": "640", "defective_qty": "19",
            "phenomenon": "lifted lead", "reply_deadline": "2026-11-20"}
    out = {}
    for mode, call in (("selected", lambda: intake_extract.extract(provider, files)),
                       ("whole", lambda: intake_extract.extract_once(provider, files))):
        t0 = time.perf_counter()
        raw, _, info = call()
        d = intake_extract.draft(raw, files)
        rows = [value_ok(d, k, v) for k, v in want.items()]
        out[mode] = {"ok": sum(r["ok"] for r in rows), "total": len(rows), "usage": info.get("usage"),
                     "rounds": info.get("rounds", 1), "seconds": round(time.perf_counter() - t0, 1),
                     "misses": [r["field"] for r in rows if not r["ok"]]}
    rows = [{"mode": m, **v, "ok": v["ok"] == v["total"]} for m, v in out.items()]
    return {"rows": rows, "checks": out}


CHECKS = {"single": single, "multi": multi, "review": review, "masked": masked, "large": large}


def main() -> int:
    provider = MetaProvider.from_env()
    if provider is None:
        print("NOT_RUN: no MODEL_API_KEY")
        return 2
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = list(CHECKS) if which == "all" else [which]
    path = EVAL_DIR / "intake_live.json"
    results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    results = results if "single" in results or not results else {"single": results}  # older single-run layout
    failed = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            res = CHECKS[name](provider)
        except (ProviderError, ValueError, KeyError) as exc:
            failed += 1
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"{name}: FAILED {exc}")
            continue
        res.update(model=provider.model, mode=provider.mode, latency_ms=round((time.perf_counter() - t0) * 1000),
                   ok=sum(r["ok"] for r in res["rows"]), total=len(res["rows"]))
        results[name] = res
        print(f"{name}: {res['ok']}/{res['total']} in {res['latency_ms']} ms; checks {res.get('checks', {})}")
        for r in res["rows"]:
            if not r["ok"]:
                print("  miss:", r)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
