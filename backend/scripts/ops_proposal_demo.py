"""AI-CFG-04 demo (spec v5.14 §29) on measured data: the 40 investigation runs of the 2026-11-03 LIVE loop
evaluation (status, rounds, tool calls, seconds, tokens from docs/evaluations/ev/loop_eval_LIVE_v2_*T112722.json)
become the run records; Meta proposes limit changes; the server's replay is shown; gina approves the first valid one
through the API. Run from backend/:

    python -m scripts.ops_proposal_demo --double | --live          (LIVE: QO_EVAL_LIVE_BUDGET_USD; one call)
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from app import EVAL_DIR
from scripts import evalkit

SOURCE = EVAL_DIR / "ev" / "loop_eval_LIVE_v2_2026-11-03T112722.json"


class Double:
    mode, model = "TEST_DOUBLE", "scripted"

    def chat(self, messages, tools, response_format=None, reasoning_effort=None):
        return {"message": {"content": json.dumps({"proposals": [
            {"name": "INVESTIGATION_MAX_TOOL_CALLS", "value": 6, "reason": "runs use few tool calls"}]})}, "usage": {}}


def main(args) -> int:
    from sqlalchemy.orm import Session

    from app.db import ModelRun, ToolCall
    from tests.v5_util import H, line_client

    provider = Double() if "--double" in args else evalkit.live_gate(args)[0]
    if provider is None:
        print("NOT_RUN:", evalkit.live_gate(args)[2])
        return 2
    c = line_client(Path(tempfile.mkdtemp()), provider=provider)
    rows = json.loads(SOURCE.read_text(encoding="utf-8"))["rows"]
    t0 = datetime(2026, 11, 3, 11, 27)
    with Session(c.app_ref.state.engine) as s:
        for r in rows:
            run = ModelRun(case_id="L", requested_by="alice", model="muse-spark-1.3", mode="LIVE",
                           status=r["model_run_status"], rounds=r["rounds"], prompt_tokens=r["prompt_tokens"],
                           completion_tokens=r["completion_tokens"], error=None, report_json=None,
                           validation_errors=r.get("validation_errors") or [], attempts=[{}],
                           started_at=t0.isoformat(), finished_at=(t0 + timedelta(seconds=r["seconds"] or 0)).isoformat())
            s.add(run)
            s.flush()
            for n, t in enumerate(r.get("tools") or []):  # the run's own tool calls ("name:ok|error")
                name, _, state = t.partition(":")
                s.add(ToolCall(model_run_id=run.id, round=n + 1, tool_name=name, arguments_json="{}",
                               result_sha256=None, ok=state == "ok", error=None if state == "ok" else state,
                               created_at=t0.isoformat()))
        s.commit()
    r = c.post("/limit-proposals", headers=H("gina"))
    assert r.status_code == 201, r.text
    props = r.json()
    for p in props:
        print(json.dumps({k: p[k] for k in ("proposal_id", "name", "current", "proposed", "status", "issue", "reason",
                                             "comparison")}, ensure_ascii=False))
    first = next((p for p in props if p["status"] == "PROPOSED"), None)
    decided = None
    if first:
        d = c.post(f"/limit-proposals/{first['proposal_id']}/decision", headers=H("gina"),
                   json={"decision": "APPROVED", "reason": "데모: 최근 실행 기록 근거로 승인"})
        decided = d.json()
        hist = c.get("/limits", headers=H("gina")).json()["history"][-1]
        print("approved:", decided["status"], "live value now", decided["live_value"], "history:", hist)
    out = {"run_mode": provider.mode, "model": provider.model, "runs_from": SOURCE.name, "runs": len(rows),
           "statistics": props[0]["statistics"] if props else None, "proposals": props, "approved": decided,
           "cost_usd": 0.0 if provider.mode != "LIVE" else None, "run": evalkit.run_info("scripts.ops_proposal_demo")}
    path = EVAL_DIR / "ev" / f"ops_proposal_demo_{provider.mode}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
