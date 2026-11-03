"""Agent "왜 안 돼?" (A) and conversation context (B) through the real API in-process, with the Meta planner. Run from
backend/:

    QO_EVAL_LIVE_BUDGET_USD=0.1 python -m scripts.agent_ab_demo --live      (a few small calls)

A request of alice is refused first; then she asks why, asks for the status, and follows up with "그거" and "그럼".
Report: docs/evaluations/ev/agent_ab_demo_<MODE>.json (each goal, the intents chosen, the tools run, the answer).
"""

import json
import sys
import tempfile
import uuid
from pathlib import Path

from app import EVAL_DIR
from scripts import evalkit

GOALS = ["아까 검토 요청 왜 안 돼?", "진행 상태 알려줘", "그거 무슨 뜻이야?", "그럼 다음엔 뭐 해야 돼?"]


def main(args) -> int:
    from tests.v5_util import H, line_client

    provider = evalkit.live_gate(args)[0] if "--live" in args else None  # None: the server rule planner
    c = line_client(Path(tempfile.mkdtemp()), provider=provider)
    refused = c.post("/cases/L/ncr/9/request-review", json={"reviewer_id": "bob"}, headers=H("alice"))
    turns = []
    for goal in GOALS:
        r = c.post("/agent/runs", json={"case_id": "L", "goal": goal},
                   headers={"X-User": "alice", "Idempotency-Key": uuid.uuid4().hex})
        out = r.json()
        turns.append({"goal": goal, "status": out.get("status"), "intents": out.get("intents"),
                      "tools": [s["tool"] for s in out.get("steps", [])],
                      "answer": [x["text"] for x in out.get("reply", [])],
                      "asked_back": (out.get("pending") or {}).get("question")})
        print(json.dumps(turns[-1], ensure_ascii=False)[:700])
    mode = provider.mode if provider else "SERVER_RULES"
    report = {"run_mode": mode, "model": getattr(provider, "model", None),
              "refused_first": {"status": refused.status_code, "detail": refused.json().get("detail")},
              "turns": turns, "run": evalkit.run_info("scripts.agent_ab_demo")}
    path = EVAL_DIR / "ev" / f"agent_ab_demo_{mode}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
