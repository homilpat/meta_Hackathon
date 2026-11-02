"""Shared parts of the local evaluations (spec §26.7): where data and traces live, what a run records, the opt-in
gate for new LIVE calls, the no-network guard for scoring, and the JSON/CSV/HTML report.

Modes, never mixed in one number:
  LIVE         a trace collected now or earlier from the real model (paid; opt-in only)
  TEST_DOUBLE  a trace from a scripted stand-in: checks the pipeline and the scorer, never a model result
  NOT_RUN      nothing was executed; never reported as a pass
Scoring is always an OFFLINE_REPLAY of saved traces: no model and no network is called.
"""

import csv
import hashlib
import html
import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app import EVAL_DIR, REPO_ROOT, docparse

# Downloaded data and traces (they may hold document text): outside git (.gitignore), here unless QO_EVAL_DATA says
DATA_DIR = Path(os.environ.get("QO_EVAL_DATA") or REPO_ROOT / ".eval_data")
BUDGET_ENV = "QO_EVAL_LIVE_BUDGET_USD"  # the budget a person confirmed for new LIVE calls; unset = no LIVE


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(x) -> str:
    return sha256_bytes(json.dumps(x, ensure_ascii=False, sort_keys=True, default=str).encode())


def code_sha() -> str:
    """HEAD, with "+dirty" when tracked files differ from it (the result then belongs to uncommitted code)."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_info(evaluator: str, **extra) -> dict:
    """What a result belongs to: code, parser, evaluator source, Python, command and time."""
    return {"code_sha": code_sha(), "parser_version": docparse.PARSER_VERSION,
            "evaluator": evaluator, "evaluator_sha256": sha256_file(Path(importlib.util.find_spec(evaluator).origin))[:16],
            "python": platform.python_version(), "command": " ".join(["python -m", evaluator, *sys.argv[1:]]),
            "at": now(), **extra}


@contextmanager
def no_network():
    """Scoring must not reach the network (spec §26.7): every connection to a non-loopback address fails and is
    counted. Loopback stays open: the in-process test client's event loop talks to itself over a local socket pair."""
    attempts: list[str] = []
    real_connect, real_create = socket.socket.connect, socket.create_connection

    def local(address) -> bool:
        host = address[0] if isinstance(address, tuple) else address
        return isinstance(host, str) and (host in ("localhost", "::1") or host.startswith("127."))

    def connect(sock, address):
        if not local(address):
            attempts.append(repr(address)[:80])
            raise ConnectionRefusedError("network is off while scoring (spec §26.7)")
        return real_connect(sock, address)

    def create(address, *a, **k):
        if not local(address):
            attempts.append(repr(address)[:80])
            raise ConnectionRefusedError("network is off while scoring (spec §26.7)")
        return real_create(address, *a, **k)

    os.environ["LANGSMITH_TRACING"] = os.environ["LANGCHAIN_TRACING_V2"] = "false"  # AgentEvals' tracer stays local
    socket.socket.connect, socket.create_connection = connect, create
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.create_connection = real_connect, real_create


def live_gate(args: list[str]) -> tuple[object | None, float | None, str | None]:
    """(provider, budget USD, why not). New LIVE calls need all three: --live on the command line, a budget a
    person confirmed in QO_EVAL_LIVE_BUDGET_USD, and a configured key. A key alone never starts a paid call."""
    if "--live" not in args:
        return None, None, "LIVE is off by default: pass --live"
    try:
        budget = float(os.environ.get(BUDGET_ENV, "") or 0)
    except ValueError:
        budget = 0
    if budget <= 0:
        return None, None, f"no confirmed budget: set {BUDGET_ENV} to the approved amount in USD"
    from app.model_provider import MetaProvider

    provider = MetaProvider.from_env()
    if provider is None:
        return None, None, "no MODEL_API_KEY configured"
    return provider, budget, None


def cost_usd(usage: dict) -> float:
    from app import limits

    return (usage.get("prompt_tokens", 0) * limits.get("MODEL_PRICE_INPUT_PER_M_USD")
            + usage.get("completion_tokens", 0) * limits.get("MODEL_PRICE_OUTPUT_PER_M_USD")) / 1e6


def write_report(name: str, summary: dict, rows: list[dict], out_dir: Path | None = None) -> Path:
    """<name>.json (summary and every row), <name>.csv (rows), <name>.html (both, readable offline)."""
    out = out_dir or EVAL_DIR / "ev"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1,
                                                 default=str), encoding="utf-8", newline="\n")
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(out / f"{name}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                     for k, v in r.items()} for r in rows)
    esc = lambda v: html.escape(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str))
    table = "".join("<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols) + "</tr>" for r in rows)
    (out / f"{name}.html").write_text(
        f"<!doctype html><meta charset='utf-8'><title>{esc(name)}</title>"
        "<style>body{font:13px system-ui;margin:16px}td,th{border:1px solid #ccc;padding:2px 6px;"
        "vertical-align:top}table{border-collapse:collapse}pre{white-space:pre-wrap}</style>"
        f"<h1>{esc(name)}</h1><pre>{esc(json.dumps(summary, ensure_ascii=False, indent=1, default=str))}</pre>"
        f"<table><tr>{''.join(f'<th>{esc(c)}</th>' for c in cols)}</tr>{table}</table>",
        encoding="utf-8", newline="\n")
    return out / f"{name}.json"
