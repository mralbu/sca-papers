"""The corpus: which PDFs exist and how their file names map to paper IDs.

File names vary by year (``SCA1987-01.pdf``, ``1-SCA1991-01.pdf``,
``SCA1990-05EURO.pdf``, ``SCA2014-051.pdf``, ``SCA2024_1010.pdf``,
``SCA_2025_1011.pdf``). The paper ID is the file stem without the ``1-`` prefix
that 1991/1992 full scans carry, so it matches how other papers cite it
(e.g. ``SCA2014-051``). ``...EURO`` papers are a separate series (European
symposium), not duplicates of the same-numbered paper.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sca import paths

_NAME_RE = re.compile(
    r"^(?:1-)?(?P<id>SCA_?(?P<year>\d{4})[-_](?P<number>\d+)(?P<euro>EURO)?)\.pdf$"
)


@dataclass(frozen=True)
class Paper:
    id: str  # e.g. "SCA2014-051", "SCA1991-03EURO"
    year: int
    number: int
    series: str  # "main" or "euro"
    pdf: Path  # local path

    @property
    def rel_path(self) -> str:
        """Path relative to papers/, e.g. ``2014/SCA2014-051.pdf``."""
        return self.pdf.relative_to(paths.PAPERS_DIR).as_posix()

    @property
    def url(self) -> str:
        """Link to the original PDF on jgmaas.com (PDFs are never rehosted)."""
        return paths.PDF_BASE_URL + self.rel_path


def parse_name(pdf: Path) -> Paper:
    """Parse a PDF path into a Paper. Raises ValueError for unknown names."""
    m = _NAME_RE.match(pdf.name)
    if not m:
        raise ValueError(f"unrecognised paper file name: {pdf.name}")
    return Paper(
        id=m["id"],
        year=int(m["year"]),
        number=int(m["number"]),
        series="euro" if m["euro"] else "main",
        pdf=pdf,
    )


def iter_papers(papers_dir: Path | None = None) -> Iterator[Paper]:
    """Yield every paper in ``papers/<year>/``, sorted by year, series, number."""
    papers_dir = papers_dir or paths.PAPERS_DIR
    found = [parse_name(p) for p in papers_dir.glob("*/*.pdf")]
    ids: dict[str, Paper] = {}
    for paper in found:
        if paper.id in ids:
            raise ValueError(f"duplicate paper id {paper.id}: {ids[paper.id].pdf} and {paper.pdf}")
        if paper.pdf.parent.name != str(paper.year):
            raise ValueError(f"{paper.pdf} is not in its year's folder")
        ids[paper.id] = paper
    yield from sorted(found, key=lambda p: (p.year, p.series, p.number))
