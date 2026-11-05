"""Stage: figure index and one WebP thumbnail per paper.

marker writes each extracted image next to the markdown and references it as
``![](_page_5_Figure_2.jpeg)``. A caption is the block right after the image
("**Figure 2.** ...", "Fig. 1. ...", "FIGURE 3 -"), or, failing that, the
block right before it (some older papers caption above). Each caption is
used once, by the image nearest to it.

Phase 1 pick (no LLM): the largest captioned image; without any caption, no
thumbnail. The pick is exported as a WebP thumbnail (max ``THUMB_WIDTH`` px
wide) to ``site/data/figures/<id>.webp``; the caption goes with it.

Output: ``data/figures/index.json`` (every image with page, kind, size,
caption, plus the pick per paper) and the thumbnails. Re-runs only redo papers
whose markdown is newer than their thumbnail.
"""

import json
import re
from pathlib import Path

from sca import cache, metadata, paths

INDEX = paths.FIGURES_DIR / "index.json"
THUMB_WIDTH = 480
WEBP_QUALITY = 60
MIN_PIXELS = 150 * 150  # skip icons, logos and rules
CAPTION_CHARS = 400

_IMAGE_RE = re.compile(r"^!\[[^\]]*\]\(([^)\s]+)\)\s*$")
_NAME_RE = re.compile(r"_page_(\d+)_([A-Za-z]+)_\d+\.\w+$")
_CAPTION_RE = re.compile(r"^\**\s*(?:fig(?:ure)?s?\.?|plate)\s*\d+", re.I)


def find_figures(md: str) -> list[dict]:
    """Images in reading order, each with the caption next to it (or None)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", md) if b.strip()]
    figures = []
    used: set[int] = set()
    for n, block in enumerate(blocks):
        m = _IMAGE_RE.match(block)
        if not m:
            continue
        caption = None
        for k in (n + 1, n - 1):
            if 0 <= k < len(blocks) and k not in used and _CAPTION_RE.match(blocks[k]):
                caption = metadata.clean_inline(blocks[k])[:CAPTION_CHARS]
                used.add(k)
                break
        name = m[1]
        page_kind = _NAME_RE.search(name)
        figures.append(
            {
                "file": name,
                "page": int(page_kind[1]) if page_kind else None,
                "kind": page_kind[2] if page_kind else None,
                "caption": caption,
            }
        )
    return figures


def pick(figures: list[dict]) -> dict | None:
    """The largest captioned image above the size floor."""
    candidates = [f for f in figures if f["caption"] and f.get("pixels", 0) >= MIN_PIXELS]
    return max(candidates, key=lambda f: f["pixels"], default=None)


def _thumbnail(src: Path, dst: Path) -> None:
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        if im.width > THUMB_WIDTH:
            im = im.resize((THUMB_WIDTH, round(im.height * THUMB_WIDTH / im.width)))
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp.webp")
        im.save(tmp, "WEBP", quality=WEBP_QUALITY, method=6)
        tmp.replace(dst)


def process(paper_id: str, old: dict | None) -> dict:
    from PIL import Image

    md = paths.MARKDOWN_DIR / paper_id / f"{paper_id}.md"
    thumb = paths.SITE_FIGURES_DIR / f"{paper_id}.webp"
    if old and (not old["pick"] or thumb.exists()) and cache.is_fresh(INDEX, md):
        return old
    figures = find_figures(md.read_text(encoding="utf-8", errors="replace"))
    for f in figures:
        path = md.parent / f["file"]
        try:
            with Image.open(path) as im:
                f["width"], f["height"] = im.size
                f["pixels"] = im.width * im.height
        except (OSError, ValueError):
            f["pixels"] = 0
    chosen = pick(figures)
    if chosen:
        _thumbnail(md.parent / chosen["file"], thumb)
    else:
        thumb.unlink(missing_ok=True)
    return {
        "figures": figures,
        "pick": {"file": chosen["file"], "caption": chosen["caption"]} if chosen else None,
    }


def run(force: bool = False) -> dict:
    records = json.loads(metadata.COMBINED.read_text(encoding="utf-8"))
    old = {} if force or not INDEX.exists() else json.loads(INDEX.read_text(encoding="utf-8"))
    index = {r["id"]: process(r["id"], old.get(r["id"])) for r in records if r["status"] == "ok"}
    # Thumbnails of papers that no longer have a pick (or no longer exist).
    keep = {f"{i}.webp" for i, v in index.items() if v["pick"]}
    if paths.SITE_FIGURES_DIR.exists():
        for f in paths.SITE_FIGURES_DIR.glob("*.webp"):
            if f.name not in keep:
                f.unlink()
    cache.write_json_atomic(INDEX, index)
    return index


def summary(index: dict) -> str:
    n = len(index)
    with_pick = sum(bool(v["pick"]) for v in index.values())
    images = sum(len(v["figures"]) for v in index.values())
    captioned = sum(bool(f["caption"]) for v in index.values() for f in v["figures"])
    size = sum(f.stat().st_size for f in paths.SITE_FIGURES_DIR.glob("*.webp"))
    return (
        f"{n} papers, {images} images ({captioned} captioned); thumbnail for {with_pick} papers, "
        f"{size / 1e6:.1f} MB in {paths.SITE_FIGURES_DIR.relative_to(paths.ROOT)}\n"
    )
