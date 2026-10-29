"""LIVE Meta tool-calling smoke on a throwaway synthetic case. Prints a redacted run log.

Exit codes: 0 VALIDATED, 1 run did not validate or provider failed, 2 MODEL_API_KEY unset.
Run from the repository root: python -m scripts.meta_investigate_smoke
"""

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import Base
from app.main import create_app
from app.model_provider import MetaProvider
from app.synthetic import generate


def main() -> int:
    provider = MetaProvider.from_env()
    if provider is None:
        print("LIVE NOT TESTED: MODEL_API_KEY is unset")
        return 2
    db = Path(tempfile.mkdtemp()) / "smoke.db"
    app = create_app(f"sqlite:///{db.as_posix()}", provider)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app, headers={"X-User": "alice"}) as client:
        client.post("/cases", json={"case_id": "LIVE-SMOKE"}).raise_for_status()
        client.post("/cases/LIVE-SMOKE/sources", json=generate(7)).raise_for_status()
        response = client.post("/cases/LIVE-SMOKE/investigations", headers={"Idempotency-Key": "live-smoke-0001"})
    app.state.engine.dispose()
    if response.status_code != 201:
        print(f"LIVE FAILED: HTTP {response.status_code}")
        return 1
    run = response.json()
    log = {k: run[k] for k in ("mode", "model", "status", "rounds", "prompt_tokens", "completion_tokens",
                               "error", "validation_errors")}
    log["tool_calls"] = [{k: c[k] for k in ("round", "tool_name", "arguments", "ok", "result_sha256")}
                         for c in run["tool_calls"]]
    log["finding_classes"] = [f["classification"] for f in (run["report"] or {}).get("findings", [])]
    print(json.dumps(log, indent=2))
    ok = run["mode"] == "LIVE" and run["status"] == "VALIDATED" and any(c["ok"] for c in run["tool_calls"])
    print("LIVE SUCCESS" if ok else f"LIVE RUN NOT VALIDATED: {run['status']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
