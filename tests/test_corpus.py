from pathlib import Path

import pytest

from sca import corpus, paths


@pytest.mark.parametrize(
    ("name", "id_", "year", "number", "series"),
    [
        ("SCA1987-01.pdf", "SCA1987-01", 1987, 1, "main"),
        ("1-SCA1991-01.pdf", "SCA1991-01", 1991, 1, "main"),
        ("1-SCA1991-03EURO.pdf", "SCA1991-03EURO", 1991, 3, "euro"),
        ("SCA1990-05EURO.pdf", "SCA1990-05EURO", 1990, 5, "euro"),
        ("SCA2007_12.pdf", "SCA2007_12", 2007, 12, "main"),
        ("SCA2014-051.pdf", "SCA2014-051", 2014, 51, "main"),
        ("SCA2024_1010.pdf", "SCA2024_1010", 2024, 1010, "main"),
        ("SCA_2025_1011.pdf", "SCA_2025_1011", 2025, 1011, "main"),
    ],
)
def test_parse_name(name, id_, year, number, series):
    p = corpus.parse_name(paths.PAPERS_DIR / str(year) / name)
    assert (p.id, p.year, p.number, p.series) == (id_, year, number, series)
    assert p.url == f"{paths.PDF_BASE_URL}{year}/{name}"


@pytest.mark.parametrize("name", ["notes.pdf", "SCA2014-051.txt", "SCA14-05.pdf"])
def test_parse_name_rejects_unknown(name):
    with pytest.raises(ValueError):
        corpus.parse_name(Path(name))


def test_iter_papers_rejects_duplicate_ids(tmp_path):
    (tmp_path / "1991").mkdir()
    (tmp_path / "1991" / "SCA1991-01.pdf").touch()
    (tmp_path / "1991" / "1-SCA1991-01.pdf").touch()
    with pytest.raises(ValueError, match="duplicate"):
        list(corpus.iter_papers(tmp_path))
