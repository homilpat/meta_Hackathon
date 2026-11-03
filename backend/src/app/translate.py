"""Korean on screen for English record text (user 2026-11-04: "META가 번역못하냐").

The record keeps its original words (audit); the screen asks for a Korean rendering. The model translates, the
server checks each translation keeps every number and code of its original (L02, STN-2, U7, 0.12), and a translation
that drops or adds one is not shown: the original is. The provider is the response-reusing one, so the same text is
translated once and every later view reuses that answer at no cost.
"""

import json
import re
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.model_provider import ProviderError
from app.workflow import Actor

ENGLISH = re.compile(r"[A-Za-z][a-z]{2,}(?:[^A-Za-z가-힣]+[A-Za-z][a-z]+){2,}")  # three English words (not CODES)
# codes like L02, STN-2, U7 first, then bare numbers; ASCII edges, since Korean particles touch them ("STN-2의")
TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*\d[A-Z0-9]*|\d+(?:\.\d+)?)(?![A-Za-z0-9])")
PROMPT = """Translate each English text into natural Korean for a manufacturing quality engineer.
Keep every number, unit, part number, LOT, code and identifier exactly as written (L02, STN-2, U7, AOI, SPI, 0.12).
Translate only; add or drop nothing. Return ONLY the JSON: items with n and ko for every text."""
SCHEMA = {"type": "json_schema", "json_schema": {"name": "translation", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["n", "ko"],
        "properties": {"n": {"type": "integer"}, "ko": {"type": "string"}}}}}}}}


# shortcut: per-sentence memory for this server process (a batch-level answer is also stored by the reusing
# provider); move it to a table if translations must survive a restart without a model call.
MEMO: dict[str, str] = {}


class TranslateIn(BaseModel):
    texts: list[str] = Field(max_length=40)


def kept(original: str, ko: str) -> bool:
    """The translation carries exactly the numbers and codes of its original."""
    return sorted(TOKEN.findall(original)) == sorted(TOKEN.findall(ko)) and bool(ko.strip())


def translate(provider, texts: list[str]) -> dict[str, str]:
    """{original: Korean} for the texts that need it and passed the check; the rest are left out (shown as is)."""
    want = list(dict.fromkeys(t for t in texts if t and len(t) <= 2000 and ENGLISH.search(t)))
    todo = [t for t in want if t not in MEMO]
    if provider is None or not todo:
        return {t: MEMO[t] for t in want if t in MEMO}
    try:
        msg = provider.chat([{"role": "system", "content": PROMPT},
                             {"role": "user", "content": json.dumps(
                                 {"texts": [{"n": i, "text": t} for i, t in enumerate(todo, 1)]}, ensure_ascii=False)}],
                            [], response_format=SCHEMA)["message"]
        items = json.loads(msg.get("content") or "")["items"]
    except (ProviderError, ValueError, KeyError, TypeError):
        return {t: MEMO[t] for t in want if t in MEMO}  # no new translation: the screen shows the original
    out = {t: MEMO[t] for t in want if t in MEMO}
    for it in items:
        n = it.get("n") if isinstance(it, dict) else None
        if isinstance(n, int) and 1 <= n <= len(todo) and kept(todo[n - 1], str(it.get("ko") or "")):
            out[todo[n - 1]] = MEMO[todo[n - 1]] = str(it["ko"]).strip()
    return out


def make_translate_router(current_user: Callable[..., Actor], provider) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.post("/translations")
    def translations(body: TranslateIn, actor: Who) -> dict:
        # shortcut: no per-user quota; the request is capped at 40 texts and a repeated text reuses its stored
        # answer. Add a quota (like MODEL_RUNS_PER_USER_HOUR) if screens start sending new text at volume.
        return {"ko": translate(provider, body.texts)}

    return router
