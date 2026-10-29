"""Small deterministic text ranking (Okapi BM25) with a fixed domain term map. No vector DB, no model.

Callers filter by scope, access and revision BEFORE ranking; this module only orders what they may see.
"""

import math
import re
from collections import Counter

VERSION = "bm25-k1.5-b0.75-terms1"
# Domain wording normalised to one term so a new phrasing still finds the record (shortcut: a hand list; replace
# with a measured synonym/embedding layer only once retrieval quality is evaluated on real wording).
TERMS = {"insufficient": "low", "shortfall": "low", "under": "low", "lower": "low", "deposit": "volume",
         "deposits": "volume", "paste": "solder", "overrun": "exceeded", "overdue": "exceeded",
         "exceed": "exceeded", "exceeds": "exceeded", "interval": "interval", "worn": "wear", "wearing": "wear",
         "clogged": "clog", "clogging": "clog", "apertures": "aperture", "cleaning": "clean", "cleaned": "clean",
         "wipe": "clean", "defects": "defect", "joints": "joint", "boards": "board", "stencils": "stencil",
         "replaced": "replace", "replacement": "replace", "calibration": "calibrate", "recalibration": "calibrate",
         "false": "false", "alarms": "alarm", "calls": "call", "bridging": "bridge"}
STOP = {"the", "a", "an", "of", "on", "in", "and", "or", "to", "for", "with", "is", "was", "were", "be", "by",
        "at", "from", "this", "that", "it", "as", "no", "not"}


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [TERMS.get(w, w) for w in words if w not in STOP and len(w) > 1]


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
