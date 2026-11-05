"""Filesystem layout shared by all pipeline stages.

Two trees with different publishing rules:

- ``papers/`` and ``data/`` are git-ignored and never published: the downloaded
  PDFs, marker's full-text markdown, and every intermediate a stage caches.
- ``site/`` is the static site deployed to GitHub Pages. Only summaries and
  derived data may be written there (metadata, coordinates, scores, small
  figure thumbnails), never full text or PDFs.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAPERS_DIR = ROOT / "papers"  # downloaded PDFs: papers/<year>/<file>.pdf

DATA_DIR = ROOT / "data"  # local-only stage outputs
INVENTORY = DATA_DIR / "inventory.json"
MARKDOWN_DIR = DATA_DIR / "markdown"  # marker output: data/markdown/<paper id>/
METADATA_DIR = DATA_DIR / "metadata"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"
TOPICS_DIR = DATA_DIR / "topics"
CITATIONS_DIR = DATA_DIR / "citations"
FIGURES_DIR = DATA_DIR / "figures"

SITE_DIR = ROOT / "site"  # published static site
SITE_DATA_DIR = SITE_DIR / "data"  # generated: papers.json, figures/, ...
SITE_FIGURES_DIR = SITE_DATA_DIR / "figures"  # one small WebP thumbnail per paper

PDF_BASE_URL = "https://www.jgmaas.com/SCA/"
