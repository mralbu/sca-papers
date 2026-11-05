"""marker's batch CLI with a safer ``save_output``. Run as ``python -m sca.marker_batch``.

marker 2.0 sometimes crops a zero-area figure; PIL then raises "cannot write
empty image as JPEG" part-way through saving, so every later figure of that
paper is lost. The replacement here drops empty figures (and their markdown
links) and writes the markdown last, so an existing ``.md`` implies its
figures and meta JSON were saved.

The patch is applied at import time: marker's workers use the ``spawn`` start
method, which re-imports this module (as ``__mp_main__``) in every worker.
"""

import json
import os
import re

import marker.scripts.convert as marker_convert
from marker.output import convert_if_not_rgb, text_from_rendered
from marker.settings import settings


def _is_empty(image) -> bool:
    return image.width == 0 or image.height == 0


def save_output(rendered, output_dir: str, fname_base: str) -> None:
    text, ext, images = text_from_rendered(rendered)
    text = text.encode(settings.OUTPUT_ENCODING, errors="replace").decode(settings.OUTPUT_ENCODING)
    for name in [n for n, img in images.items() if _is_empty(img)]:
        del images[name]
        text = re.sub(r"!\[[^\]]*\]\(" + re.escape(name) + r"\)", "", text)

    for name, img in images.items():
        convert_if_not_rgb(img).save(os.path.join(output_dir, name), settings.OUTPUT_IMAGE_FORMAT)
    with open(
        os.path.join(output_dir, f"{fname_base}_meta.json"), "w", encoding=settings.OUTPUT_ENCODING
    ) as f:
        f.write(json.dumps(rendered.metadata, indent=2))
    with open(
        os.path.join(output_dir, f"{fname_base}.{ext}"), "w", encoding=settings.OUTPUT_ENCODING
    ) as f:
        f.write(text)


marker_convert.save_output = save_output

if __name__ == "__main__":
    marker_convert.convert_cli()
