"""Agent trajectory evaluation (spec §26.4, §26.7): AgentEvals' deterministic matchers over the recorded steps, plus
code checks of what the matcher cannot see (an earlier result's id/version used by the next call, the final state
re-read from the API, no false success). No LLM judge, no network. Run from backend/:

    python -m scripts.agent_eval            writes docs/evaluations/ev/agent_eval.{json,csv,html}

Two things are evaluated apart (spec §26.4):
  FIXED_SERVER   the Agent-First run with the server planner (SERVER_RULES): the server picks the tools from fixed
                 rules, so a pass shows the workflow branches correctly, not that a model plans
  MODEL_LOOP     the investigation loop where the model picks the next tool (app/investigator.py). Here only with
                 a TEST_DOUBLE (scripted replies): it checks the adapter and the server's checks, never model skill.
                 A LIVE run of the loop is NOT_RUN (no trace was collected under an approved budget)
Each pair is one request with one tool result changed; the expected change in the next action is written down
before the run (EXPECT). The document reading is fixed (a scripted extraction), so its errors cannot leak in here.
"""

import json
import sys
import tempfile
import uuid
from pathlib import Path

from scripts import evalkit

# Matching policy: independent reads may come in any order (superset: the required ones must be there, extra ones are
# counted, not failed); writes must come in order with exact arguments (strict).
EXPECT = {
    "approval_state": "no document -> create_draft then validate_document of that new version; an existing DRAFT -> "
                      "validate only, no new version; IN_REVIEW -> no write, wait for the reviewer; REJECTED -> a new "
                      "version; APPROVED D2 -> the next document (containment)",
    "permission": "a REVIEWER asking for a draft: create_draft is DENIED by the route, the run is BLOCKED, no document",
    "stale": "the document changed after the question: the confirmed review request is not sent (BLOCKED, no Review)",
    "tool_failure": "one read fails: the step is recorded ERROR, the other reads still run, no reply line cites it",
    "duplicate": "the same Idempotency-Key: the same run, no second step or document",
    "intake_conflict": "an extraction whose LOTs disagree: confirming a case is refused until a person resolves it; "
                       "a consistent extraction makes one case; a stale draft version is refused",
    "inspection": "AOI FAIL without a human decision is UNKNOWN, never 'no defect'; a human DEFECT_CONFIRMED changes "
                  "the proposed D0 route",
    "model_loop_tool_error": "TEST_DOUBLE: a tool error is recorded ok=false and evidence it never returned cannot "
                             "be cited (report not VALIDATED)",
}


# ---- adapter: recorded steps -> OpenAI-style messages (what AgentEvals reads) ----
def messages(calls: list[tuple[str, dict, str]]) -> list[dict]:
    """[(tool, args, status)] -> one assistant tool call and one tool result per call."""
    out = []
    for i, (tool, args, status) in enumerate(calls):
        out += [{"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function", "function": {
            "name": tool, "arguments": json.dumps(args, sort_keys=True)}}]},
                {"role": "tool", "tool_call_id": f"c{i}", "content": status}]
    return out


def from_steps(steps: list[dict], kind: str | None = None) -> list[dict]:
    """AgentStep rows (run output) -> messages; kind keeps READ or WRITE steps only."""
    return messages([(s["tool"], s["args"], s["status"]) for s in steps if kind is None or s["kind"] == kind])


def from_tool_calls(calls) -> list[dict]:
    """ToolCall rows of a ModelRun (the model loop) -> messages."""
    return messages([(c.tool_name, json.loads(c.arguments_json or "{}"), "OK" if c.ok else "ERROR") for c in calls])


def match(outputs: list[dict], reference: list[dict], mode: str, args: str = "exact") -> bool:
    from agentevals.trajectory.match import create_trajectory_match_evaluator

    ev = create_trajectory_match_evaluator(trajectory_match_mode=mode, tool_args_match_mode=args)
    return bool(ev(outputs=outputs, reference_outputs=reference)["score"])


def judge(steps: list[dict], reads: list[str], writes: list[tuple[str, dict]], forbidden: list[str]) -> dict:
    tools = [s["tool"] for s in steps]
    return {"reads_superset": match(from_steps(steps, "READ"), messages([(t, {}, "OK") for t in reads]),
                                    "superset", "ignore"),
            "writes_strict": match(from_steps(steps, "WRITE"), messages([(t, a, "OK") for t, a in writes]), "strict"),
            "forbidden_absent": not set(tools) & set(forbidden)}


# ---- scenarios: each returns rows {pair, variant, workflow, steps, checks} ----
def sub(tmp: Path, name: str) -> Path:
    (tmp / name).mkdir(parents=True, exist_ok=True)
    return tmp / name


def row(pair: str, variant: str, out: dict | None, checks: dict, workflow: str = "FIXED_SERVER",
        run_mode: str = "OFFLINE_REAL_CODE", **extra) -> dict:
    steps = (out or {}).get("steps", [])
    return {"pair": pair, "variant": variant, "workflow": workflow, "run_mode": run_mode,
            "status": (out or {}).get("status"), "steps": [f"{s['tool']}:{s['status']}" for s in steps],
            "repeated_calls": len(steps) - len({(s["tool"], json.dumps(s["args"], sort_keys=True)) for s in steps}),
            "checks": checks, "pass": all(checks.values()), **extra}


def approval_state(tmp: Path) -> list[dict]:
    from app.db import DocumentVersion
    from tests.test_agent_ag3 import count, d0_d1, resume, run
    from tests.v5_util import H, line_client, ok

    c = line_client(sub(tmp, "a"))
    d0_d1(c)
    rows = []
    first = run(c, "8D 초안 써 줘").json()
    made = next(s for s in first["steps"] if s["tool"] == "create_draft")
    rows.append(row("approval_state", "no_document", first, {
        **judge(first["steps"], ["case_summary", "stages"], [("create_draft", {"kind": "ncr"}),
                                                           ("validate_document", {"kind": "ncr", "version": 1})],
                ["request_review"]),
        "validate_uses_created_version": next(s for s in first["steps"] if s["tool"] == "validate_document")[
            "args"]["version"] == made["result"]["version"],
        "pending_names_that_version": first["pending"]["version"] == made["result"]["version"],
        "state_one_draft": [d["status"] for d in c.get("/cases/L/ncr", headers=H("alice")).json()] == ["DRAFT"]}))
    again = run(c, "8D 초안 써 줘").json()
    rows.append(row("approval_state", "draft_exists", again, {
        **judge(again["steps"], ["case_summary", "stages"], [("validate_document", {"kind": "ncr", "version": 1})],
                ["create_draft"]), "state_still_one_version": count(c, DocumentVersion) == 1}))
    resume(c, again, reviewer_id="bob")
    waiting = run(c, "8D 초안 써 줘").json()
    rows.append(row("approval_state", "in_review", waiting, {
        **judge(waiting["steps"], ["case_summary", "stages"], [], ["create_draft", "validate_document"]),
        "waits_for_the_reviewer": waiting["status"] == "NEEDS_HUMAN" and waiting["pending"]["action"] == "await"
        and waiting["pending"]["owner"] == "bob",
        "state_in_review": c.get("/cases/L/ncr/1", headers=H("alice")).json()["status"] == "IN_REVIEW"}))
    d = c.get("/cases/L/ncr/1", headers=H("bob")).json()
    ok(c.post("/cases/L/ncr/1/decision", headers=H("bob"),
              json={"decision": "REJECT", "comment": "근거 보완", "content_sha256": d["content_sha256"]}), 200)
    redo = run(c, "8D 초안 써 줘").json()
    made = next((s for s in redo["steps"] if s["tool"] == "create_draft"), {"result": {}})
    rows.append(row("approval_state", "rejected", redo, {
        **judge(redo["steps"], ["case_summary", "stages"], [("create_draft", {"kind": "ncr"}),
                                                          ("validate_document", {"kind": "ncr", "version": 2})], []),
        "new_version_from_the_create_result": made["result"].get("version") == 2,
        "state_v1_stays_rejected": c.get("/cases/L/ncr/1", headers=H("alice")).json()["status"] == "REJECTED"}))
    resume(c, redo, reviewer_id="bob")
    d = c.get("/cases/L/ncr/2", headers=H("bob")).json()
    ok(c.post("/cases/L/ncr/2/decision", headers=H("bob"),
              json={"decision": "APPROVE", "comment": "ok", "content_sha256": d["content_sha256"]}), 200)
    nxt = run(c, "8D 초안 써 줘").json()
    rows.append(row("approval_state", "approved", nxt, {
        **judge(nxt["steps"], ["case_summary", "stages"], [("create_draft", {"kind": "containment"}),
                                                         ("validate_document", {"kind": "containment",
                                                                                "version": 1})], []),
        "approved_ncr_untouched": c.get("/cases/L/ncr/2", headers=H("alice")).json()["status"] == "APPROVED"}))
    return rows


def permission(tmp: Path) -> list[dict]:
    from app.db import DocumentVersion
    from tests.test_agent_ag3 import count, run
    from tests.v5_util import line_client

    c = line_client(sub(tmp, "p"))
    out = run(c, "8D 초안 써 줘", user="bob").json()
    draft = next((s for s in out["steps"] if s["tool"] == "create_draft"), {})
    return [row("permission", "reviewer_asks_for_a_draft", out, {
        "create_draft_denied_by_route": draft.get("status") == "DENIED" and draft.get("http_status") == 403,
        "run_blocked": out["status"] == "BLOCKED",
        "no_success_claimed": not any("저장됨" in x["text"] for x in out["reply"]),
        "state_no_document": count(c, DocumentVersion) == 0})]


def stale(tmp: Path) -> list[dict]:
    from app.db import Review
    from tests.test_agent_ag3 import count, resume, run
    from tests.v5_util import H, line_client, ok

    c = line_client(sub(tmp, "s"))
    out = run(c, "8D 초안 써 줘").json()
    asked = out["pending"]["version"]
    ok(c.post("/cases/L/ncr", json={}, headers=H("alice")))  # the author makes v2 meanwhile
    late = resume(c, out, reviewer_id="bob").json()
    return [row("stale", "document_changed_after_the_question", late, {
        "asked_version_was_1": asked == 1, "blocked_as_stale": late["status"] == "BLOCKED"
        and "stale" in late["reply"][-1]["text"], "state_no_review": count(c, Review) == 0,
        "state_v2_still_draft": c.get("/cases/L/ncr/2", headers=H("alice")).json()["status"] == "DRAFT"})]


def tool_failure(tmp: Path) -> list[dict]:
    from app.tools import EvidenceTools, ToolError
    from tests.test_agent_ag3 import run
    from tests.v5_util import line_client

    reads = ["case_summary", "data_integrity", "spc", "predictions", "evidence_gaps", "experience", "history",
             "references", "queue"]
    rows = []
    for variant in ("normal", "data_integrity_fails"):
        c = line_client(sub(tmp, variant))
        real = EvidenceTools.check_data_integrity
        if variant != "normal":
            def broken(self):
                raise ToolError("integrity store unavailable")
            EvidenceTools.check_data_integrity = broken
        try:
            out = run(c, "불량 원인 조사해 줘").json()
        finally:
            EvidenceTools.check_data_integrity = real
        failed = [s["seq"] for s in out["steps"] if s["status"] != "OK"]
        rows.append(row("tool_failure", variant, out, {
            **judge(out["steps"], reads, [], ["create_draft", "validate_document"]),
            "failure_recorded": failed == ([] if variant == "normal" else [2]),
            "no_reply_line_cites_a_failed_step": not any(set(x.get("steps", [])) & set(failed) and
                                                         "실패" not in x["text"] for x in out["reply"])}))
    return rows


def duplicate(tmp: Path) -> list[dict]:
    from app.db import AgentStep, DocumentVersion
    from tests.test_agent_ag3 import count
    from tests.v5_util import line_client

    c = line_client(sub(tmp, "d"))
    h = {"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex}
    a = c.post("/agent/runs", json={"case_id": "L", "goal": "8D 초안 써 줘"}, headers=h).json()
    steps = count(c, AgentStep)
    b = c.post("/agent/runs", json={"case_id": "L", "goal": "8D 초안 써 줘"}, headers=h).json()
    return [row("duplicate", "same_idempotency_key", b, {
        "same_run": a["run_id"] == b["run_id"], "state_no_new_step": count(c, AgentStep) == steps,
        "state_one_document": count(c, DocumentVersion) == 1})]


def intake_conflict(tmp: Path) -> list[dict]:
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from app.db import QualityCase
    from tests.test_intake_in2 import Scripted, analyze, client, extraction, f, two_files
    from tests.test_intake_in3 import confirm, resolve

    def cases(c):
        with Session(c.app.state.engine) as s:
            return s.scalar(select(func.count()).select_from(QualityCase))

    rows = []
    # conflict: the fixed extraction gives L02 (complaint table) and L03 (supplement); a relative deadline as well
    p = Scripted()
    c = client(sub(tmp, "conflict"), p)
    iid, pdf_id, docx_id = two_files(c)
    p.replies.append(extraction(pdf_id, docx_id))
    draft = analyze(c, iid).json()["draft"]
    refused = confirm(c, iid, draft["version"])
    fixed = resolve(c, iid, draft["version"])
    old = confirm(c, iid, draft["version"])
    made = confirm(c, iid, fixed)
    lots = _reported_lots(c, made.json().get("case_id"))
    rows.append(row("intake_conflict", "lot_conflict", None, {
        "draft_shows_conflict": draft["fields"]["lot"]["status"] == "CONFLICT",
        "confirm_refused_before_resolution": refused.status_code == 409,
        "stale_version_refused": old.status_code == 409,
        "confirm_after_resolution": made.status_code == 201 and cases(c) == 1,
        "state_case_uses_the_resolved_lot": lots == ["L02"]},
        http=[refused.status_code, old.status_code, made.status_code], reported_lots=lots))
    # consistent: the complaint alone (L02 everywhere), the same request
    p = Scripted()
    c = client(sub(tmp, "consistent"), p)
    iid, pdf_id, _ = two_files(c)
    p.replies.append({"documents": [{"file_id": pdf_id, "classes": ["COMPLAINT"], "needs_confirmation": False}],
                      "fields": [f("lot", "L02", ("pdf:p1:t1:r2:c1", "L02")),
                                 f("customer_ref", "HM-CC-2026-0417", ("pdf:p1:l3", "HM-CC-2026-0417"))],
                      "links": [], "questions": [], "transcriptions": [], "need": []})
    draft = analyze(c, iid).json()["draft"]
    made = confirm(c, iid, draft["version"])
    again = confirm(c, iid, draft["version"])  # the person clicks twice
    kinds = {e["classification"] for e in _evidence(c, made.json().get("case_id"))}
    rows.append(row("intake_conflict", "lot_consistent", None, {
        "draft_lot_found": draft["fields"]["lot"]["status"] == "FOUND",
        "confirm_makes_one_case": made.status_code == 201 and cases(c) == 1,
        "second_confirm_no_second_case": cases(c) == 1 and again.status_code in (200, 201, 409),
        "state_evidence_is_customer_reported": bool(kinds) and kinds <= {"CUSTOMER_REPORTED", "HYPOTHESIS"}},
        http=[made.status_code, again.status_code], evidence_kinds=sorted(kinds)))
    return rows


def _reported_lots(c, case_id) -> list[str]:
    """The LOT values the new case stores as customer-reported rows, re-read from the database."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import SourceEvent

    if not case_id:
        return []
    with Session(c.app.state.engine) as s:
        rows = [json.loads(e.raw_json) for e in s.scalars(select(SourceEvent).where(SourceEvent.case_id == case_id))]
    return sorted({str(r.get("value")) for r in rows if r.get("field") == "lot"})


def _evidence(c, case_id) -> list[dict]:
    """The case's evidence as the API shows it after the write (re-read, not the confirm response)."""
    if not case_id:
        return []
    return c.get(f"/cases/{case_id}/evidence", headers={"X-User": "alice"}).json()


def inspection(tmp: Path) -> list[dict]:
    from app.tools import EvidenceTools
    from tests.test_agent_ag3 import run
    from tests.v5_util import H, line_client

    rows = []
    real = EvidenceTools.get_case_summary
    for variant in ("aoi_fail_no_human_decision", "human_defect_confirmed"):
        c = line_client(sub(tmp, variant))
        if variant == "aoi_fail_no_human_decision":  # same request; the summary tool returns no human decision
            # (the source route accepts only exact generated fixtures, so the tool result is what changes)
            EvidenceTools.get_case_summary = lambda self: {**real(self), "aoi_fail": [
                {**f, "human": None} for f in real(self)["aoi_fail"]]}
        try:
            out = run(c, "8D로 갈지 판정해 줘", user="bob").json()
            filled = c.post(f"/agent/runs/{out['run_id']}/resume", json={"token": out["pending"]["token"],
                                                                          "confirm": True}, headers=H("bob")).json()
        finally:
            EvidenceTools.get_case_summary = real
        prop = next((s["result"] for s in filled["steps"] if s["tool"] in ("propose_triage", "fill_triage")), None) or {}
        fields = prop.get("fields", {})
        want = {"aoi_fail_no_human_decision": ("UNKNOWN", "FULL_8D"),
                "human_defect_confirmed": ("DEFECT_CONFIRMED", "EMERGENCY_FULL_8D")}[variant]
        rows.append(row("inspection", variant, filled, {
            **judge(filled["steps"], ["case_summary", "spc", "stages"], [], ["create_draft"]),
            "observed_defect": fields.get("observed_defect") == want[0], "proposed_route": fields.get("route")
            == want[1], "not_submitted_by_agent": c.get("/cases/L/triage", headers=H("bob")).status_code != 200
            or not c.get("/cases/L/triage", headers=H("bob")).json()},
            proposed={k: fields.get(k) for k in ("observed_defect", "route", "severity")}))
    return rows


def model_loop_tool_error(tmp: Path) -> list[dict]:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db import ToolCall
    from app.investigator import investigate
    from tests.v5_util import line_client

    rows = []
    for variant in ("normal", "tool_error"):
        c = line_client(sub(tmp, f"m{variant}"))
        call = {"id": "t1", "function": {"name": "get_case_summary" if variant == "normal" else "get_evidence",
                                         "arguments": "{}" if variant == "normal" else "{\"evidence_ids\": 7}"}}
        report = {"summary": "s", "next_evidence_requests": [], "open_questions": [], "findings": [
            {"classification": "OBSERVED", "text": "x", "evidence_ids": ["EV-not-returned"], "value": None,
             "unit": None, "calc": None}]}

        class Double:  # TEST_DOUBLE: one tool call, then a report citing evidence no tool returned
            mode, model = "TEST_DOUBLE", "scripted"
            replies = [{"message": {"tool_calls": [call]}}, {"message": {"content": json.dumps(report)}}]  # noqa: RUF012

            def chat(self, messages, tools, response_format=None, reasoning_effort=None):
                return self.replies.pop(0)

        with Session(c.app_ref.state.engine) as s:
            run = investigate(s, "L", "alice", Double())
            calls = s.scalars(select(ToolCall).where(ToolCall.model_run_id == run.id)).all()
            traj = from_tool_calls(calls)
            rows.append(row("model_loop_tool_error", variant, None, {
                "adapter_round_trip": match(traj, traj, "strict"),
                "tool_status_recorded": [c_.ok for c_ in calls] == [variant == "normal"],
                "uncited_evidence_not_validated": run.status != "VALIDATED"},
                workflow="MODEL_LOOP", run_mode="TEST_DOUBLE", model_run_status=run.status))
    return rows


SCENARIOS = [approval_state, permission, stale, tool_failure, duplicate, intake_conflict, inspection,
             model_loop_tool_error]


def run_all(tmp: Path) -> list[dict]:
    rows = []
    for sc in SCENARIOS:
        try:
            rows += sc(tmp)
        except Exception as exc:  # noqa: BLE001 (a scenario that cannot run is a failure, never a pass)
            rows.append(row(sc.__name__, "could_not_run", None, {"ran": False}, error=f"{type(exc).__name__}: {exc}"))
    return rows


def main() -> int:
    with evalkit.no_network() as attempts:
        rows = run_all(Path(tempfile.mkdtemp()))
    from importlib.metadata import version

    import agentevals.trajectory.match as m
    summary = {"expected_changes": EXPECT, "variants": len(rows), "passed": sum(r["pass"] for r in rows),
               "failed": [f"{r['pair']}/{r['variant']}" for r in rows if not r["pass"]],
               "by_workflow": {w: f"{sum(r['pass'] for r in rows if r['workflow'] == w)}/"
                                  f"{sum(r['workflow'] == w for r in rows)}" for w in ("FIXED_SERVER", "MODEL_LOOP")},
               "model_loop_live": "NOT_RUN (no trace collected under an approved budget)",
               "matcher": f"agentevals {version('agentevals')} {m.__name__} (superset for reads, strict for writes)",
               "llm_judge": "none", "network_attempts": len(attempts), "model_calls": 0,
               "not_evaluated": [("whether the reply wording or a proposed investigation is sensible (fixed-rubric "
                                 "human review of a sample; not automated)")],
               "run": evalkit.run_info("scripts.agent_eval")}
    print(evalkit.write_report("agent_eval", summary, rows))
    print(summary["by_workflow"], "failed:", summary["failed"])
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())
