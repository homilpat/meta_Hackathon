"""Small deterministic text ranking (Okapi BM25) with a fixed domain term map. No vector DB, no model.

Callers filter by scope, access and revision BEFORE ranking; this module only orders what they may see.
"""

import math
import re
from collections import Counter

from app.glossary import GLOSSARY, PARTICLES

VERSION = "bm25-k1.5-b0.75-glossary2"
# Any wording of a concept, in any language, becomes its canonical term (see app/glossary.py; shortcut: a hand list,
# replace with a measured synonym/embedding layer only once retrieval quality is evaluated on real wording).
TERMS = {w.lower(): canon for canon, words in GLOSSARY.items() for w in (canon, *words)}
LONGEST = max(map(len, TERMS))
STOP = {"the", "a", "an", "of", "on", "in", "and", "or", "to", "for", "with", "is", "was", "were", "be", "by",
        "at", "from", "this", "that", "it", "as", "no", "not"}


def _strip(rest: str) -> str:
    for p in PARTICLES:
        if rest.endswith(p) and len(rest) > len(p):
            return rest[: -len(p)]
    return "" if rest in PARTICLES else rest


def _segment(word: str) -> list[str]:
    """Non-ASCII words: glossary words cut out from the left, longest first, so suffixes (Korean particles) and
    scripts written without spaces (Japanese, Chinese) still match; unknown stretches are kept as written."""
    out, rest, i = [], "", 0
    while i < len(word):
        hit = next((word[i:i + n] for n in range(min(LONGEST, len(word) - i), 1, -1) if word[i:i + n] in TERMS),
                   None)
        if hit is None:
            rest, i = rest + word[i], i + 1
            continue
        out += [_strip(rest), hit] if rest else [hit]
        rest, i = "", i + len(hit)
    return [*out, _strip(rest)] if rest else out


def tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[^\W_]+", text.lower()):
        for piece in ([w] if w.isascii() else _segment(w)):
            if piece in STOP or len(piece) < 2:
                continue
            out += TERMS.get(piece, piece).split()
    return out


def bm25(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[tuple[float, list[str]]]:
    """(score, matched terms) per doc, in input order. Score 0 means no shared term."""
    toks = [tokens(d) for d in docs]
    if not toks:
        return []
    avg = sum(map(len, toks)) / len(toks) or 1.0
    df = Counter(t for doc in toks for t in set(doc))
    q = list(dict.fromkeys(tokens(query)))
    out = []
    for doc in toks:
        tf, score, hit = Counter(doc), 0.0, []
        for t in q:
            if not tf[t]:
                continue
            idf = math.log(1 + (len(toks) - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(doc) / avg))
            hit.append(t)
        out.append((round(score, 4), hit))
    return out
