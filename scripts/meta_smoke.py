"""One explicit, synthetic-only LIVE smoke call. Output never includes provider content."""

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.model_provider import MODEL, URL, read_key


def parse_answer(content: str) -> str:
    answer = json.loads(content)
    if answer != {"status": "ok"}:
        raise ValueError("Unexpected structured response")
    return answer["status"]


def main() -> int:
    key = read_key()
    if not key:
        print("LIVE NOT TESTED: MODEL_API_KEY is unset")
        return 2

    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Synthetic smoke check. Return status ok."}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "smoke",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["ok"]}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            },
        },
        "max_tokens": 64,
    }
    request = Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        if result.get("model") != MODEL:
            raise ValueError("Unexpected model ID")
        parse_answer(result["choices"][0]["message"]["content"])
    except (HTTPError, URLError, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"LIVE FAILED: {type(exc).__name__}")
        return 1
    print(f"LIVE SUCCESS: model={MODEL}, structured_status=ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

