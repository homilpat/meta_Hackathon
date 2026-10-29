"""History OFF vs ON on fixed held-out query profiles + the demo case; writes docs/evaluations/HISTORY_COMPARISON.md.

The planner is deterministic and rule-based, and the scenario answer key encodes the same synthetic
process knowledge as the precedent bank. This shows that eligible precedents reach the plan and that
failed fixes are not recommended; it is NOT evidence that an LLM investigator improves with history.
That comparison (settings C vs D) needs LIVE Meta runs. Run: python -m scripts.history_compare
"""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import EVAL_DIR, history
from app.db import Base
from app.main import create_app
from app.synthetic import generate

AS_OF = "2026-01-15T00:00:00+00:00"
# (query id, family, board pattern(s), needed first discriminating check, action that must not be recommended)
QUERIES = [
    ("Q01", "QF-A", [("SPI_VOLUME_LOW", "AOI_FAIL_CONFIRMED")], "STENCIL_APERTURE_INSPECTION", None),
    ("Q02", "QF-A", [("SPI_VOLUME_LOW", "AOI_FAIL_CONFIRMED"), ("NORMAL", "AOI_PASS")], "STENCIL_APERTURE_INSPECTION", None),
    ("Q03", "QF-B", [("SPI_VOLUME_HIGH", "AOI_FAIL_CONFIRMED")], "STENCIL_THICKNESS_CHECK", None),
    ("Q04", "QF-B", [("SPI_VOLUME_HIGH", "AOI_FAIL_CONFIRMED"), ("SPI_VOLUME_HIGH", "AOI_PASS")], "STENCIL_THICKNESS_CHECK", None),
    ("Q05", "QF-C", [("SPI_VOLUME_SCATTER", "AOI_FAIL_CONFIRMED")], "SPI_CALIBRATION_LOG", None),
    ("Q06", "QF-C", [("SPI_VOLUME_SCATTER", "AOI_FALSE_ALARM")], "REFLOW_PROFILE_LOG", "REFLOW_PROFILE_CHANGE"),
    ("Q07", "QF-D", [("SPI_VOLUME_LOW", "AOI_FALSE_ALARM")], None, "PRINTER_PRESSURE_ADJUST"),
    ("Q08", "QF-D", [("SPI_VOLUME_LOW", "AOI_FALSE_ALARM"), ("SPI_VOLUME_LOW", "AOI_PASS")], None, "PRINTER_PRESSURE_ADJUST"),
    ("Q09", "QF-E", [("NORMAL", "AOI_FALSE_ALARM")], "AOI_LIBRARY_REVIEW", "AOI_THRESHOLD_TUNE"),
    ("Q10", "QF-F", [("SPI_VOLUME_LOW", "AOI_MISSING")], "AOI_RERUN", None),
    ("Q11", "QF-F", [("NORMAL", "AOI_MISSING")], "AOI_RERUN", None),
    ("Q12", "QF-G", [("SPI_VOLUME_LOW", "AOI_FAIL_UNVERIFIED")], "OPERATOR_ADJUDICATION", "PRINTER_PRESSURE_ADJUST"),
    ("Q13", "QF-G", [("SPI_VOLUME_HIGH", "AOI_FAIL_UNVERIFIED")], "OPERATOR_ADJUDICATION", None),
    ("Q14", "QF-H", [("NORMAL", "AOI_FAIL_CONFIRMED")], "XRAY_CROSS_SECTION", None),
    ("Q15", "QF-H", [("NO_SPI", "AOI_FAIL_CONFIRMED")], "XRAY_CROSS_SECTION", None),
    ("Q16", "QF-I", [("SPI_VOLUME_HIGH", "AOI_FALSE_ALARM")], None, None),
    ("Q17", "QF-J", [("SPI_VOLUME_LOW", "AOI_FAIL_CONFIRMED"), ("SPI_VOLUME_LOW", "AOI_FALSE_ALARM")], "STENCIL_APERTURE_INSPECTION", "PRINTER_PRESSURE_ADJUST"),
    ("Q18", "QF-J", [("SPI_VOLUME_SCATTER", "AOI_FAIL_CONFIRMED"), ("SPI_VOLUME_SCATTER", "AOI_FALSE_ALARM")], "SPI_CALIBRATION_LOG", "REFLOW_PROFILE_CHANGE"),
    ("Q19", "QF-K", [("NORMAL", "AOI_PASS")], None, None),
    ("Q20", "QF-K", [("SPI_VOLUME_LOW", "AOI_PASS")], None, None),
]


def profile(boards: list[tuple[str, str]]) -> history.Profile:
    return history.Profile(as_of=AS_OF, boards={f"Q/B{i}": {"spi": s, "aoi": a, "evidence": []}
                                                for i, (s, a) in enumerate(boards, 1)})


def score(plan: dict, needed: str | None, avoid: str | None) -> dict:
    checks = [c["check"] for c in plan["next_checks"]]
    text = json.dumps(plan["next_checks"]).lower()
    recommended_avoid = bool(avoid) and history.ACTION_TERMS[avoid] in text
    return {"checks": checks, "top1": (checks[:1] == [needed]) if needed else None,
            "hit3": (needed in checks[:3]) if needed else None, "recommends_failed_fix": recommended_avoid,
            "warned_failed_fix": bool(avoid) and any(avoid in w["text"] for w in plan["warnings"]),
            "precedents_used": plan["precedents_used"]}


def main() -> None:
    db = Path(tempfile.mkdtemp()) / "h.db"
    app = create_app(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(app.state.engine)
    rows = []
    with Session(app.state.engine) as s, s.begin():
        history.ensure_bank(s)
        bank_families = {h["family"] for h in history.bank()}
        assert not bank_families & {q[1] for q in QUERIES}, "query family leaked into the bank"
        for qid, fam, boards, needed, avoid in QUERIES:
            prof = profile(boards)
            found = history.retrieve(s, prof)
            rows.append({"query": qid, "family": fam, "boards": boards, "needed": needed, "avoid": avoid,
                         "OFF": score(history.plan_next_evidence(prof, None), needed, avoid),
                         "ON": score(history.plan_next_evidence(prof, found), needed, avoid),
                         "retrieval_status": found["status"]})
    with TestClient(app, headers={"X-User": "alice"}) as c:
        c.post("/cases", json={"case_id": "DEMO"})
        c.post("/cases/DEMO/sources", json=generate(7))
        demo = {m: c.get(f"/cases/DEMO/next-evidence?history_mode={m}").json() for m in ("off", "on")}
    app.state.engine.dispose()

    def rate(mode: str, key: str) -> str:
        vals = [r[mode][key] for r in rows if r[mode][key] is not None]
        return f"{sum(vals)}/{len(vals)}"

    summary = {m: {k: rate(m, k) for k in ("top1", "hit3", "recommends_failed_fix")} for m in ("OFF", "ON")}
    avoid_rows = [r for r in rows if r["avoid"]]
    summary["ON"]["warned_failed_fix"] = f"{sum(r['ON']['warned_failed_fix'] for r in avoid_rows)}/{len(avoid_rows)}"
    (EVAL_DIR / "history_eval.json").write_text(json.dumps({"summary": summary, "queries": rows, "demo_case": {
        m: {k: demo[m][k] for k in ("next_checks", "warnings", "precedents_used", "known", "unknown")}
        for m in demo}}, indent=2), encoding="utf-8")
    lines = [f"| {r['query']} | {r['family']} | {', '.join('+'.join(b) for b in r['boards'])} | {r['needed'] or '-'} | "
             f"{', '.join(r['OFF']['checks'])} | {', '.join(r['ON']['checks'])} | {', '.join(r['ON']['precedents_used']) or '-'} | "
             f"{'yes' if r['ON']['recommends_failed_fix'] or r['OFF']['recommends_failed_fix'] else 'no'} |" for r in rows]
    (EVAL_DIR / "HISTORY_COMPARISON.md").write_text(f"""# History OFF vs ON — deterministic planner log

Generated by `python -m scripts.history_compare` (bank `{history.BANK_VERSION}`, as-of `{AS_OF}`).

**What this is:** a consistency check of the retrieval + rule-based planner on {len(rows)} held-out query
profiles (families disjoint from the bank) and the demo case. The answer key encodes the same synthetic
process knowledge as the bank, so a higher ON score is expected by construction and is **not** evidence
that an LLM investigator improves with history. The C (history OFF) vs D (history ON) comparison with the
Meta model is **not run yet** (no LIVE key); no improvement is claimed.

| metric | OFF | ON |
|---|---|---|
| needed check ranked first | {summary['OFF']['top1']} | {summary['ON']['top1']} |
| needed check in top 3 | {summary['OFF']['hit3']} | {summary['ON']['hit3']} |
| recommends a fix that failed before | {summary['OFF']['recommends_failed_fix']} | {summary['ON']['recommends_failed_fix']} |
| warns about the failed fix (queries with one) | - | {summary['ON']['warned_failed_fix']} |

Demo case (synthetic fixture seed 7): OFF checks {[c['check'] for c in demo['off']['next_checks']]};
ON checks {[c['check'] for c in demo['on']['next_checks']]}; ON warnings {[w['text'] for w in demo['on']['warnings']]}.

| query | family | boards (SPI+AOI) | needed | OFF checks | ON checks | precedents | failed fix recommended |
|---|---|---|---|---|---|---|---|
""" + "\n".join(lines) + "\n\nRaw per-query output: `docs/evaluations/history_eval.json`.\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
