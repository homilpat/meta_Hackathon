"""C: the D0->D8 success and failure scenarios of tests/test_c_e2e.py against a real uvicorn process.

Each scenario gets its own Alembic-migrated scratch DB and server. Run from backend/:
    python -m scripts.e2e_http [--port 8798]
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
from tests.test_c_e2e import failure, success
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8798)
    port = ap.parse_args().port
    failed = 0
    for name, scenario in (("success D0->D8 CLOSED", success), ("failure D6 NOT_EFFECTIVE", failure)):
        try:
            with server(port) as c:
                out = scenario(c)
            print(f"PASS {name}" + (f" snapshot={out['snapshot_sha256'][:16]}" if out else ""))
        except Exception:  # noqa: BLE001 - report every scenario
            failed += 1
            print(f"FAIL {name}\n{traceback.format_exc()}")
    print(f"{2 - failed}/2 passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
