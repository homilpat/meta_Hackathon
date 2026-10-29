"""Integration smoke against a real uvicorn process on an Alembic-migrated scratch DB (not create_all).

Checks the built React bundle at /app (every referenced asset), the /ui fallback, provider honesty without a key,
case access control, an NCR draft through the one claim validator, Experience Memory, separation of duties on
approval, and the audit hash chain. Exit 0 when every step passes. Run from backend/:
    python -m scripts.integration_smoke [--port 8799]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import BACKEND_DIR

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}")


def call(base: str, path: str, user: str = "alice", body: dict | None = None, method: str | None = None):
    headers = {"X-User": user, "Idempotency-Key": uuid.uuid4().hex}
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(base + path, data=data, headers=headers, method=method or ("GET" if data is None else "POST"))
    try:
        with urlopen(req, timeout=60) as r:
            raw = r.read()
            status = r.status
    except HTTPError as e:
        raw, status = e.read(), e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    port = ap.parse_args().port
    base = f"http://127.0.0.1:{port}"
    db = Path(tempfile.mkdtemp()) / "integration.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}", "MODEL_API_KEY": ""}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True,
                   capture_output=True)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                              cwd=tempfile.gettempdir(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if call(base, "/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.5)
        status, health = call(base, "/health")
        check("health", status == 200 and health == {"status": "ok", "stage": "S6"}, str(health))

        status, html = call(base, "/app/")
        assets = re.findall(r'(?:src|href)="(/app/[^"]+)"', html if isinstance(html, str) else "")
        check("/app index", status == 200 and '<div id="root">' in html and len(assets) >= 2, f"{len(assets)} assets")
        bad = [a for a in assets if call(base, a)[0] != 200]
        check("/app assets", not bad, ",".join(bad))
        status, ui = call(base, "/ui")
        check("/ui legacy", status == 200 and isinstance(ui, str) and "<html" in ui.lower())

        status, prov = call(base, "/provider")
        check("provider not LIVE without key", status == 200 and not prov["configured"]
              and prov["live_status"] != "VERIFIED", str(prov.get("live_status")))

        cid = "INT-" + uuid.uuid4().hex[:6].upper()
        check("create case", call(base, "/cases", body={"case_id": cid})[0] == 201)
        _, line = call(base, "/synthetic/line/7")
        check("load line sources", call(base, f"/cases/{cid}/sources", body=line)[0] == 201)
        check("unassigned user refused", call(base, f"/cases/{cid}/evidence", user="bob")[0] == 403)
        for u in ("bob", "carol", "erin", "frank", "dave"):
            call(base, f"/cases/{cid}/assignments", body={"user_id": u})
        status, _ = call(base, f"/cases/{cid}/process-context", body={"site": "SITE-A", "customer": "DEFAULT"})
        check("process context", status == 201)
        status, gates = call(base, f"/cases/{cid}/gates", user="bob")
        check("gates", status == 200 and set(gates["state"]) >= {f"D{i}" for i in range(9)})

        status, doc = call(base, f"/cases/{cid}/ncr", body={})
        check("NCR template draft", status == 201, str(doc)[:120] if status != 201 else "")
        status, val = call(base, f"/cases/{cid}/ncr/1/validate", user="bob", body={})
        check("claim validator", status in (200, 201) and val["result"] in ("PASS", "WARN"), str(val)[:120])

        status, xp = call(base, f"/cases/{cid}/experience/retrievals", body={"q": "solder volume drift stencil"})
        check("experience memory", status in (200, 201)
              and xp["mode"] in ("KNOWN", "ANALOGICAL", "NO_RELEVANT_HISTORY"), str(xp.get("mode")))

        status, _ = call(base, f"/cases/{cid}/investigations", body={"use_history": True})
        check("investigation without key is 503 (no mock)", status == 503, str(status))

        sha = doc["content_sha256"]
        check("request review", call(base, f"/cases/{cid}/ncr/1/request-review", body={"reviewer_id": "bob"})[0]
              in (200, 201))
        status, _ = call(base, f"/cases/{cid}/ncr/1/decision", body={"decision": "APPROVE", "comment": "self",
                                                                       "content_sha256": sha})
        check("author cannot approve own NCR", status == 403, str(status))
        status, _ = call(base, f"/cases/{cid}/ncr/1/decision", user="bob",
                         body={"decision": "APPROVE", "comment": "ok", "content_sha256": "0" * 64})
        check("stale hash refused", status == 409, str(status))
        status, _ = call(base, f"/cases/{cid}/ncr/1/decision", user="bob",
                         body={"decision": "APPROVE", "comment": "checked against rows", "content_sha256": sha})
        check("reviewer approves", status in (200, 201), str(status))

        # G9: edit the approved NCR -> new version, re-validated; the approved v1 stays as it was
        c1 = doc["claims"][0]
        status, e = call(base, f"/cases/{cid}/ncr/1/edits", body={
            "expected_sha256": sha, "reason": "smoke: wording", "changes": [
                {"claim_id": c1["claim_id"], "text": c1["text"] + " (reviewed)"}]})
        check("G9 edit -> v2 + validation", status == 201 and e["version"] == 2
              and e["validation"]["result"] in ("PASS", "WARN") and len(e["diff"]) == 1, str(e)[:160])
        pct = next(c for c in doc["claims"] if c["unit"] == "count" and c["value"])  # "x of y", recomputed
        status, _ = call(base, f"/cases/{cid}/ncr/2/edits", body={
            "expected_sha256": e.get("content_sha256"), "reason": "smoke: wrong number",
            "changes": [{"claim_id": pct["claim_id"], "value": pct["value"] + 1}]})
        check("G9 wrong number blocked", status == 422, str(status))
        status, _ = call(base, f"/cases/{cid}/ncr/1/edits", body={
            "expected_sha256": sha, "reason": "smoke: stale base", "changes": [
                {"claim_id": c1["claim_id"], "text": c1["text"] + " (again)"}]})
        check("G9 stale base refused", status == 409, str(status))
        check("G9 AI proposal offline", call(base, f"/cases/{cid}/ncr/2/edit-proposals",
                                             body={"instruction": "shorter"})[0] == 503)
        call(base, f"/cases/{cid}/ncr/2/request-review", body={"reviewer_id": "bob"})
        status, _ = call(base, f"/cases/{cid}/ncr/2/decision", user="bob", body={
            "decision": "APPROVE", "comment": "edit checked", "content_sha256": e.get("content_sha256")})
        _, v1 = call(base, f"/cases/{cid}/ncr/1", user="bob")
        check("G9 v2 approved, v1 unchanged", status == 200 and v1["status"] == "APPROVED"
              and v1["content_sha256"] == sha, str(status))

        status, chain = call(base, "/audit/verify")
        check("audit chain", status == 200 and chain["ok"] and chain["links"] > 0, f"links={chain.get('links')}")
    finally:
        server.terminate()
        server.wait(10)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
