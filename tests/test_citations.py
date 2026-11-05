import pytest

from sca import citations


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("Lenormand, R., Society of Core Analysts, SCA1993-22 (1993)", (1993, 22)),
        ("Dernaika, M., SCA 2014-059 (2014)", (2014, 59)),
        ("Forbes, P.L., ... SCA 9107 presented at the SCA conference", (1991, 7)),
        ("Hawkins, J., 1989, ..., paper SCA paper 8909.", (1989, 9)),
        ("Cuiec, L., 1995 SCA Conference, paper 9529, San Francisco", (1995, 29)),
        ("Mateo, J., SCA-08 presented at the SCA 2004 conference", (2004, 8)),
        ("Bekri, S., SCA 35, 2005 (2005)", (2005, 35)),
        ("presented at the SCA 2004 conference, Abu Dhabi", None),  # a year, not an ID
        ("Smith, SCAL guidelines 2004-12", None),
        ("Jones, SPE 9529 (1980)", None),  # "paper NNNN" only counts with an SCA mention
    ],
)
def test_explicit_id(ref, expected):
    assert citations.explicit_id(ref) == expected


def record(id, year, number, title, authors, refs=(), series="main"):
    return {
        "id": id,
        "year": year,
        "number": number,
        "series": series,
        "status": "ok",
        "title": title,
        "authors": list(authors),
        "references": list(refs),
    }


@pytest.fixture
def matcher():
    return citations.Matcher(
        [
            record("SCA1994-04", 1994, 4, "CORE ANALYSIS BY LOW FIELD NMR", ["C. Straley"]),
            record("SCA1994-06", 1994, 6, "Heterogeneous systems imaging", ["G. Maddinelli"]),
            record("SCA1992-05EURO", 1992, 5, "Diaphragm method", ["W. Hammervold"], series="euro"),
            record("SCA1992-05", 1992, 5, "Something else", ["A. Other"]),
        ]
    )


def test_title_beats_mistyped_id(matcher):
    ref = 'Straley, C., Rossini, D. (1994) "Core analysis by low field NMR", paper SCA 9406.'
    target, method = matcher.match(ref)
    assert (target.id, method) == ("SCA1994-04", "title_over_id")


def test_quoted_title_contradicting_id_is_dropped(matcher):
    ref = 'Doe, J. (1994) "A completely different paper about centrifuges", SCA 9406.'
    assert matcher.match(ref) is None


def test_euro_series(matcher):
    target, _ = matcher.match("Hammervold, W.L., SCA 1992-05 Euro.")
    assert target.id == "SCA1992-05EURO"


def test_title_needs_year_and_author(matcher):
    assert matcher.match("Straley, C.: Core analysis by low field NMR. Log Analyst.") is None


def test_pagerank_mean_is_one_and_ranks_cited_higher():
    ids = ["a", "b", "c", "d"]
    pr = citations.pagerank(ids, [("a", "c"), ("b", "c"), ("d", "c"), ("c", "b")])
    assert sum(pr.values()) / len(pr) == pytest.approx(1)
    assert pr["c"] > pr["b"] > pr["a"]
