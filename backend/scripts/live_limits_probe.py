"""LIVE probes behind two limits (META_LIVE_LOG): how many images muse-spark-1.3 takes in one call, and whether
document extraction needs more than minimal reasoning. A few LIVE calls; may incur charges. Run from backend/:
    python -m scripts.live_limits_probe images|effort
"""

import base64
import io
import sys
import time

from PIL import Image, ImageDraw

from app import intake_extract
from app.model_provider import MetaProvider, ProviderError
from scripts import intake_live_check


def png(n: int) -> str:
    img = Image.new("RGB", (120, 60), "white")
    ImageDraw.Draw(img).text((10, 20), f"IMG {n}", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def images(p) -> None:
    for n in (9, 10):
        parts = [{"type": "text", "text": "Reply with the labels you can read, comma separated."}]
        parts += [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png(k)}"}} for k in range(1, n + 1)]
        t0 = time.perf_counter()
        try:
            r = p.chat([{"role": "user", "content": parts}], [], reasoning_effort="minimal")
            text = r["message"].get("content") or ""
            print(f"{n} images: OK {time.perf_counter() - t0:.1f}s labels_read={sum(f'IMG {k}' in text for k in range(1, n + 1))}")
        except ProviderError as exc:
            print(f"{n} images: REFUSED {time.perf_counter() - t0:.1f}s {exc}")


def effort(p) -> None:
    for e in ("minimal", "default"):
        intake_extract.EXTRACT_EFFORT = e
        t0 = time.perf_counter()
        res = intake_live_check.single(p)
        print(f"effort={e}: {sum(r['ok'] for r in res['rows'])}/{len(res['rows'])} "
              f"in {time.perf_counter() - t0:.1f}s; misses {[r['field'] for r in res['rows'] if not r['ok']]}")


if __name__ == "__main__":
    provider = MetaProvider.from_env()
    if provider is None:
        print("NOT_RUN: no MODEL_API_KEY")
        sys.exit(2)
    {"images": images, "effort": effort}[sys.argv[1]](provider)
