"""How well does the server's selection (app/doc_select.py) catch the values in a long document? Offline, no model.

Builds a 120-page synthetic complaint dossier: a cover page with no values, the values scattered on far pages
(reference on p.37, a LOT/quantity table on p.80, the deadline on p.115, the phenomenon on p.52), and filler pages
that reuse the same words in other senses ("lot of", "quantity discount", "reply soon"). For each round it reports
which fields' true elements were selected, how many elements and estimated tokens went out against the whole
document. Writes docs/evaluations/select_eval.json. Run from backend/:  python -m scripts.select_eval
"""

import io
import json

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app import EVAL_DIR, docparse, limits
from app.doc_select import select

PAGES = 120
TRUTH = {  # field -> (page, text the value line contains)
    "customer_ref": (37, "Customer reference: QX-2026-5512"),
    "phenomenon": (52, "Phenomenon: lifted lead on Q4 after wave soldering"),
    "lot": (80, "LQ7"),
    "defective_qty": (80, "19"),
    "inspected_qty": (80, "640"),
    "reply_deadline": (115, "Please reply by 2026-11-20 18:00 KST"),
}
FILLER = ["We bought a lot of new fixtures this quarter for the assembly hall.",
          "Quantity discounts apply to orders above the usual volume.",
          "Please reply soon to the meeting invitation for the audit dinner.",
          "The reference design was shared with the layout team last year.",
          "General notes on handling, storage and packaging of boards.",
          "Customer satisfaction survey results will follow in a separate mail."]


def dossier() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    for p in range(1, PAGES + 1):
        y = 800
        if p == 1:
            c.drawString(50, y, "SYNTHETIC TEST DOSSIER - Quality correspondence, collected appendix")
        for k in range(24):
            y -= 25
            c.drawString(50, y, f"{FILLER[(p + k) % len(FILLER)]} (p{p}-{k})")
        if p == 37:
            c.drawString(50, 120, TRUTH["customer_ref"][1])
        if p == 52:
            c.drawString(50, 120, TRUTH["phenomenon"][1])
        if p == 80:
            for r, row in enumerate([["LOT", "Inspected qty", "Defective qty"], ["LQ7", "640", "19"]]):
                for k, cell in enumerate(row):
                    c.drawString(55 + k * 150, 140 - r * 20, cell)
        if p == 115:
            c.drawString(50, 120, TRUTH["reply_deadline"][1])
        c.showPage()
    c.save()
    return buf.getvalue()


def caught(elements: list[dict], ids: set[str]) -> dict[str, bool]:
    out = {}
    for field, (page, text) in TRUTH.items():
        hits = [e["id"] for e in elements if e.get("page") == page and text in e.get("text", "")]
        out[field] = any(h in ids for h in hits)
    return out


def main() -> None:
    elements, _, _ = docparse.parse("application/pdf", dossier(), docparse.Budget(10_000))
    total_tokens = sum(limits.estimate_tokens(json.dumps(e, ensure_ascii=False)) for e in elements)
    sent: set[str] = set()
    skip: dict[str, int] = {}
    rounds = []
    fields = list(TRUTH)
    for r in range(1, 4):
        ids, rep = select(elements, fields, skip, base=(r == 1))
        sent |= set(ids)
        got = caught(elements, sent)
        tokens = sum(limits.estimate_tokens(json.dumps(e, ensure_ascii=False)) for e in elements if e["id"] in sent)
        rounds.append({"round": r, "elements_sent_total": len(sent), "tokens_sent_total": tokens,
                       "caught": got, "caught_n": sum(got.values()), "hits": rep["hits"]})
        fields = [f for f, ok in got.items() if not ok]  # what a model would still be missing
        for f in fields:
            skip[f] = skip.get(f, 0) + 1
        if not fields:
            break
    out = {"pages": PAGES, "elements": len(elements), "tokens_whole_document": total_tokens, "rounds": rounds}
    (EVAL_DIR / "select_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"whole document: {len(elements)} elements, ~{total_tokens} tokens")
    for r in rounds:
        print(f"round {r['round']}: sent {r['elements_sent_total']} elements ~{r['tokens_sent_total']} tokens, "
              f"caught {r['caught_n']}/{len(TRUTH)} {[f for f, ok in r['caught'].items() if not ok] or ''}")


if __name__ == "__main__":
    main()
