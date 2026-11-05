import numpy as np

from sca import topics


def test_ctfidf_picks_distinctive_terms():
    docs = [
        "nmr relaxation T2 distribution nmr logging",
        "nmr relaxation surface relaxivity",
        "centrifuge capillary pressure drainage centrifuge",
        "centrifuge capillary pressure imbibition",
    ]
    kw = topics.ctfidf_keywords(docs, np.array([0, 0, 1, 1]), n=3)
    assert kw[0][0].startswith("nmr")
    assert kw[1][0].startswith("centrifuge") or kw[1][0].startswith("capillary")
    # a unigram already inside a picked bigram is not repeated
    assert not any(a != b and a in b for a in kw[1] for b in kw[1])


def test_merges_fold_into_first_id():
    labels = topics.apply_merges(np.array([0, 1, 2, 3, 1]), [[1, 3], [2, 0]])
    assert labels.tolist() == [2, 1, 2, 1, 1]


def test_outliers_are_reassigned_to_nearest_cluster():
    rng = np.random.default_rng(0)
    a = rng.normal(0, 0.05, (30, 2))
    b = rng.normal(5, 0.05, (30, 2))
    points = np.vstack([a, b, [[3.2, 3.2]]])
    labels, outlier = topics.cluster(points)
    assert (labels >= 0).all()  # outliers are reassigned, never left at -1
    assert labels[-1] == labels[30]  # the stray point goes with the cluster near (5, 5)
    assert labels[0] != labels[30]


def test_overrides(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text("merge:\n  - [3, 7]\nrename:\n  3: NMR\n")
    assert topics.load_overrides(f) == {"merge": [[3, 7]], "rename": {3: "NMR"}}
    assert topics.load_overrides(tmp_path / "missing.yaml") == {}
