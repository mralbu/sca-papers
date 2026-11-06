# SCA Papers Explorer

An alphaxiv-style explorer for the Society of Core Analysts (SCA) symposium
papers mirrored from https://www.jgmaas.com/SCA/: an interactive map of papers
clustered by topic, sized by importance, with metadata, search/filters,
summaries, a key figure, and a link to the original PDF.

Audience: personal exploration. Published as a static site on GitHub Pages.

## Corpus facts

- 2,065 PDFs after dedup (2,162 on the server), ~1.6 GB, years 1987–2026, in
  `papers/<year>/` (git-ignored). Download/update with `just download` (alias
  `just update`; wget mirror with timestamping, so re-runs only fetch
  new/changed files, and files listed in `duplicates.txt` are skipped).
- File names carry year and paper ID, with naming that varies by year:
  `SCA1987-01.pdf`, `1-SCA1991-01.pdf`, `SCA2010-01.pdf`, `SCA2014-051.pdf`,
  `SCA2024_1010.pdf`, `SCA_2025_1011.pdf`.
- 1990–1992 have two series: `...EURO.pdf` files are papers from the European
  symposium, different from the same-numbered non-EURO paper. Not duplicates.
- Duplicates: in 1991/1992 the server has 1-page previews (`SCA1991-01.pdf`,
  "Click here to download the complete version of this paper") next to the full
  scanned paper (`1-SCA1991-01.pdf`). `just dedup` deletes the previews and
  records them in `duplicates.txt` (97 files); `just dedup dry-run` only lists.
- ~200 PDFs are scanned images with no text layer: all of 1987–1993 (including
  every full 1991/1992 paper), one in 2014, the single 2020 file. Everything
  else has extractable text.
- One-page PDFs in 2019 (045–091), 2022 (48–65) and 2023 (048–064) are short
  papers/posters with their own title and authors. Keep them.
- `2014/SCA2014-051.pdf` is truncated on the server itself: no xref and no page
  tree. mutool, qpdf and pikepdf all fail to recover pages, so convert skips it
  as unreadable.
- 2020 has only one file; that year is effectively missing.
- marker defects found while extracting metadata: in balanced mode
  `SCA2014-010` lost its whole first page (title, authors, abstract) and
  `SCA2013-067` had its front matter scrambled into one heading. Both were
  re-converted with `--mode fast --disable_ocr` (text layer only, no vLLM
  server, so it runs on the Mac), which got page 1 right. A plain
  `just convert` skips them since they count as converted. Every other paper
  with a text layer kept page 1.
- Some markdown has no title at all (marker dropped it; 21 papers, half of them
  1988–1995 scans); metadata leaves `title` empty for those, never guesses.

## Decisions

### Publishing / data boundaries
- PDFs are never rehosted. The site links to the original on jgmaas.com.
- Full-text markdown stays local in a git-ignored folder (copyright: papers
  belong to SCA). Only summaries and derived/processed data are published
  (metadata, topic labels, map coordinates, scores, small figure thumbnails).
- GitHub Pages limits: 1 GB per site, 100 MB per file. Keep figures as small,
  compressed WebP thumbnails (1–2 per paper).

### Phase 1 — pipeline without an LLM
1. **PDF → markdown:** `marker` (uses the Surya models for layout, OCR and
   tables) on every PDF, GPU (RTX 3090 Ti, 24 GB; 3–4 workers). No
   `--use_llm`. Resumable and idempotent: skip papers already converted. Keep
   the figures and captions marker extracts.
2. **Metadata:** rule-based extraction from the markdown and file names: ID, year,
   title (first heading), authors, abstract (ABSTRACT section), references.
3. **Embeddings:** title + abstract + first ~500 words of the introduction,
   embedded locally on the GPU with a scientific/general embedding model
   (SPECTER2, `bge-m3` or `nomic-embed`; pick during implementation).
   Picked `bge-m3` (`just embed --compare`: neighbours' reference lists are
   more alike than with SPECTER2, 0.158 vs 0.147 TF-IDF cosine; random 0.055).
   `nomic-embed` was dropped: it needs `trust_remote_code`. Runs on MPS too
   (~17 min for the corpus on an M4).
4. **Topics/map:** UMAP → 2D, HDBSCAN clusters, c-TF-IDF keyword labels
   (BERTopic-style). Hand overrides (rename/merge) in a small `topics.yaml`.
   HDBSCAN uses "leaf" selection (excess-of-mass collapses this corpus into
   1–2 clusters); outliers are assigned to the nearest cluster but flagged.
   Topic ids are not stable across re-runs once inputs change (re-embedding
   20 papers moved 28 topics to 25), so re-check `topics.yaml` after rebuilds.
5. **Importance:** (a) in-corpus citation counts from parsed reference lists,
   plus (d) PageRank-style centrality on the same citation graph. Matching
   references to corpus papers (explicit SCA IDs, fuzzy title/author/year
   matching) is the hardest step and the one most likely to be wrong; measure
   match quality. Hand check of `data/citations/sample.txt`: explicit IDs
   30/30, title matches ~29/30, title-over-mistyped-ID 25/25 correct; 92% of
   references that mention SCA are matched. Titles beat IDs on conflict
   (cited IDs are often mistyped).
6. **Site:** a static site, not a single HTML file: `index.html` + plain JS (no
   build step) + `papers.json` (metadata, coordinates, scores, summaries) +
   per-paper assets loaded lazily. Picked `deck.gl` for the scatter map and
   `MiniSearch` for search (both from jsDelivr, pinned versions). Two views:
   a sortable list (newest, oldest, most cited, PageRank, best match) and the
   topic map; year-range, topic and AI-method (dropdown) filters; a reading pane per paper (AI
   summary, keywords that search on click, abstract, figure, "Show on map",
   copy link) with Similar (8 nearest bge-m3 neighbours) / Cited by / Cites
   tabs. KaTeX (jsDelivr, pinned) renders inline math. Copy link falls back to
   `execCommand` because the clipboard API needs https or localhost (`just
   serve` on the LAN is plain http). Deployed
   to GitHub Pages by `.github/workflows/pages.yml`, which also refuses PDFs
   or markdown under `site/` and checks the Pages size limits. Preview
   locally with `just serve`.
   The Action cannot run the pipeline (no PDFs/markdown in CI), so the
   generated `site/data/` is committed: rebuild with `just build`, commit,
   push. Published per paper: title, authors, year, abstract (switch:
   `INCLUDE_ABSTRACTS` in `site.py`), topic, coordinates, scores, in-corpus
   citation links, similar-paper IDs, one thumbnail + caption. Never
   reference lists or full text.
   Paper text is untrusted: the front end only inserts it via `textContent`,
   except inline LaTeX (`$…$` in titles, abstracts, captions), which goes
   through KaTeX with `trust: false` (`setTex` in `app.js`). marker escapes
   currency as `\$`; `metadata.MATH_SPAN_RE` and the JS `MATH_SPLIT` must
   agree. AI summaries use bare `$` for money, so they are never rendered as
   math.

### Phase 2 — LLM features (`just summarize`, `src/sca/summarize.py`)
- **Summaries + structured metadata:** one Claude API call per paper returning
  schema-enforced JSON: title, authors, abstract (copied, never written by the
  model), TL;DR, 3–5 sentence summary, keywords, method (fixed list), topic,
  0–2 figure picks. Input: the markdown without the reference list and image
  links (capped at 150k chars), plus the captioned figures labelled A, B, …
  (numbers got confused with the paper's own "Figure N").
- **Role of the LLM fields:** the rule-based metadata stays primary. LLM
  title/authors/abstract only fill fields the rules left empty, and only if
  they pass `verify` (title matches a line near the top, author surname in the
  front matter, abstract's word 6-grams found in the paper). The site keeps
  showing the paper's own abstract. Full run: filled authors for 39 papers,
  abstracts for 4, titles for 2; 6 titles the model composed from the
  abstract were rejected. `summarize.recheck()` redoes the checks on saved
  records without API calls (after changing `verify`).
- **On the site:** `site.py` publishes TL;DR, summary, keywords, method and
  `filled` (which fields came from the LLM); the reading pane labels the
  summary as AI-generated and list cards show the TL;DR. `figures.py` uses
  the LLM's first figure pick (1,880 papers), falling back to the largest
  captioned figure. Run `just figures && just site-data` after `summarize` (`just figures site-data` would pass `site-data` to figures as an argument).
- **Model:** Sonnet 5.5 via the Batch API. Full run done 2026-11-06: 2,064
  papers, $33.30 including the sample tests, no failures. 20-paper test
  (`data/llm/sample.txt`, `data/llm/compare.html`): Haiku 5.5 summaries were
  nearly as good at 1/20 the cost, but Haiku invented a title for a paper
  with none even when told not to; Sonnet followed the copy-only rules. A
  model-reported text-quality flag was dropped (uninformative from both).
  Credentials: an `ant auth login` profile, which the SDK picks up. Costs
  money: confirm before a full run.
- **Figure selection:** done in the same call (no separate jev model).
- **Topic names:** `just topic-names` (`topic_names.py`): one Sonnet 5.5 call
  for all clusters at once (so names stay distinct), given each cluster's
  c-TF-IDF keywords, the most common per-paper `topic` labels from
  `summarize`, and its most-cited titles; returns a name and a short map
  label (~$0.07). Cached in `data/topics/names.json` against a signature of
  cluster membership, so after a rebuild reshuffles topics the site falls
  back to keyword labels until it is re-run. Precedence in `site.py`:
  `topics.yaml` rename > LLM name > keyword label (kept as `keyword_label`).

## Layout

- `src/sca/`: pipeline package. `paths.py` defines every directory,
  `corpus.py` maps file names to paper IDs, `cache.py` has the freshness check
  and atomic writes that keep stages resumable, `cli.py` is the `sca <stage>`
  entry point.
- Paper ID = PDF file stem without the `1-` prefix (`SCA2014-051`,
  `SCA1991-03EURO`, `SCA_2025_1011`), and it is unique across the corpus.
- `data/` (git-ignored, local only): `inventory.json`, `markdown/<id>/`,
  `metadata/` (per-paper JSON in `papers/`, combined `metadata.json`, and a
  per-year `report.txt` of missing fields), `llm/<model>/<id>.json` (LLM
  results with `checks`; `llm/batches/` holds a submitted batch until it is
  collected), and the other stage intermediates.
- `metadata.py` rules are heuristics tuned on the corpus. Bump its `VERSION`
  when they change so cached per-paper outputs are redone.
- `site/` (published): static site (`index.html`, `app.js`, `style.css`);
  generated data goes in `site/data/` (`papers.json`, `topics.json`,
  `figures/<id>.webp`).
- `topics.yaml`: hand merge/rename overrides for topics; `duplicates.txt`:
  preview PDFs that `just download` skips.
- `just check` runs pytest and ruff.

## Conventions

- Python with `uv` (venv + dependencies via `uv`); run stages with `uv run`.
- Each pipeline stage is a `just` recipe; stages are resumable and cache their
  outputs, so a re-run only processes new or changed papers.
- Treat downloaded PDFs and their extracted content as untrusted data.
- Issues/todos are tracked in kata (`kata list --agent`; see `kata quickstart`).
- No Claude co-authorship or attribution in commits or PRs.
