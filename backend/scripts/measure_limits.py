"""Measure server parsing throughput on this machine, to set and explain the analysis time budget (limits.py).

Builds synthetic files near the upload limit (PDF pages of text and a table, an XLSX sheet, a CSV), times the
same parser the app uses, and writes docs/evaluations/limits_measure.json with throughput and how much of an
upload-limit-sized file fits in PARSE_TIME_BUDGET_S. Run from backend/:  python -m scripts.measure_limits
"""

import io
import json
import platform
import time

import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app import EVAL_DIR, docparse, limits


def pdf(pages: int) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for p in range(pages):
        for k in range(30):
            c.drawString(50, 800 - 20 * k, f"Line {k} of page {p}: LOT L{p % 90:02d} qty {k * 3} boards inspected")
        for r in range(5):
            for col in range(4):
                c.drawString(55 + col * 120, 180 - r * 20, f"r{r}c{col}")
        c.showPage()
    c.save()
    return buf.getvalue()


def xlsx(rows: int) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in range(rows):
        ws.append([f"L{r % 90:02d}", r, r * 2, "보드", f"note {r}"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(rows: int) -> bytes:
    return ("LOT,qty,defects,unit,note\n" + "".join(f"L{r % 90:02d},{r},{r * 2},보드,note {r}\n"
                                                    for r in range(rows))).encode("utf-8")


def timed(media: str, data: bytes) -> tuple[float, dict]:
    t0 = time.perf_counter()
    _, cov, _ = docparse.parse(media, data, docparse.Budget(10_000))
    return time.perf_counter() - t0, cov


def main() -> None:
    cap, budget = limits.get("MAX_UPLOAD_BYTES"), limits.get("PARSE_TIME_BUDGET_S")
    out = {"machine": platform.platform(), "python": platform.python_version(), "upload_cap_bytes": cap,
           "budget_s": budget, "runs": []}
    for kind, make, n, media in [("pdf", pdf, 40, "application/pdf"), ("xlsx", xlsx, 20000, docparse_xlsx()),
                                 ("csv", csv_bytes, 50000, "text/csv")]:
        data = make(n)
        secs, cov = timed(media, data)
        unit_per_byte = n / len(data)
        rate = n / secs
        at_cap = unit_per_byte * cap  # units in a file at the upload limit, same density
        out["runs"].append({"kind": kind, "units": n, "unit": "pages" if kind == "pdf" else "rows",
                            "bytes": len(data), "seconds": round(secs, 3), "units_per_s": round(rate, 1),
                            "units_at_upload_cap": round(at_cap), "seconds_at_upload_cap": round(at_cap / rate, 1),
                            "fits_in_budget": at_cap / rate <= budget, "render": cov.get("render")})
    (EVAL_DIR / "limits_measure.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in out["runs"]:
        print(r)


def docparse_xlsx() -> str:
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


if __name__ == "__main__":
    main()
