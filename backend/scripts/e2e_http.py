"""C: the D0->D8 success and failure scenarios of tests/test_c_e2e.py, and the Agent-First AG4 scenario of
tests/test_agent_ag4.py, against a real uvicorn process.

Each scenario gets its own Alembic-migrated scratch DB and server. Run from backend/:
    python -m scripts.e2e_http [--port 8798] [--out DIR]
After the success scenario the closed case's 8D report and the approved NCR are downloaded as DOCX and PDF (G10),
opened with python-docx / pypdf and saved to DIR (default: a new temp directory).
"""

import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine

from app import BACKEND_DIR
from app.synthetic import generate_line
from tests.test_agent_ag4 import agent_scenario
from tests.test_c_e2e import failure, success
from tests.test_g10_export import opened
from tests.v5_util import TEAM, H


@contextlib.contextmanager
def server(port: int):
    db = Path(tempfile.mkdtemp()) / "e2e.db"
    url = f"sqlite:///{db.as_posix()}"
    env = {**os.environ, "DATABASE_URL": url, "MODEL_API_KEY": ""}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND_DIR, env=env, check=True,
                   capture_output=True)
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                            cwd=tempfile.gettempdir(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    c = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120)
    engine = create_engine(url)  # read-only: the evidence-id lookup in tests.v5_util
    c.app_ref = SimpleNamespace(state=SimpleNamespace(engine=engine))
    try:
        for _ in range(60):
            with contextlib.suppress(httpx.TransportError):
                if c.get("/health").status_code == 200:
                    break
            time.sleep(0.5)
        assert c.post("/cases", json={"case_id": "L"}, headers=H("alice")).status_code == 201
        assert c.post("/cases/L/sources", json=generate_line(7), headers=H("alice")).status_code == 201
        for u in TEAM:
            c.post("/cases/L/assignments", json={"user_id": u}, headers=H("alice"))
        assert c.post("/cases/L/process-context", json={"site": "SITE-A", "customer": "DEFAULT"},
                      headers=H("alice")).status_code == 201
        yield c
    finally:
        c.close()
        engine.dispose()
        proc.terminate()
        proc.wait(10)


def download(c, out: Path) -> None:
    for path in ("/cases/L/report/export", "/cases/L/documents/ncr/export"):
        for fmt in ("docx", "pdf"):
            r = c.get(f"{path}?format={fmt}", headers=H("bob"))
            text = opened(r, fmt)
            name = r.headers["content-disposition"].split('filename="')[1].rstrip('"')
            assert r.headers["x-reference-sha256"] in "".join(text.split())
            (out / name).write_bytes(r.content)
            print(f"  {name} {r.headers['content-type']} {len(r.content)} bytes "
                  f"fields_checked={r.headers['x-fields-checked']} sha256={r.headers['x-file-sha256'][:16]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8798)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    port, out = args.port, args.out or Path(tempfile.mkdtemp(prefix="qualityops_export_"))
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    scenarios = (("success D0->D8 CLOSED", success), ("failure D6 NOT_EFFECTIVE", failure),
                 ("agent draft -> G9 edit -> confirmed review -> human approval -> approved export only", agent_scenario))
    for name, scenario in scenarios:
        try:
            with server(port) as c:
                res = scenario(c)
                if res and "snapshot_sha256" in res:
                    download(c, out)
            print(f"PASS {name}" + (f" snapshot={res['snapshot_sha256'][:16]}; files in {out}"
                                    if res and "snapshot_sha256" in res else ""))
        except Exception:  # noqa: BLE001 - report every scenario
            failed += 1
            print(f"FAIL {name}\n{traceback.format_exc()}")
    print(f"{len(scenarios) - failed}/{len(scenarios)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
