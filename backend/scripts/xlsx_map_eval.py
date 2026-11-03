"""Unregistered inspection XLSX mapping (spec v5.14 §29 acceptance): rules alone against the AI proposal on the same
synthetic samples (scripts/xlsx_samples.py, gold written before any run), and the full demo flow. Run from backend/:

    python -m scripts.xlsx_map_eval collect --double | --live   one proposal per sample; trace in .eval_data (LIVE paid:
                                                                 --live plus QO_EVAL_LIVE_BUDGET_USD)
                                       [--protected]           headers masked as for a protected file
    python -m scripts.xlsx_map_eval score                        offline from the saved traces -> docs/evaluations/ev
    python -m scripts.xlsx_map_eval demo --double | --live       upload -> rules fail -> proposal -> a person checks the
                                                                 original cells -> saved -> a second file reuses it

Metrics, per arm, over the required fields (lot, inspected_qty, defective_qty) of every sample:
- required accuracy: the proposed column equals the gold one (gold "none" is right only when nothing is mapped);
- hold rate: required fields left for a person (unresolved, uncertain, or unmapped);
- edits: required fields a person must change to reach the gold mapping.
TEST_DOUBLE (a scripted proposer) checks the pipeline only and is never pooled with LIVE.
"""

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

from app import inspection_layout as lay
from app import inspection_xlsx as ix
from app.model_provider import ProviderError
from scripts import evalkit
from scripts.xlsx_samples import DEMO_A, DEMO_B, samples

TRACES = evalkit.DATA_DIR / "xlsx_map" / "traces"
REQ = ix.REQUIRED


class Double:
    """TEST_DOUBLE: maps by the built-in header words on the first candidate (what a careful rule would do)."""
    mode, model = "TEST_DOUBLE", "scripted-rules"

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        c = json.loads(messages[-1]["content"])["candidates"][0]
        got = ix.suggest({x["column"]: x["header"] for x in c["columns"]})
        return {"message": {"content": json.dumps({"candidate_id": c["id"], "unresolved": [k for k in REQ if not got[k]],
                                                   "fields": [{"field": k, "column": got[k] or "NONE", "reason": "words"}
                                                              for k in ix.FIELDS]})}, "usage": {}}


class Recorded:
    def __init__(self, rec):
        self.rec, self.mode, self.model = rec, rec["mode"], rec["model"]

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        if self.rec.get("error"):
            raise ProviderError(self.rec["error"])
        return {"message": {"content": self.rec["content"]}, "usage": self.rec.get("usage") or {}}


class Recorder:
    def __init__(self, inner):
        self.inner, self.mode, self.model, self.rec = inner, inner.mode, inner.model, {}

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        t0 = time.perf_counter()
        try:
            r = self.inner.chat(messages, tools, response_format, reasoning_effort)
        except ProviderError as exc:
            self.rec = {"error": str(exc), "seconds": round(time.perf_counter() - t0, 2)}
            raise
        self.rec = {"content": r["message"].get("content"), "usage": r.get("usage") or {},
                    "request_sha256": evalkit.sha256_json([messages, response_format]),
                    "seconds": round(time.perf_counter() - t0, 2)}
        return r


def provider_of(args):
    if "--double" in args:
        return Double(), 0.0, None
    return evalkit.live_gate(args)


def collect(args) -> int:
    provider, budget, why = provider_of(args)
    if provider is None:
        print("NOT_RUN:", why)
        return 2
    TRACES.mkdir(parents=True, exist_ok=True)
    protected = "--protected" in args  # headers masked as for a file not approved for external use
    mode = ("MASKED_" if protected else "") + provider.mode
    out = TRACES / f"{mode}-{evalkit.now().replace(':', '')}.jsonl"
    spent = 0.0
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"header": evalkit.run_info("scripts.xlsx_map_eval", run_mode=provider.mode,
                                                       model=provider.model, budget_usd=budget)}) + "\n")
        for s in samples():
            if provider.mode == "LIVE" and spent + 0.05 > budget:  # DERIVED: a proposal is ~2k tokens, far below
                print(f"STOPPED: budget {budget} USD (spent {spent:.3f})")
                break
            rec = Recorder(provider)
            res = lay.propose(rec, lay.tables(s["data"]), protected=protected)
            spent += evalkit.cost_usd(rec.rec.get("usage") or {})
            f.write(json.dumps({"sample": s["name"], "mode": provider.mode, "model": provider.model,
                                "protected": protected, **rec.rec},
                               ensure_ascii=False) + "\n")
            print(s["name"], res["status"], f"spent {spent:.4f} USD")
    print("trace", out)
    return 0


def judge(s: dict, cands: list[dict], table: str | None, mapping: dict, held: set[str]) -> dict:
    gold = s["gold"]
    c = next((t for t in cands if t["id"] == table), None)
    right_table = bool(c) and c["range"].startswith(gold["table"])
    right = {k: right_table and (mapping.get(k) or None) == gold[k] for k in REQ}
    return {"right_table": right_table, "correct": sum(right.values()), "held": len(held & set(REQ)),
            "edits": sum(not v for v in right.values()),
            "wrong": {k: mapping.get(k) for k in REQ if not right[k]}}


def rules(s: dict) -> dict:
    """Rules alone: the route; a FORM route maps by the form, otherwise the built-in words on the first candidate."""
    cands = lay.tables(s["data"])
    r = lay.route(cands, [ix.BUILTIN])
    table = r["table"] or (cands[0]["id"] if cands else None)
    c = next((t for t in cands if t["id"] == table), None)
    mapping = ix.suggest(c["columns"]) if c else {}
    held = {k for k in REQ if not mapping.get(k)} if r["route"] != "FORM" else set()
    return {"route": r["route"], "reasons": [x["code"] for x in r["reasons"]], **judge(s, cands, table, mapping, held)}


def ai(s: dict, rec: dict) -> dict:
    cands = lay.tables(s["data"])
    res = lay.propose(Recorded(rec), cands, protected=rec.get("protected", False))
    p = res["proposal"]
    if not p:
        return {"status": res["status"], "issues": [i["code"] for i in res["issues"]],
                **judge(s, cands, None, {}, set(REQ))}
    c = next(t for t in cands if t["id"] == p["table"])
    asked = {x["field"] for x in lay.uncertain(c, p["mapping"], s["data"], p["unresolved"])}
    held = asked | set(p["unresolved"]) | {k for k in REQ if not p["mapping"].get(k)}
    return {"status": res["status"], "issues": [i["code"] for i in res["issues"]],
            **judge(s, cands, p["table"], p["mapping"], held), "usage": rec.get("usage") or {}}


def totals(rows: list[dict], arm: str) -> dict:
    n = len(rows) * len(REQ)
    xs = [r[arm] for r in rows]
    return {"samples": len(rows), "required_fields": n,
            "required_accuracy": round(sum(x["correct"] for x in xs) / n, 3) if n else None,
            "hold_rate": round(sum(x["held"] for x in xs) / n, 3) if n else None,
            "edits": sum(x["edits"] for x in xs), "right_table": sum(x["right_table"] for x in xs),
            "failed_samples": {r["sample"]: x["wrong"] for r, x in zip(rows, xs) if x["wrong"]}}


def score(args) -> int:
    by = {s["name"]: s for s in samples()}
    done = 0
    for mode in ("LIVE", "TEST_DOUBLE", "MASKED_LIVE", "MASKED_TEST_DOUBLE"):
        paths = sorted(TRACES.glob(f"{mode}-*.jsonl")) if TRACES.exists() else []
        if not paths:
            continue
        p = paths[-1]  # the latest collection of this mode; earlier ones stay in .eval_data
        lines = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        with evalkit.no_network():
            rows = [{"sample": r["sample"], "rules": rules(by[r["sample"]]), "ai": ai(by[r["sample"]], r)}
                    for r in lines[1:]]
        cost = sum(evalkit.cost_usd(r["ai"].get("usage") or {}) for r in rows)
        summary = {"run_mode": mode, "trace": p.name, "collected": lines[0]["header"],
                   "rules_alone": totals(rows, "rules"), "ai_proposal": totals(rows, "ai"),
                   "cost_usd": round(cost, 4), "gold": "scripts/xlsx_samples.py (written before any run)",
                   "not_evaluated": ["review time (needs people)", "real company files (none provided)"],
                   "scored": evalkit.run_info("scripts.xlsx_map_eval")}
        print(evalkit.write_report(f"xlsx_map_eval_{mode}", summary, rows))
        print(mode, json.dumps({k: {m: summary[k][m] for m in ("required_accuracy", "hold_rate", "edits")}
                                for k in ("rules_alone", "ai_proposal")}))
        done += 1
    if not done:
        print("NOT_RUN: no saved traces")
        return 2
    return 0


def demo(args) -> int:
    """The §29 flow through the real HTTP API in-process. The person's part is scripted: they compare each asked
    field with the original cells and correct it to the gold column (counted as an edit) or confirm it."""
    import base64

    from fastapi.testclient import TestClient

    from app.db import Base
    from app.intake import FIXTURE_DIR
    from app.main import create_app
    from tests.v5_util import H

    provider, _, why = provider_of(args)
    if provider is None:
        print("NOT_RUN:", why)
        return 2
    gold = {"lot": "A", "inspected_on": "B", "inspected_qty": "C", "defective_qty": "E"}
    app = create_app(f"sqlite:///{Path(tempfile.mkdtemp()) / 'demo.db'}", provider)
    Base.metadata.create_all(app.state.engine)
    c = TestClient(app)
    steps = []

    def ok(r, code=(200, 201)):
        assert r.status_code in code, r.text
        return r.json()

    def up(name):
        b = base64.b64encode((FIXTURE_DIR / name).read_bytes()).decode()
        x = ok(c.post("/intakes", headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex},
                      json={"files": [{"name": name, "content_base64": b}]}))
        return x["intake_id"], x["files"][0]["file_id"], x["files"][0]["data_origin"]

    ok(c.post("/cases", json={"case_id": "DEMO-29"}, headers=H("alice")))
    iid, fid, origin = up(DEMO_A)
    v = ok(c.get(f"/intakes/{iid}/files/{fid}/inspection", headers=H("alice")))
    steps.append({"step": "1 upload unregistered A", "data_origin": origin, "route": v["layout"]["route"],
                  "reasons": [r["code"] for r in v["layout"]["reasons"]], "rule_mapping": v["mapping"]})
    t0 = time.perf_counter()
    p = ok(c.post(f"/intakes/{iid}/files/{fid}/inspection/proposals", headers=H("alice")))
    prop = p["proposal"] or {}
    steps.append({"step": "2 AI proposal", "status": p["status"], "mode": p["mode"], "model": p["model"],
                  "seconds": round(time.perf_counter() - t0, 1), "table": prop.get("table"),
                  "mapping": prop.get("mapping"), "reasons": prop.get("reasons"), "issues": p["issues"]})
    asked = p["preview"]["layout"]["uncertain"]
    mapping = dict(prop.get("mapping") or {})
    edits = [k for k in gold if mapping.get(k) != gold[k]]
    mapping.update(gold)
    steps.append({"step": "3 person compares original cells", "asked": [
        {"field": a["field"], "column": a["column"], "header": a["header"], "why": a["why"],
         "side_by_side": [[x["header"]] + [f"{y['cell']}={y['raw']}" for y in x["cells"]] for x in a["context"]]}
        for a in asked], "edited_fields": edits,
        "first_row": {k: p["preview"]["rows"][0]["cells"].get(k) for k in gold} if p["preview"]["rows"] else None})
    table = prop.get("table") or p["preview"]["layout"]["table"]
    form = ok(c.post(f"/intakes/{iid}/files/{fid}/inspection/mapping",
                     headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex},
                     json={"table": table, "mapping": mapping, "confirmed": [a["field"] for a in asked],
                           "proposal_id": p["proposal_id"], "reason": "원본 셀과 대조해 확인 (데모)"}))
    steps.append({"step": "4 saved", "form": form["name"], "version": form["version"], "edits": form["edits"],
                  "structure_sha": form["structure_sha"][:12]})

    def into_case(iid, fid, v):
        return ok(c.post("/cases/DEMO-29/inspection-imports", headers={"X-User": "alice",
                                                                      "Idempotency-Key": uuid.uuid4().hex},
                         json={"intake_id": iid, "file_id": fid, "file_sha256": v["file_sha256"], "sheet": v["sheet"],
                               "header_row": v["header_row"], "mapping": v["mapping"],
                               "include_rows": [x["row"] for x in v["rows"]], "form": v["form"]["name"]}))
    va = ok(c.get(f"/intakes/{iid}/files/{fid}/inspection", headers=H("alice")))
    ia = into_case(iid, fid, va)
    iid2, fid2, _ = up(DEMO_B)
    vb = ok(c.get(f"/intakes/{iid2}/files/{fid2}/inspection", headers=H("alice")))
    ib = into_case(iid2, fid2, vb)
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.db import InspectionMappingProposal
    with Session(app.state.engine) as s:
        proposals = s.scalar(select(func.count()).select_from(InspectionMappingProposal))
    steps.append({"step": "5 second file B (same structure, other values)", "route": vb["layout"]["route"],
                  "form": vb["form"]["name"], "same_mapping": vb["mapping"] == va["mapping"],
                  "ai_proposals_total": proposals,
                  "lots_A": [x["values"]["lot"] for x in va["rows"]], "lots_B": [x["values"]["lot"] for x in vb["rows"]],
                  "defective_A": [x["values"]["defective_qty"] for x in va["rows"]],
                  "defective_B": [x["values"]["defective_qty"] for x in vb["rows"]],
                  "imports": [ia["import_id"], ib["import_id"]],
                  "evidence_B": ib["evidence_ids"]})
    out = {"run_mode": provider.mode, "model": provider.model, "steps": steps,
           "person": "scripted: corrects each field to the gold column after comparing the cells",
           "run": evalkit.run_info("scripts.xlsx_map_eval", step="demo")}
    path = evalkit.EVAL_DIR / "ev" / f"xlsx_demo_{provider.mode}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
    for st in steps:
        print(json.dumps(st, ensure_ascii=False, default=str)[:400])
    print(path)
    return 0


def main() -> int:
    cmd, *args = sys.argv[1:] or ["help"]
    return {"collect": collect, "score": score, "demo": demo}.get(cmd, lambda _: print(__doc__) or 2)(args)


if __name__ == "__main__":
    sys.exit(main())
