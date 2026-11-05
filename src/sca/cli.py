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
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
