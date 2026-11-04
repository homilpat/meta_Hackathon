"""Korean (or the language the AI operations department picks) on screen for English record text
(user 2026-11-04: "META가 번역못하냐"; 2026-11-05: language chosen on the admin screen).

The record keeps its original words (audit); the screen asks for a Korean rendering. The model translates, the
server checks each translation keeps every number and code of its original (L02, STN-2, U7, 0.12), and a translation
that drops or adds one is not shown: the original is. The provider is the response-reusing one, so the same text is
translated once and every later view reuses that answer at no cost.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import ModelResponse

from app import limits
from app.model_provider import ProviderError
from app.workflow import Actor

# no Hangul and three English words anywhere (not CODES): "AOI inspection A01 on board L02-P03/B4 reported FAIL."
ENGLISH = re.compile(r"^(?![\s\S]*[가-힣])(?:[\s\S]*?\b[A-Za-z][a-z]+\b){3}")
# codes like L02, STN-2, U7 first, then bare numbers; ASCII edges, since Korean particles touch them ("STN-2의")
TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)*\d[A-Z0-9]*|\d+(?:\.\d+)?)(?![A-Za-z0-9])")
# the language record text is shown in: the AI operations department picks it (limit TRANSLATE_LANGUAGE)
LANGS = {"ko": "Korean", "ja": "Japanese", "zh": "Simplified Chinese"}
PROMPT = """Translate each English text into natural {language} for a manufacturing quality engineer.
Keep every number, unit, part number, LOT, code and identifier exactly as written (L02, STN-2, U7, AOI, SPI, 0.12).
Translate only; add or drop nothing. Return ONLY the JSON: items with n and ko (the translation) for every text."""
SCHEMA = {"type": "json_schema", "json_schema": {"name": "translation", "strict": True, "schema": {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["n", "ko"],
        "properties": {"n": {"type": "integer"}, "ko": {"type": "string"}}}}}}}}


MEMO: dict[str, str] = {}  # key(text, language) -> translation: this process's view of the stored ones


def key(text: str, lang: str = "ko") -> str:
    return hashlib.sha256(f"translate-{lang}:{text}".encode()).hexdigest()


def remember(sessions, texts: list[str], lang: str) -> None:
    """Load stored translations of these texts (they survive a restart)."""
    if sessions is None:
        return
    want = {key(t, lang) for t in texts} - MEMO.keys()
    if want:
        with sessions() as s:
            for row in s.scalars(select(ModelResponse).where(ModelResponse.request_sha256.in_(want))):
                MEMO[row.request_sha256] = row.message.get("ko", "")


def store(sessions, provider, pairs: dict[str, str], lang: str) -> None:
    if sessions is None or not pairs:
        return
    try:
        with sessions.begin() as s:
            for t, ko in pairs.items():
                if not s.scalar(select(ModelResponse.id).where(ModelResponse.request_sha256 == key(t, lang))):
                    s.add(ModelResponse(request_sha256=key(t, lang), model=provider.model, provider_mode=provider.mode,
                                        message={"ko": ko, "text": t, "language": lang}, usage={},
                                        created_at=datetime.now(UTC).isoformat()))
    except (IntegrityError, OperationalError):
        pass  # kept in MEMO; stored next time


class TranslateIn(BaseModel):
    texts: list[str] = Field(max_length=40)


def kept(original: str, ko: str) -> bool:
    """The translation carries exactly the numbers and codes of its original."""
    return sorted(TOKEN.findall(original)) == sorted(TOKEN.findall(ko)) and bool(ko.strip())


def translate(provider, texts: list[str], sessions=None) -> dict[str, str]:
    """{original: translation} for the texts that need it and passed the check; the rest are left out (shown as is).
    Nothing is translated when the chosen language is OFF."""
    lang = limits.get("TRANSLATE_LANGUAGE")
    if lang not in LANGS:
        return {}
    want = list(dict.fromkeys(t for t in texts if t and len(t) <= 2000 and ENGLISH.search(t)))
    remember(sessions, want, lang)

    def known() -> dict[str, str]:
        return {t: MEMO[key(t, lang)] for t in want if key(t, lang) in MEMO}

    todo = [t for t in want if key(t, lang) not in MEMO]
    if provider is None or not todo:
        return known()
    try:
        msg = provider.chat([{"role": "system", "content": PROMPT.format(language=LANGS[lang])},
                             {"role": "user", "content": json.dumps(
                                 {"texts": [{"n": i, "text": t} for i, t in enumerate(todo, 1)]}, ensure_ascii=False)}],
                            [], response_format=SCHEMA)["message"]
        items = json.loads(msg.get("content") or "")["items"]
    except (ProviderError, ValueError, KeyError, TypeError):
        return known()  # no new translation: the screen shows the original
    new = {}
    for it in items:
        n = it.get("n") if isinstance(it, dict) else None
        if isinstance(n, int) and 1 <= n <= len(todo) and kept(todo[n - 1], str(it.get("ko") or "")):
            new[todo[n - 1]] = MEMO[key(todo[n - 1], lang)] = str(it["ko"]).strip()
    store(sessions, provider, new, lang)
    return known()


def make_translate_router(sessions, current_user: Callable[..., Actor], provider) -> APIRouter:
    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.post("/translations")
    def translations(body: TranslateIn, actor: Who) -> dict:
        # shortcut: no per-user quota; the request is capped at 40 texts and a repeated text reuses its stored
        # answer. Add a quota (like MODEL_RUNS_PER_USER_HOUR) if screens start sending new text at volume.
        return {"ko": translate(provider, body.texts, sessions)}

    return router
