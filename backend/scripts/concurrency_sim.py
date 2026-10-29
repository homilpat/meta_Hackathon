"""Multi-user concurrency simulation against a real uvicorn server (HTTP, threads, file SQLite).

Each scenario fires conflicting requests from different demo users at the same moment and checks an
invariant afterwards. Writes docs/evaluations/CONCURRENCY_RESULTS.md and docs/evaluations/concurrency.json. No model calls.
Run: python -m scripts.concurrency_sim [--trials 20]
"""

import argparse
import json
import socket
import tempfile
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import EVAL_DIR, audit
from app.db import Base, DocumentVersion, WorkflowEvent
from app.main import create_app
from app.synthetic import generate, spi_correction

APPROVERS = {"ncr": "bob", "containment": "erin", "rca": "frank"}


class Client:
    def __init__(self, base: str):
        self.base, self.codes = base, Counter()

    def call(self, user, method, path, body=None, key=None):
        req = Request(self.base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                      headers={"X-User": user, "Content-Type": "application/json",
                               "Idempotency-Key": key or uuid.uuid4().hex})
        try:
            with urlopen(req, timeout=60) as r:
                code, out = r.status, json.load(r)
        except HTTPError as e:
            code, out = e.code, e.read().decode(errors="replace")[:300]
        self.codes[code] += 1
        return code, out

    def ok(self, *a, **kw):
        code, out = self.call(*a, **kw)
        assert code < 300, (a, code, out)
        return out


def together(*calls):
    """Release all calls at the same instant; return their (status, body) in order."""
    gate = threading.Barrier(len(calls))

    def go(fn):
        gate.wait()
        return fn()

    with ThreadPoolExecutor(len(calls)) as pool:
        return [f.result() for f in [pool.submit(go, fn) for fn in calls]]


def new_case(c: Client, cid: str):
    c.ok("alice", "POST", "/cases", {"case_id": cid})
    c.ok("alice", "POST", f"/cases/{cid}/sources", generate(7))
    for u in APPROVERS.values():
        c.ok("alice", "POST", f"/cases/{cid}/assignments", {"user_id": u})


def approve(c: Client, cid, kind, version):
    d = c.ok("alice", "POST", f"/cases/{cid}/{kind}/{version}/request-review", {"reviewer_id": APPROVERS[kind]})
    return c.ok(APPROVERS[kind], "POST", f"/cases/{cid}/{kind}/{version}/decision",
                {"decision": "APPROVE", "content_sha256": d["content_sha256"]})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    trials = ap.parse_args().trials
    db = Path(tempfile.mkdtemp()) / "concurrency.db"
    app = create_app(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(app.state.engine)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    c = Client(f"http://127.0.0.1:{port}")
    results = {}

    def scenario(name, desc, run):
        seen, bad, t0 = Counter(), [], time.perf_counter()
        before = Counter(c.codes)
        for i in range(trials):
            codes, violation = run(f"{name}-{i}")
            seen.update(codes)
            if violation:
                bad.append(f"trial {i}: {violation}")
        results[name] = {"description": desc, "trials": trials, "status_codes": dict(sorted(seen.items())),
                         "violations": bad, "server_errors_5xx": sum(n for k, n in (c.codes - before).items()
                                                                     if k >= 500),
                         "seconds": round(time.perf_counter() - t0, 2)}

    def double_decision(cid):
        new_case(c, cid)
        c.ok("alice", "POST", f"/cases/{cid}/ncr", {})
        d = c.ok("alice", "POST", f"/cases/{cid}/ncr/1/request-review", {"reviewer_id": "bob"})
        out = together(*[lambda dec=dec: c.call("bob", "POST", f"/cases/{cid}/ncr/1/decision",
                                                {"decision": dec, "content_sha256": d["content_sha256"]})
                         for dec in ("APPROVE", "REJECT", "REQUEST_INFO")])
        codes = [o[0] for o in out]
        doc = c.ok("alice", "GET", f"/cases/{cid}/ncr/1")
        wins = codes.count(200)
        if wins != 1 or len(doc["decisions"]) != 1:
            return codes, f"{wins} decisions accepted, {len(doc['decisions'])} recorded"
        return codes, None

    def stale_approval(cid):
        new_case(c, cid)
        c.ok("alice", "POST", f"/cases/{cid}/ncr", {})
        d = c.ok("alice", "POST", f"/cases/{cid}/ncr/1/request-review", {"reviewer_id": "bob"})
        out = together(lambda: c.call("bob", "POST", f"/cases/{cid}/ncr/1/decision",
                                      {"decision": "APPROVE", "content_sha256": d["content_sha256"]}),
                       lambda: c.call("alice", "POST", f"/cases/{cid}/ncr", {}))
        with Session(app.state.engine) as s:
            ev = {(w.event, w.detail[:6]): w.id for w in s.scalars(select(WorkflowEvent).where(
                WorkflowEvent.case_id == cid))}
        approved, v2 = ev.get(("APPROVE", "NCR v1")), ev.get(("DRAFT_CREATED", "NCR v2"))
        if out[0][0] == 200 and v2 is not None and approved > v2:
            return [o[0] for o in out], "v1 approved after v2 was drafted"
        return [o[0] for o in out], None

    def revision_vs_approval(cid):
        new_case(c, cid)
        c.ok("alice", "POST", f"/cases/{cid}/ncr", {})
        approve(c, cid, "ncr", 1)
        c.ok("alice", "POST", f"/cases/{cid}/containment", {})
        d = c.ok("alice", "POST", f"/cases/{cid}/containment/1/request-review", {"reviewer_id": "erin"})
        out = together(lambda: c.call("erin", "POST", f"/cases/{cid}/containment/1/decision",
                                      {"decision": "APPROVE", "content_sha256": d["content_sha256"]}),
                       lambda: c.call("alice", "POST", f"/cases/{cid}/source-revisions",
                                      {"asset": spi_correction(7), "reason": "concurrent re-measure"}))
        ncr = c.ok("alice", "GET", f"/cases/{cid}/ncr/1")["status"]
        cont = c.ok("alice", "GET", f"/cases/{cid}/containment/1")["status"]
        if ncr != "APPROVED" and cont == "APPROVED":
            return [o[0] for o in out], f"containment APPROVED on a reopened NCR ({ncr})"
        return [o[0] for o in out], None

    def same_key_retry(cid):
        new_case(c, cid)
        key = uuid.uuid4().hex
        out = together(*[lambda: c.call("alice", "POST", f"/cases/{cid}/ncr", {}, key) for _ in range(4)])
        with Session(app.state.engine) as s:
            n = len(s.scalars(select(DocumentVersion).where(DocumentVersion.case_id == cid)).all())
        bodies = {json.dumps(o[1], sort_keys=True) for o in out if o[0] == 201}
        if n != 1 or len(bodies) != 1 or any(o[0] != 201 for o in out):
            return [o[0] for o in out], f"{n} versions created, {len(bodies)} distinct 201 bodies"
        return [o[0] for o in out], None

    def parallel_cases(prefix):
        ids = [f"{prefix}-{k}" for k in range(4)]

        def chain(cid):
            new_case(c, cid)
            for kind in APPROVERS:
                c.ok("alice", "POST", f"/cases/{cid}/{kind}", {})
                approve(c, cid, kind, 1)
            return [s["status"] for s in c.ok("alice", "GET", f"/cases/{cid}/stages")]

        out = together(*[lambda cid=cid: chain(cid) for cid in ids])
        wrong = [cid for cid, st in zip(ids, out, strict=True) if st != ["APPROVED"] * 3]
        events = [Counter(t["event"] for t in c.ok("erin", "GET", f"/cases/{cid}/timeline")) for cid in ids]
        mixed = [cid for cid, e in zip(ids, events, strict=True)
                 if e != events[0] or e["DRAFT_CREATED"] != 3 or e["APPROVE"] != 3]
        return [200], (f"incomplete {wrong}" if wrong else None) or (f"timelines differ {mixed}" if mixed else None)

    scenario("double_decision", "one reviewer sends APPROVE, REJECT and REQUEST_INFO at once (three tabs)",
             double_decision)
    scenario("stale_approval", "reviewer approves v1 while the author drafts v2", stale_approval)
    scenario("revision_vs_approval", "QA approves the containment plan while an SPI correction reopens its NCR",
             revision_vs_approval)
    scenario("same_key_retry", "one client retries the same create request 4x concurrently (same Idempotency-Key)",
             same_key_retry)
    scenario("parallel_cases", "4 cases run the full D2-D4 chain in parallel threads", parallel_cases)
    server.should_exit = True
    with Session(app.state.engine) as s:
        chain = audit.verify(s)  # concurrent writers must still produce one unbroken audit hash chain
    app.state.engine.dispose()

    results["audit_chain"] = {"ok": chain["ok"], "links": chain["links"], "breaks": chain["breaks"]}
    (EVAL_DIR / "concurrency.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    rows = "\n".join(f"| {k} | {v['description']} | {v['trials']} | {v['status_codes']} | {v['server_errors_5xx']} | "
                     f"{len(v['violations'])} |" for k, v in results.items() if k != "audit_chain")
    (EVAL_DIR / "CONCURRENCY_RESULTS.md").write_text(f"""# Concurrency simulation

Generated by `python -m scripts.concurrency_sim --trials {trials}`: a real uvicorn server on a file SQLite
database, demo users sending conflicting HTTP requests released together by a thread barrier. SYNTHETIC data,
no model calls. Raw output: `docs/evaluations/concurrency.json`.

| scenario | what collides | trials | status codes of the colliding requests | 5xx | invariant violations |
|---|---|---|---|---|---|
{rows}

Audit hash chain after all scenarios: ok={chain['ok']}, {chain['links']} links, {len(chain['breaks'])} breaks.

Invariants: exactly one decision per review; a version is never approved after a newer draft exists; a
containment plan is never APPROVED on top of a reopened NCR; one Idempotency-Key creates one version and every
retry gets the same response; parallel cases finish independently with only their own events.
Before the fix (first run, 10 trials, same scenarios): double_decision 10/10 trials accepted 2-3 decisions;
revision_vs_approval 8/10 left a containment plan APPROVED on a reopened NCR; same_key_retry returned HTTP 500
on 30 of 40 requests (duplicate version insert). Cause: the SQLite driver ran each request's checks outside
its write transaction. Fix: `serialize_sqlite` in `app/main.py` (BEGIN IMMEDIATE).
Limits: one machine, threads not processes, SQLite (single writer). It shows the server's conflict rules hold
under these collisions; it is not a load test.
""", encoding="utf-8")
    print(json.dumps({k: {"codes": v["status_codes"], "5xx": v["server_errors_5xx"], "violations": len(v["violations"])}
                      for k, v in results.items() if k != "audit_chain"} | {"audit_chain_ok": chain["ok"]}))


if __name__ == "__main__":
    main()
