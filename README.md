# SCA Papers Explorer

An interactive explorer for the Society of Core Analysts (SCA) symposium papers
(1987–2026, ~2,000 papers) mirrored at <https://www.jgmaas.com/SCA/>: a list
and a topic map of the papers, sized by in-corpus citations, with search,
year and topic filters, similar papers, citation links, a key figure and a link
to the original PDF.

Site (once GitHub Pages is enabled for the repo):
<https://mralbu.github.io/sca-papers/>

## What is published

Only derived data: title, authors, year, abstract, topic, map coordinates,
citation scores and links, similar papers, and one small figure thumbnail per
paper. PDFs, full text and reference lists stay local; the site links to the
original PDF on jgmaas.com. The papers belong to SCA.

## Requirements

- [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
- `wget` (download) and `pdftotext` from poppler (`just dedup`)
- A GPU for the PDF conversion (marker); embeddings also run on Apple MPS or CPU

## Usage

```sh
just setup            # Python environment
just download         # mirror the PDFs into papers/ (re-run to update)
just dedup            # drop 1991/1992 preview PDFs (recorded in duplicates.txt)
just convert          # PDF -> markdown with marker (slow; resumable)
just build            # metadata, embeddings, topics, citations, figures, site data
just serve            # preview the site at http://localhost:8000
```

Every stage is cached and resumable, so a re-run only processes new or changed
papers. Run `just` for the full list of recipes and their arguments.

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

Topic names and merges can be overridden by hand in `topics.yaml`; topic ids
change when the inputs change, so re-check it after a rebuild.

## Publishing

CI cannot run the pipeline (no PDFs in the repo), so `site/data/` is committed.
After `just build`, commit `site/` and push to `main`; the GitHub Action in
`.github/workflows/pages.yml` deploys `site/` to GitHub Pages after checking
that it holds no PDFs or markdown and fits the Pages size limits.

## Development

`just check` runs pytest and ruff. Design notes, corpus quirks and decisions
are in [AGENTS.md](AGENTS.md).
