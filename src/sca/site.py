"""Stage: export the published site data (``site/data/``).

Joins metadata, topics, citation scores and figure picks into
``site/data/papers.json`` and ``site/data/topics.json``. Only derived data and
metadata go here: title, authors, year, abstract, topic, map position, scores,
in-corpus citation links, the figure caption, and the LLM summary fields (TL;DR,
summary, keywords, method, figure reason). Never full text, reference lists or
PDFs (the site links to the original PDF on jgmaas.com).

Rule-based metadata stays primary: an LLM title, author list or abstract is
used only where the rules found none, and only if it passed ``summarize.verify``
(``filled`` lists those fields so the front end can say so).

Set ``INCLUDE_ABSTRACTS = False`` to publish without abstracts.
"""

import json
import re
from collections import defaultdict

import numpy as np

from sca import cache, citations, embed, figures, metadata, paths, summarize, topics

INCLUDE_ABSTRACTS = True
PAPERS_JSON = paths.SITE_DATA_DIR / "papers.json"
TOPICS_JSON = paths.SITE_DATA_DIR / "topics.json"
MAX_FILE_BYTES = 100 * 10**6  # GitHub Pages per-file limit
N_SIMILAR = 8

# Kept upper case when an ALL-CAPS title is re-cased for display.
ACRONYMS = {
    "NMR",
    "SCAL",
    "RCAL",
    "CT",
    "MRI",
    "EOR",
    "IOR",
    "CO2",
    "SEM",
    "XRD",
    "MICP",
    "USBM",
    "FIB",
    "DRP",
    "LSW",
    "SAGD",
    "API",
    "PVT",
    "MCT",
    "NAPL",
    "DNAPL",
    "LNAPL",
    "UK",
    "USA",
    "II",
    "III",
    "IV",
    "ESEM",
    "CPMG",
    "T1",
    "T2",
    "H2",
    "CH4",
    "N2",
    "GPU",
    "3D",
    "2D",
    "4D",
    "1D",
    "AI",
    "ML",
    "CNN",
    "PNM",
    "LBM",
    "TOC",
    "HPHT",
    "PFG",
    "PGSE",
    "DDIF",
}
SPECIAL = {"PH": "pH"}
SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
    "via",
    "with",
}


def display_title(title: str) -> str:
    """Title-case a title that is mostly upper case; leave mixed-case titles alone."""
    letters = [c for c in metadata.MATH_SPAN_RE.sub(" ", title) if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return title

    def word(m: re.Match, first: bool) -> str:
        w = m.group(0)
        if w in SPECIAL:
            return SPECIAL[w]
        if w in ACRONYMS or any(c.isdigit() for c in w) or not re.search(r"[AEIOUY]", w):
            return w
        lw = w.lower()
        return lw if lw in SMALL_WORDS and not first else lw[:1].upper() + lw[1:]

    # Math spans stay as they are: swap them for placeholders while re-casing.
    maths: list[str] = []

    def hold(m: re.Match) -> str:
        maths.append(m.group(0))
        return f"\x00{len(maths) - 1}\x00"

    held = metadata.MATH_SPAN_RE.sub(hold, title)
    out, first = [], True
    for part in re.split(r"(\s+)", held):
        out.append(re.sub(r"[A-Za-z0-9]+", lambda m, f=first: word(m, f), part))
        if part.strip():
            first = part.endswith(":")
    return re.sub(r"\x00(\d+)\x00", lambda m: maths[int(m.group(1))], "".join(out))


def similar(model: str, k: int = N_SIMILAR) -> dict[str, list[str]]:
    """The k nearest papers to each paper by cosine similarity (vectors are L2-normalised)."""
    ids, vectors = embed.load(model)
    sims = vectors @ vectors.T
    np.fill_diagonal(sims, -np.inf)
    top = np.argsort(-sims, axis=1)[:, :k]
    return {pid: [ids[j] for j in row] for pid, row in zip(ids, top, strict=True)}


def llm_fields(r: dict, record: dict | None) -> tuple[dict, dict]:
    """Published LLM fields, and checked values for the metadata fields the rules
    left empty (title, authors, abstract)."""
    if not record:
        return {}, {}
    res, checks = record["result"], record["checks"]
    published = {
        "tldr": res["tldr"],
        "summary": res["summary"],
        "keywords": res["keywords"],
        "method": res["method"],
    }
    fills = {}
    if not r["title"] and checks["title"]:
        fills["title"] = res["title"]
    if not r["authors"]:
        good = [a for a, ok in zip(res["authors"], checks["authors"], strict=True) if ok]
        if good:
            fills["authors"] = good
    if not r["abstract"] and checks["abstract"]:
        fills["abstract"] = res["abstract"]
    return published, fills


def build() -> tuple[list[dict], list[dict]]:
    records = json.loads(metadata.COMBINED.read_text(encoding="utf-8"))
    topic_data = json.loads(topics.OUTPUT.read_text(encoding="utf-8"))
    cite_data = json.loads(citations.OUTPUT.read_text(encoding="utf-8"))
    fig_index = json.loads(figures.INDEX.read_text(encoding="utf-8"))
    neighbours = similar(topic_data["model"])
    cites, cited = defaultdict(list), defaultdict(list)
    for e in cite_data["edges"]:
        cites[e["source"]].append(e["target"])
        cited[e["target"]].append(e["source"])
    papers = []
    for r in records:
        pos = topic_data["papers"].get(r["id"])
        if not pos:  # no usable text (e.g. the unreadable SCA2014-051)
            continue
        score = cite_data["scores"][r["id"]]
        pick = (fig_index.get(r["id"]) or {}).get("pick")
        llm, fills = llm_fields(r, summarize.load(r["id"]))
        title = fills.get("title") or r["title"]
        paper = {
            "id": r["id"],
            "title": display_title(title) if title else r["id"],
            "authors": fills.get("authors", r["authors"]),
            "year": r["year"],
            "series": r["series"],
            "url": r["url"],
            "topic": pos["topic"],
            "outlier": pos["outlier"],
            "x": pos["x"],
            "y": pos["y"],
            "cited_by": score["cited_by"],
            "pagerank": score["pagerank"],
            "cites": sorted(cites[r["id"]]),
            "cited": sorted(cited[r["id"]]),
            "similar": neighbours.get(r["id"], []),
            "figure": f"data/figures/{r['id']}.webp" if pick else None,
            "caption": pick["caption"] if pick else None,
            "figure_reason": pick.get("reason") if pick else None,
            **llm,
        }
        if INCLUDE_ABSTRACTS:
            paper["abstract"] = fills.get("abstract", r["abstract"])
        elif "abstract" in fills:
            del fills["abstract"]
        if fills:
            paper["filled"] = sorted(fills)
        papers.append(paper)
    return papers, topic_data["topics"]


def run() -> str:
    papers, topic_list = build()
    cache.write_text_atomic(
        PAPERS_JSON, json.dumps(papers, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    cache.write_json_atomic(TOPICS_JSON, topic_list)
    figures_bytes = sum(f.stat().st_size for f in paths.SITE_FIGURES_DIR.glob("*.webp"))
    sizes = {p: p.stat().st_size for p in (PAPERS_JSON, TOPICS_JSON)}
    too_big = [p.name for p, s in sizes.items() if s > MAX_FILE_BYTES]
    if too_big:
        raise SystemExit(f"over the 100 MB GitHub Pages file limit: {too_big}")
    total = sum(f.stat().st_size for f in paths.SITE_DIR.rglob("*") if f.is_file())
    return (
        f"{len(papers)} papers, {len(topic_list)} topics -> {PAPERS_JSON.relative_to(paths.ROOT)} "
        f"({sizes[PAPERS_JSON] / 1e6:.1f} MB), figures {figures_bytes / 1e6:.1f} MB, "
        f"site total {total / 1e6:.1f} MB\n"
    )
