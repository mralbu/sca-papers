# SCA Papers Explorer

**[Open the explorer →](https://mralbu.github.io/sca-papers/)**
(live once GitHub Pages is enabled for the repo; see [Publishing](#publishing))

An interactive explorer for the 2,064 Society of Core Analysts (SCA) symposium
papers from 1987–2026, mirrored at <https://www.jgmaas.com/SCA/>. Browse them
as a list or as a topic map, read an AI summary of each paper, and follow
similar papers and citations to the original PDF.

## Features

- **List and map views.** A sortable list (newest, oldest, most cited,
  PageRank, best match) and a 2D map of the papers clustered into 30 topics,
  with points sized by citation importance.
- **Search and filters.** Full-text search over titles, authors, keywords,
  abstracts and summaries; year range; topic filter.
- **Reading pane per paper.** AI-generated TL;DR, summary and keywords (click a
  keyword to search for it), the paper's own abstract, a key figure with the
  reason it was picked, "Show on map", a copyable link, and the PDF on
  jgmaas.com.
- **Related papers.** Similar papers (nearest neighbours by embedding), papers
  that cite it and papers it cites, within the corpus.
- **Readable topics.** Topics are named by an LLM from their keywords and
  titles ("NMR relaxation and pore size", "Centrifuge capillary pressure
  methods").
- Inline math in titles, abstracts and captions is rendered with KaTeX.
  Keyboard shortcuts: **R** reading mode, **M** show on map, **Esc** close.

## What is published

Only derived data: title, authors, year, abstract, topic, map coordinates,
citation scores and links, similar papers, AI summaries (TL;DR, summary,
keywords, method label, why the figure was picked) and one small figure
thumbnail per paper. PDFs, full text and reference lists stay local; the site
links to the original PDF on jgmaas.com. The papers belong to SCA.

## Quick start

```sh
just setup            # Python environment
just download         # mirror the PDFs into papers/ (re-run to update)
just dedup            # drop 1991/1992 preview PDFs (recorded in duplicates.txt)
just convert          # PDF -> markdown with marker (slow; resumable)
just build            # metadata, embeddings, topics, citations, figures, site data
just serve            # preview the site at http://localhost:8000
```

`just build` runs every stage except the AI steps (Claude API, paid). To
include them:

```sh
just summarize --all --batch   # AI summaries, keywords, figure picks (paid)
just topic-names               # AI topic names (paid, a few cents)
just figures && just site-data # use the AI figure picks and names on the site
```

Every stage is cached and resumable, so a re-run only processes new or changed
papers. Run `just` for the full list of recipes and their arguments.

## Pipeline

| Stage | Recipe | Output |
| --- | --- | --- |
| 0 | `inventory` | `data/inventory.json` (IDs, years, source URLs) |
| 1 | `convert` | `data/markdown/<id>/` (marker text, figures, captions) |
| 2 | `metadata` | `data/metadata/` (title, authors, abstract, references) |
| 3 | `embed` | `data/embeddings/<model>/` (bge-m3 by default) |
| 4 | `topics` | `data/topics/` (UMAP map, HDBSCAN topics, c-TF-IDF labels) |
| 5 | `citations` | `data/citations/` (in-corpus citation graph, PageRank) |
| 6 | `figures` | `data/figures/`, `site/data/figures/<id>.webp` |
| 7 | `site-data` | `site/data/papers.json`, `site/data/topics.json` |
| AI | `summarize` | `data/llm/<model>/<id>.json` (summary, keywords, figure pick, checks) |
| AI | `topic-names` | `data/topics/names.json` (readable topic names) |

`data/` is git-ignored and stays local; only `site/` is published.

## Publishing

CI cannot run the pipeline (no PDFs in the repo), so `site/data/` is committed.
After a rebuild, commit `site/` and push to `main`. The GitHub Action in
`.github/workflows/pages.yml` checks that `site/` holds no PDFs or markdown and
fits the Pages size limits, then deploys it.

One-time setup: under Settings → Pages, set the source to **GitHub Actions**.
Pages on a private repository needs a paid GitHub plan; otherwise make the
repository public.

## Development

`just check` runs pytest and ruff. Design notes, corpus quirks and decisions
are in [AGENTS.md](AGENTS.md). Issues are tracked with kata (`kata list`).
