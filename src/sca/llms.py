"""llms.txt files for the published site (https://llmstxt.org/ convention).

Written by ``site.run()`` from the same records as ``papers.json``, so they hold
only what the site already publishes, never full text or reference lists:

- ``site/llms.txt``: short index (what the corpus is, caveats, one link per topic).
- ``site/llms/<topic>.txt``: per topic, every paper with authors, method,
  keywords, TL;DR and AI summary, most central (PageRank) first.
- ``site/llms-full.txt``: the whole catalogue, one line per paper (all authors,
  method, keywords, TL;DR; no summary), grouped by topic.
"""

import re

from sca import cache, paths

SITE_URL = "https://mralbu.github.io/sca-papers/"
LLMS_TXT = paths.SITE_DIR / "llms.txt"
LLMS_FULL = paths.SITE_DIR / "llms-full.txt"
TOPIC_DIR = paths.SITE_DIR / "llms"  # generated; markdown in .txt so browsers show it

AI_NOTE = (
    "TL;DRs, summaries, keywords and method labels were written by Claude (Sonnet 5.5) "
    "from each paper's text and can contain errors; titles, authors and years come "
    "from the papers themselves. Check the PDF before relying on a detail."
)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "topic"


def one_line(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def link_text(text: str) -> str:
    """Escape what would break a markdown link label."""
    return one_line(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def paper_url(p: dict) -> str:
    return f"{SITE_URL}#{p['id']}"


def topic_files(topic_list: list[dict]) -> dict[int, str]:
    """Topic id -> file name, unique even if two names slug the same."""
    names, seen = {}, set()
    for t in sorted(topic_list, key=lambda t: t["id"]):
        name = slug(t["label"])
        if name in seen:
            name = f"{name}-{t['id']}"
        seen.add(name)
        names[t["id"]] = f"{name}.txt"
    return names


def by_topic(papers: list[dict], topic_list: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Topics largest first, each with its papers by PageRank (most central first)."""
    groups = {t["id"]: [] for t in topic_list}
    for p in papers:
        groups[p["topic"]].append(p)
    order = sorted(topic_list, key=lambda t: (-len(groups[t["id"]]), t["id"]))
    return [(t, sorted(groups[t["id"]], key=lambda p: -p["pagerank"])) for t in order]


def index(papers: list[dict], groups, files: dict[int, str]) -> str:
    years = [p["year"] for p in papers]
    lines = [
        "# SCA Papers Explorer",
        "",
        f"> An explorer for the {len(papers):,} papers of the Society of Core Analysts (SCA) "
        f"symposium, {min(years)}–{max(years)}: core analysis and petrophysics (SCAL, "
        "wettability, capillary pressure, relative permeability, NMR, digital rock and more), "
        "grouped by topic, with in-corpus citations and AI-written summaries. The PDFs are "
        "hosted by jgmaas.com and linked from each entry.",
        "",
        f"- {AI_NOTE}",
        "- Citation counts only cover citations between papers in this corpus.",
        f"- Each paper has a page at `{SITE_URL}#<ID>` (e.g. `#SCA2014-051`) and a PDF link.",
        "- Topics come from clustering text embeddings; method labels are a fixed list of 8.",
        "",
        "## Topics",
        "",
    ]
    for t, ps in groups:
        lines.append(
            f"- [{link_text(t['label'])}]({SITE_URL}llms/{files[t['id']]}): {len(ps)} papers. "
            f"Keywords: {', '.join(t['keywords'][:6])}"
        )
    lines += [
        "",
        "## Data",
        "",
        f"- [All papers, one line each]({SITE_URL}llms-full.txt): ID, year, title, all "
        "authors, method, keywords and TL;DR, grouped by topic",
        f"- [papers.json]({SITE_URL}data/papers.json): the site's full data as JSON "
        "(abstracts, map coordinates, PageRank, citation and similar-paper links)",
        f"- [topics.json]({SITE_URL}data/topics.json): topic names, keywords and sizes",
        "",
        "## Optional",
        "",
        "- [SCA papers on jgmaas.com](https://www.jgmaas.com/SCA/): the original PDF archive",
        "",
    ]
    return "\n".join(lines)


def topic_page(t: dict, ps: list[dict]) -> str:
    lines = [
        f"# {one_line(t['label'])}",
        "",
        f"> {len(ps)} SCA symposium papers in this topic, most central in the citation "
        f"graph (PageRank) first. Topic keywords: {', '.join(t['keywords'])}.",
        "",
        f"{AI_NOTE} Index of all topics: {SITE_URL}llms.txt",
        "",
    ]
    for p in ps:
        lines += [f"## {one_line(p['title'])}", ""]
        lines.append(f"- ID: {p['id']}, year: {p['year']}")
        if p["authors"]:
            lines.append(f"- Authors: {', '.join(p['authors'])}")
        if p.get("method"):
            lines.append(f"- Method: {p['method']}")
        if p.get("keywords"):
            lines.append(f"- Keywords: {', '.join(p['keywords'])}")
        lines.append(f"- Cited by {p['cited_by']} papers in the corpus, cites {len(p['cites'])}")
        lines.append(f"- [PDF]({p['url']}) · [On the site]({paper_url(p)})")
        lines.append("")
        for text in (p.get("tldr"), p.get("summary")):
            if text:
                lines += [one_line(text), ""]
    return "\n".join(lines)


def full_line(p: dict) -> str:
    parts = [f"- [{link_text(p['title'])}]({p['url']}) — {p['id']}, {p['year']}."]
    if p["authors"]:
        parts.append(f"{', '.join(p['authors'])}.")
    if p.get("method"):
        parts.append(f"Method: {p['method']}.")
    if p.get("keywords"):
        parts.append(f"Keywords: {', '.join(p['keywords'])}.")
    if p.get("tldr"):
        parts.append(one_line(p["tldr"]))
    return " ".join(parts)


def full(papers: list[dict], groups) -> str:
    lines = [
        "# SCA Papers Explorer: all papers",
        "",
        f"> All {len(papers):,} Society of Core Analysts symposium papers, one line each: "
        "title (linked to the PDF), ID, year, authors, method, keywords and TL;DR. "
        "Grouped by topic (largest first), most central (PageRank) first within a topic.",
        "",
        f"{AI_NOTE} Per-topic files with longer summaries: {SITE_URL}llms.txt",
        "",
    ]
    for t, ps in groups:
        lines += [f"## {one_line(t['label'])}", "", *map(full_line, ps), ""]
    return "\n".join(lines)


def write(papers: list[dict], topic_list: list[dict]) -> list:
    """Write every llms file (replacing stale topic files); returns their paths."""
    files = topic_files(topic_list)
    groups = by_topic(papers, topic_list)
    TOPIC_DIR.mkdir(parents=True, exist_ok=True)
    for old in TOPIC_DIR.iterdir():  # stale topics (and .md files from before the rename)
        if old.name not in files.values():
            old.unlink()
    out = []
    for t, ps in groups:
        path = TOPIC_DIR / files[t["id"]]
        cache.write_text_atomic(path, topic_page(t, ps))
        out.append(path)
    cache.write_text_atomic(LLMS_TXT, index(papers, groups, files))
    cache.write_text_atomic(LLMS_FULL, full(papers, groups))
    return [LLMS_TXT, LLMS_FULL, *out]
