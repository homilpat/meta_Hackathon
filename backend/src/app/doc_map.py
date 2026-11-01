"""A small map of a document for the model to navigate by (spec v5.8 §24): the author's own table of contents
when there is one (PDF bookmarks, DOCX heading styles, a contents page) and, always, one short entry per page
(PDF) or per section (DOCX, spreadsheets): its first line, its table header row, its captions and the words that
appear in no other part (so a part without a title still says what it holds).
The map is built by the server from the parse; nothing in it is a value the model may cite.
"""

import re
from collections import Counter, defaultdict

from app import retrieval


def unit_of(e: dict, section: str) -> str:
    """The part an element belongs to: p<page> for PDF, the current heading section for others."""
    return f"p{e['page']}" if "page" in e else section


def units(elements: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    section = "s0"
    for e in elements:
        if "page" not in e and e.get("heading") is not None:
            section = e["id"]
        if "page" not in e and e.get("sheet"):
            section = f"sheet:{e['sheet']}"
        out[unit_of(e, section)].append(e)
    return out


def build(elements: list[dict], coverage: dict) -> dict:
    """{toc: [...], parts: [{part, first, header, captions}]}; 'part' is what the model may ask for."""
    toc = [{"title": o["title"], "part": f"p{o['page']}", "level": o["level"]} for o in coverage.get("outline", [])]
    toc += [{"title": e["text"], "part": e["id"], "level": e["heading"]} for e in elements
            if e.get("heading") is not None and "page" not in e]
    toc_pages = coverage.get("toc_pages", [])
    parts = []
    grouped = units(elements)
    words = {part: set(retrieval.tokens(" ".join(e.get("text", "") for e in els))) for part, els in grouped.items()}
    seen = Counter(w for ws in words.values() for w in ws)
    for part, els in grouped.items():
        texts = [e for e in els if e["kind"] == "text"]
        cells = [e for e in els if e["kind"] == "cell"]
        top = min((c["row"] for c in cells), default=None)
        parts.append({"part": part, "first": texts[0]["text"][:120] if texts else "",
                      "header": [c["text"] for c in cells if c["row"] == top][:12],
                      "captions": [e["text"][:120] for e in els if any(x.get("caption_id") == e["id"] for x in els)],
                      # words found in no other part: what sets this part apart, when it has no title (TF-IDF's idea)
                      "unique": sorted(w for w in words[part] if seen[w] == 1 and not w.isdigit()),
                      "elements": len(els)})
    return {"toc": toc, "toc_pages": toc_pages, "heading_candidates": candidates(elements), "parts": parts}


SENTENCE_END = re.compile(r"[.!?。…]\s*$|[다요]\s*$")  # a sentence, not a heading (English and Korean endings)


def candidates(elements: list[dict]) -> list[dict]:
    """Lines that look like headings without the document saying so: standing alone, shorter than this document's
    median line, not ending like a sentence, not a bare number. The model decides which are real headings."""
    lines = [e for e in elements if e["kind"] == "text" and e.get("text", "").strip()]
    if not lines:
        return []
    median = sorted(len(e["text"]) for e in lines)[len(lines) // 2]
    # a line repeated in two or more parts is boilerplate (running header, footer, form text), not a heading
    shape = {e["id"]: re.sub(r"[\W\d_]+", "", e["text"].lower()) for e in lines}
    parts_of: dict[str, set] = defaultdict(set)
    for e in lines:
        parts_of[shape[e["id"]]].add(e.get("page", e["id"]))
    return [{"part": f"p{e['page']}" if "page" in e else e["id"], "id": e["id"], "text": e["text"]}
            for e in lines if len(e["text"]) < median and not SENTENCE_END.search(e["text"])
            and shape[e["id"]] and len(parts_of[shape[e["id"]]]) < 2]


def elements_of(elements: list[dict], part: str) -> list[dict]:
    return units(elements).get(part, [])
