"""The same request gets the same answer (spec §26.5, user 2026-11-02). A model can answer an identical request
differently from one call to the next; wrapping the real provider, an answer is stored by the sha256 of everything
sent (model, messages, tools, schema, effort, temperature, seed, max tokens) and returned for that request again.
Only answers the provider returned are stored, never its errors. limits.MODEL_RESPONSE_REUSE = OFF calls anew.
"""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app import limits
from app.db import ModelResponse
from app.model_provider import sampling


class Reusing:
    def __init__(self, inner, sessions: sessionmaker):
        self.inner, self.sessions = inner, sessions

    def __getattr__(self, name):  # mode, model, external, url: the wrapped provider's
        return getattr(self.inner, name)

    def key(self, messages, tools, response_format, reasoning_effort) -> str:
        sent = {"model": self.inner.model, "url": getattr(self.inner, "url", None), "messages": messages,
                "tools": tools, "response_format": response_format, "reasoning_effort": reasoning_effort,
                "max_tokens": getattr(self.inner, "_max_tokens", None) or limits.get("MODEL_MAX_OUTPUT_TOKENS"),
                **sampling()}
        return hashlib.sha256(json.dumps(sent, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def chat(self, messages: list[dict], tools: list[dict], response_format: dict | None = None,
             reasoning_effort: str | None = None) -> dict:
        if limits.get("MODEL_RESPONSE_REUSE") != "ON":
            return self.inner.chat(messages, tools, response_format, reasoning_effort)
        key = self.key(messages, tools, response_format, reasoning_effort)
        try:
            with self.sessions() as s:
                row = s.scalar(select(ModelResponse).where(ModelResponse.request_sha256 == key))
        except OperationalError:  # the database is locked by the caller's own write: call the model, as with OFF
            row = None
        if row is not None:  # no new call, so no new usage or cost
            return {"message": row.message, "usage": {}, "reused": {"request_sha256": key, "stored_at":
                                                                     row.created_at}}
        out = self.inner.chat(messages, tools, response_format, reasoning_effort)
        try:
            with self.sessions.begin() as s:
                s.add(ModelResponse(request_sha256=key, model=self.inner.model, provider_mode=self.inner.mode,
                                    message=out["message"], usage=out.get("usage") or {},
                                    created_at=datetime.now(UTC).isoformat()))
        except IntegrityError:  # the same request answered at the same moment: the first stored answer stands
            pass
        except OperationalError:  # locked: the answer is used, only not stored for reuse
            pass
        return out
