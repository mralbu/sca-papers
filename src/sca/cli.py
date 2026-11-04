"""Entry point: ``uv run sca <stage>``. Each stage is also a just recipe."""

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="sca", description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    stages.add_parser("inventory", help=inventory.__doc__).set_defaults(func=inventory)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
