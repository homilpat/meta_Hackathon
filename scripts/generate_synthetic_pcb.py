"""Emit the reproducible S1 fixture as JSON. Never emits real manufacturing records."""

import argparse
import json
from pathlib import Path

from app.synthetic import generate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    content = json.dumps(generate(args.seed), ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.write_text(content + "\n", encoding="utf-8")
    else:
        print(content)


if __name__ == "__main__":
    main()
