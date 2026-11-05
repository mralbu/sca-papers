"""Stage: export the published site data (``site/data/``).

Joins metadata, topics, citation scores and figure picks into
``site/data/papers.json`` and ``site/data/topics.json``. Only derived data and
metadata go here: title, authors, year, abstract, topic, map position, scores,
in-corpus citation links and the figure caption. Never full text, reference
lists or PDFs (the site links to the original PDF on jgmaas.com).

Set ``INCLUDE_ABSTRACTS = False`` to publish without abstracts.
"""

import json
from collections import defaultdict

from sca import cache, citations, figures, metadata, paths, topics

INCLUDE_ABSTRACTS = True
PAPERS_JSON = paths.SITE_DATA_DIR / "papers.json"
TOPICS_JSON = paths.SITE_DATA_DIR / "topics.json"
MAX_FILE_BYTES = 100 * 10**6  # GitHub Pages per-file limit


def build() -> tuple[list[dict], list[dict]]:
    records = json.loads(metadata.COMBINED.read_text(encoding="utf-8"))
    topic_data = json.loads(topics.OUTPUT.read_text(encoding="utf-8"))
    cite_data = json.loads(citations.OUTPUT.read_text(encoding="utf-8"))
    fig_index = json.loads(figures.INDEX.read_text(encoding="utf-8"))
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
        paper = {
            "id": r["id"],
            "title": r["title"] or r["id"],
            "authors": r["authors"],
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
            "figure": f"data/figures/{r['id']}.webp" if pick else None,
            "caption": pick["caption"] if pick else None,
        }
        if INCLUDE_ABSTRACTS:
            paper["abstract"] = r["abstract"]
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
