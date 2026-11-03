"""Spec v5.15 §30 demo through the real HTTP API in-process: customer DOCX forms (register -> proposal -> preview ->
confirm -> export, two forms on one case, reuse on another case, a changed form) and a held defect rate (question ->
answer by a typed number and by an original cell -> source check -> resume). Run from backend/:

    python -m scripts.v515_demo --double                     scripted proposals (pipeline check)
    QO_EVAL_LIVE_BUDGET_USD=0.3 python -m scripts.v515_demo --live    Meta proposes (paid; a few calls)

Only the AI steps call the model (slot mapping, where a missing value could be); the case is built with the model
switched off. The person's part is scripted: they compare each proposed slot with the gold mapping written in
scripts/docx_samples.py and correct it (counted as an edit). Report: docs/evaluations/ev/v515_demo_<MODE>.json.
"""

import base64
import io
import json
import sys
import tempfile
import uuid
from pathlib import Path

import docx

from app.intake import FIXTURE_DIR
from app.model_provider import ProviderError
from scripts import evalkit
from scripts.docx_samples import FORMS, gold_paragraph, gold_table
from scripts.xlsx_samples import book


class Gate:
    """The app's provider: off while the case is built (no paid call), on for the AI steps."""

    def __init__(self, inner):
        self.inner, self.on, self.mode, self.model, self.calls = inner, False, inner.mode, inner.model, []

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        if not self.on:
            raise ProviderError("model off while the demo builds its case")
        r = self.inner.chat(messages, tools, response_format, reasoning_effort)
        self.calls.append(r.get("usage") or {})
        return r


class Double:
    mode, model = "TEST_DOUBLE", "scripted-gold-with-one-swap"

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        body = json.loads(messages[-1]["content"])
        if "slots" in body:
            ids = [s["id"] for s in body["slots"]]
            gold = gold_table() if ids[0].startswith("T") else gold_paragraph()
            pairs = [(s, gold.get(s) or "NONE") for s in ids]
            pairs = [(s, "d4.occurrence_cause" if f == "d4.escape_cause" else f) for s, f in pairs]  # one mistake
            return {"message": {"content": json.dumps({"slots": [{"slot_id": s, "field_id": f, "reason": "label"}
                                                                 for s, f in pairs], "unresolved": []})}, "usage": {}}
        col = next(c["id"] for s in body["sources"] for t in s["tables"] for c in t["columns"] if "검사" in c["header"])
        return {"message": {"content": json.dumps({"candidates": [{"source_id": col, "reason": "header"}]})},
                "usage": {}}


def main(args) -> int:
    from tests.test_c_e2e import success
    from tests.test_intake_in1 import own_pdf, upload
    from tests.v5_util import H, confirmed_cause, line_client

    if "--double" in args:
        inner = Double()
    else:
        inner, _, why = evalkit.live_gate(args)
        if inner is None:
            print("NOT_RUN:", why)
            return 2
    gate = Gate(inner)
    c = line_client(Path(tempfile.mkdtemp()), provider=gate)
    success(c)
    confirmed_cause(c, text="AOI program did not flag low-volume joints on L02", category="METHOD",
                    cause_type="NON_DETECTION")
    steps = []

    def ok(r, codes=(200, 201)):
        assert r.status_code in codes, r.text
        return r.json()

    def K():
        return {"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex}

    def reg(fname):
        cust, name, _ = FORMS[fname]
        return ok(c.post("/customer-templates", headers=K(), json={
            "customer": cust, "name": name, "reason": "고객 양식 수령 (데모)",
            "content_base64": base64.b64encode((FIXTURE_DIR / fname).read_bytes()).decode()}))

    accuracy = []
    for fname, gold in (("customer_form_A_8d_table.docx", gold_table()),
                        ("customer_form_B_reply_paragraph.docx", gold_paragraph())):
        t = reg(fname)
        gate.on = True
        p = ok(c.post(f"/customer-templates/{t['template_id']}/proposals", headers=H("alice")))
        gate.on = False
        prop = (p["proposal"] or {}).get("mapping", {})
        wrong = {s: prop.get(s) for s in gold if prop.get(s) != gold[s]}
        accuracy.append({"form": fname, "slots": len(gold), "correct": len(gold) - len(wrong), "wrong": wrong,
                         "unresolved": (p["proposal"] or {}).get("unresolved", [])})
        m = ok(c.post(f"/customer-templates/{t['template_id']}/mapping", headers=K(), json={
            "mapping": gold, "proposal_id": p["proposal_id"], "reason": "원본 칸과 출처 대조 (데모)"}))
        v = ok(c.get(f"/cases/L/customer-templates/{t['template_id']}/preview", headers=H("alice")))
        r = c.get(f"/cases/L/customer-templates/{t['template_id']}/export", params={"mode": "final"},
                  headers=H("alice"))
        d = docx.Document(io.BytesIO(r.content)) if r.status_code == 200 else None
        steps.append({"step": f"DOCX {t['name']}", "slots": len(t["slots"]), "route_at_register": t["route"],
                      "proposal": {"status": p["status"], "mode": p["mode"], "model": p["model"], "wrong": wrong},
                      "mapping_version": m["version"], "edits": m["edits"],
                      "preview": [[s["label"], s["field"], s["status"], (s["value"] or "")[:60], s["source"]]
                                  for s in v["slots"]],
                      "final": {"status": r.status_code, "sha256": r.headers.get("x-file-sha256"),
                                "mapping_version": r.headers.get("x-mapping-version"),
                                "case_data_version": r.headers.get("x-case-data-version"),
                                "first_lines": [p.text for p in d.paragraphs][:3] if d else r.text[:200]}})

    a = reg("customer_form_A_8d_table.docx")  # the same file again: the same version, confirmed mapping
    up = upload(c, [("customer.pdf", own_pdf())]).json()
    iid = up["intake_id"]
    c.post(f"/intakes/{iid}/analyze", headers=H("alice"))
    c.post(f"/intakes/{iid}/draft/edits", headers=H("alice"), json={"base_version": 1, "changes": [
        {"field": "customer", "value": "DEFAULT", "reason": "고객 확인"},
        {"field": "lot", "value": "LOT-NEW-42", "reason": "고객 확인"}]})
    new = ok(c.post(f"/intakes/{iid}/confirm", headers=K(), json={"base_version": 2, "action": "NEW_CASE"}))["case_id"]
    v = ok(c.get(f"/cases/{new}/customer-templates/{a['template_id']}/preview", headers=H("alice")))
    final = c.get(f"/cases/{new}/customer-templates/{a['template_id']}/export", params={"mode": "final"},
                  headers=H("alice"))
    v2 = reg("customer_form_A_8d_table_v2.docx")
    other = reg("customer_form_OTHER_8d.docx")
    steps.append({"step": "reuse on another case, form change, other customer",
                  "new_case": new, "route": a["route"],
                  "values": {s["label"]: s["shown"] for s in v["slots"]},
                  "final_on_new_case": [final.status_code, final.json().get("detail", "")[:160]],
                  "changed_form": [v2["version"], v2["route"]],
                  "other_customer_preview": c.get(f"/cases/L/customer-templates/{other['template_id']}/preview",
                                                  headers=H("alice")).status_code})

    # §30.2: LOT 0007, 3 defective, no inspected quantity
    up = upload(c, [("complaint.pdf", own_pdf(b"0007")), ("inspection.xlsx", book({"검사": [
        ["LOT", "검사 수량", "불량 수량"], ["0007", 120, 3], ["0008", 200, 1]]}))]).json()
    iid, xlsx = up["intake_id"], up["files"][1]["file_id"]
    c.post(f"/intakes/{iid}/analyze", headers=H("alice"))
    c.post(f"/intakes/{iid}/draft/edits", headers=H("alice"), json={"base_version": 1, "changes": [
        {"field": "lot", "value": "0007", "reason": "고객 문서"}, {"field": "defective_qty", "value": "3",
                                                                  "reason": "고객 문서"}]})
    case = ok(c.post(f"/intakes/{iid}/confirm", headers=K(), json={"base_version": 2, "action": "NEW_CASE"}))["case_id"]
    req = ok(c.post(f"/cases/{case}/calculations/held", headers=K(), json={"lot": "0007", "period": "2026-10"}))
    gate.on = True
    sug = ok(c.post(f"/input-requests/{req['request_id']}/suggestions", headers=H("alice")))
    gate.on = False
    bad = ok(c.post(f"/input-requests/{req['request_id']}/answers", headers=K(),
                    json={"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "B3"}))
    ans = ok(c.post(f"/input-requests/{req['request_id']}/answers", headers=K(),
                    json={"kind": "SOURCE_CELL", "file_id": xlsx, "sheet": "검사", "cell": "B2"}))
    res = ok(c.post(f"/input-requests/{req['request_id']}/resume", headers=K()))
    again = ok(c.post(f"/input-requests/{req['request_id']}/resume", headers=K()))
    steps.append({"step": "held defect rate LOT 0007", "held": [req["status"], req["question"]],
                  "suggestion": {k: sug.get(k) for k in ("status", "mode", "model", "candidates")},
                  "wrong_row_answer": bad.get("rejected"), "answer": ans["status"],
                  "result": {"rate_percent": res["result"]["rate_percent"],
                             "calculation_id": res["result"]["calculation"]["calculation_id"],
                             "inputs": res["result"]["inputs"]},
                  "second_resume_same": again["result"]["calculation"]["calculation_id"]
                  == res["result"]["calculation"]["calculation_id"]})
    cost = sum(evalkit.cost_usd(u) for u in gate.calls)
    out = {"run_mode": inner.mode, "model": inner.model, "model_calls": len(gate.calls), "cost_usd": round(cost, 4),
           "docx_mapping_accuracy": accuracy, "steps": steps,
           "person": "scripted: corrects every proposed slot to the gold mapping", "run": evalkit.run_info(
               "scripts.v515_demo")}
    path = evalkit.EVAL_DIR / "ev" / f"v515_demo_{inner.mode}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps({"mode": inner.mode, "calls": len(gate.calls), "cost": round(cost, 4),
                      "accuracy": [(a["form"], a["correct"], a["slots"], a["wrong"]) for a in accuracy]},
                     ensure_ascii=False))
    for st in steps:
        print(json.dumps(st, ensure_ascii=False, default=str)[:600])
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
