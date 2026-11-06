"""Entry point: ``uv run sca <stage>``. Each stage is also a just recipe."""

import argparse
import json
import sys
from collections import Counter

from sca import cache, corpus, paths


def inventory(args: argparse.Namespace) -> None:
    """List every paper with its ID, year, series and source URL."""
    papers = list(corpus.iter_papers())
    records = [
        {
            "id": p.id,
            "year": p.year,
            "number": p.number,
            "series": p.series,
            "pdf": p.rel_path,
            "url": p.url,
        }
        for p in papers
    ]
    cache.write_json_atomic(paths.INVENTORY, records)
    by_year = Counter(p.year for p in papers)
    years = ", ".join(f"{y}: {n}" for y, n in sorted(by_year.items()))
    print(
        f"{len(papers)} papers in {len(by_year)} years -> {paths.INVENTORY.relative_to(paths.ROOT)}"
    )
    print(years)


def convert(args: argparse.Namespace) -> None:
    """Convert PDFs to markdown with marker (resumable)."""
    from sca import convert as stage  # heavy imports only when needed

    failed = stage.run(ids=args.ids, workers=args.workers, limit=args.limit)
    sys.exit(1 if failed else 0)


def metadata(args: argparse.Namespace) -> None:
    """Extract title, authors, abstract and references from the markdown."""
    from sca import metadata as stage

    records = stage.run(ids=args.ids, force=args.force)
    if args.ids:
        for r in records:
            print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    print(f"{len(records)} papers -> {stage.COMBINED.relative_to(paths.ROOT)}")
    print(stage.REPORT.read_text(encoding="utf-8"), end="")


def embed(args: argparse.Namespace) -> None:
    """Embed title + abstract + introduction start with a local model (resumable)."""
    from sca import embed as stage

    if args.compare:
        print(stage.evaluate(args.models or list(stage.MODELS)), end="")
        return
    for name in args.models or [stage.DEFAULT_MODEL]:
        done, total = stage.run(name)
        print(f"{name}: embedded {done} new/changed of {total} -> {stage.model_dir(name)}")


def topics(args: argparse.Namespace) -> None:
    """UMAP map, HDBSCAN topics and c-TF-IDF labels (overrides in topics.yaml)."""
    from sca import embed as embed_stage
    from sca import topics as stage

    data = stage.run(model=args.model or embed_stage.DEFAULT_MODEL, force=args.force)
    print(stage.table(data), end="")


def citations(args: argparse.Namespace) -> None:
    """Match references to corpus papers; citation counts and PageRank."""
    from sca import citations as stage

    stage.run(force=args.force)
    print(stage.REPORT.read_text(encoding="utf-8"), end="")


def figures(args: argparse.Namespace) -> None:
    """Index marker's figures and captions; one WebP thumbnail per paper."""
    from sca import figures as stage

    print(stage.summary(stage.run(force=args.force)), end="")


def summarize(args: argparse.Namespace) -> None:
    """LLM summaries, structured metadata and figure picks (Claude API)."""
    from sca import metadata as metadata_stage
    from sca import summarize as stage

    records = json.loads(metadata_stage.COMBINED.read_text(encoding="utf-8"))
    if args.all:
        ids = [r["id"] for r in records if r["status"] == "ok"]
    else:
        ids = args.ids or stage.choose_sample(records)
    if args.batch:
        for alias in args.models or ["sonnet"]:
            done = stage.run_batch(ids, alias, force=args.force)
            print(stage.usage_table(done, len(records)), end="")
        return
    aliases = args.models or list(stage.MODELS)
    done = stage.run(ids, aliases, force=args.force, workers=args.workers)
    print(f"{len(done)} of {len(ids) * len(aliases)} done")
    print(stage.usage_table(done, len(records)), end="")
    if not args.all:
        page = stage.compare(ids, aliases)
        print(f"comparison -> {page.relative_to(paths.ROOT)}")


def site(args: argparse.Namespace) -> None:
    """Export the published site data (site/data/papers.json, topics.json)."""
    from sca import site as stage

    print(stage.run(), end="")


def main() -> None:
    parser = argparse.ArgumentParser(prog="sca", description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    stages.add_parser("inventory", help=inventory.__doc__).set_defaults(func=inventory)
    p = stages.add_parser("convert", help=convert.__doc__)
    p.add_argument("ids", nargs="*", help="only these paper IDs (default: all)")
    p.add_argument("--workers", type=int, help="marker worker processes (default: auto)")
    p.add_argument("--limit", type=int, help="convert at most this many papers")
    p.set_defaults(func=convert)
    p = stages.add_parser("metadata", help=metadata.__doc__)
    p.add_argument("ids", nargs="*", help="only these paper IDs; prints the records")
    p.add_argument("--force", action="store_true", help="ignore cached per-paper outputs")
    p.set_defaults(func=metadata)
    p = stages.add_parser("embed", help=embed.__doc__)
    p.add_argument("models", nargs="*", help="bge-m3, specter2 (default: bge-m3)")
    p.add_argument("--compare", action="store_true", help="score already-embedded models")
    p.set_defaults(func=embed)
    p = stages.add_parser("topics", help=topics.__doc__)
    p.add_argument("--model", help="embedding model to use (default: bge-m3)")
    p.add_argument("--force", action="store_true", help="recompute even if fresh")
    p.set_defaults(func=topics)
    p = stages.add_parser("citations", help=citations.__doc__)
    p.add_argument("--force", action="store_true", help="recompute even if fresh")
    p.set_defaults(func=citations)
    p = stages.add_parser("figures", help=figures.__doc__)
    p.add_argument("--force", action="store_true", help="redo every paper")
    p.set_defaults(func=figures)
    p = stages.add_parser("summarize", help=summarize.__doc__)
    p.add_argument("ids", nargs="*", help="paper IDs (default: the fixed sample in data/llm/)")
    p.add_argument("--all", action="store_true", help="every paper with markdown")
    p.add_argument(
        "--batch", action="store_true", help="use the Batch API (half price; waits for results)"
    )
    p.add_argument(
        "--models",
        nargs="+",
        choices=["haiku", "sonnet"],
        help="default: both (with --batch: sonnet)",
    )
    p.add_argument("--workers", type=int, default=4, help="concurrent API requests")
    p.add_argument("--force", action="store_true", help="ignore cached outputs")
    p.set_defaults(func=summarize)
    stages.add_parser("site", help=site.__doc__).set_defaults(func=site)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
