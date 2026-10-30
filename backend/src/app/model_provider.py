"""Model provider boundary. LIVE = Meta Muse Spark over HTTPS; anything else must declare itself."""

import json
import os
import re
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app import REPO_ROOT

MODEL = "muse-spark-1.3"
URL = "https://api.meta.ai/v1/chat/completions"
# Last-line egress check on the exact bytes we are about to send.
SECRET_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}|\bsk-[A-Za-z0-9]{10,}|MODEL_API_KEY\s*=")
# Backstop for the data-rights gate in tools.py: rows marked anything but SYNTHETIC/APPROVED_FOR_EXTERNAL
# never leave, even if an upstream check is bypassed. Matches JSON nested inside tool-result strings too.
# The marker word is matched in capitals only, so a model reply saying "no confidential data" does not abort a run.
RESTRICTED_PATTERN = re.compile(r'(?i:\\?"(?:data_origin|sensitivity|source_origin)\\?"\s*:\s*\\?"'
                                r"(?!SYNTHETIC\b|APPROVED_FOR_EXTERNAL\b))|\bCONFIDENTIAL")


class ProviderError(Exception):
    """Transport, HTTP, timeout or response-shape failure. Never reported as success."""


class EgressBlocked(ProviderError):
    """Outbound payload contained something that must not leave the machine."""


class ModelProvider(Protocol):
    mode: str  # "LIVE" for the real provider; test doubles must use "TEST_DOUBLE"
    model: str

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return {"message": assistant message dict, "usage": dict}."""


def read_key() -> str:
    if "MODEL_API_KEY" in os.environ:  # set, even to "", wins: the offline smoke/E2E servers must not pick up .env
        return os.environ["MODEL_API_KEY"].strip()
    for env in (Path(".env"), REPO_ROOT / ".env"):  # working directory first (as before), then the repo root
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("MODEL_API_KEY="):
                    return line.partition("=")[2].strip().strip('"').strip("'")
    return ""


class MetaProvider:
    mode = "LIVE"
    model = MODEL

    # muse-spark reasons before it answers: 1500 and 4096 tokens both cut a LIVE investigation report off
    def __init__(self, key: str, timeout: float = 60.0, max_tokens: int = 8192, opener=urlopen):
        self._key, self._timeout, self._max_tokens, self._open = key, timeout, max_tokens, opener

    @classmethod
    def from_env(cls) -> "MetaProvider | None":
        key = read_key()
        return cls(key) if key else None

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        body = json.dumps({"model": MODEL, "messages": messages, "tools": tools,
                           "max_tokens": self._max_tokens}).encode("utf-8")
        text = body.decode("utf-8")
        if self._key in text or SECRET_PATTERN.search(text):
            raise EgressBlocked("secret-like content in outbound payload")
        if RESTRICTED_PATTERN.search(text):
            raise EgressBlocked("data not approved for external processing in outbound payload")
        request = Request(URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        try:
            with self._open(request, timeout=self._timeout) as response:
                result = json.load(response)
            if result.get("model") != MODEL:
                raise ProviderError("unexpected model id in response")
            choice = result["choices"][0]
            # A reasoning model can spend max_tokens before or while answering (seen LIVE): a cut-off reply is a
            # failure, never a short or partial answer handed on as complete.
            if choice.get("finish_reason") == "length":
                raise ProviderError("answer cut off at max_tokens (finish_reason=length)")
            if not choice["message"].get("content") and not choice["message"].get("tool_calls"):
                raise ProviderError(f"no answer or tool call (finish_reason={choice.get('finish_reason')})")
            return {"message": choice["message"], "usage": result.get("usage") or {}}
        except ProviderError:
            raise
        except HTTPError as exc:
            raise ProviderError(f"HTTP {exc.code}") from None
        except TimeoutError:
            raise ProviderError("timeout") from None
        except URLError as exc:
            raise ProviderError(f"network: {type(exc.reason).__name__}") from None
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"malformed response: {type(exc).__name__}") from None
