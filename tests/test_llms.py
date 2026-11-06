from sca import llms


def _paper(i, topic, **kw):
    return {
        "id": f"SCA2014-{i:03d}",
        "title": f"Paper [{i}]",
        "authors": ["A. One", "B. Two"],
        "year": 2014,
        "url": f"https://www.jgmaas.com/SCA/2014/SCA2014-{i:03d}.pdf",
        "topic": topic,
        "pagerank": float(i),
        "cited_by": i,
        "cites": [],
        "method": "laboratory experiment",
        "keywords": ["NMR", "T2"],
        "tldr": "Short\nline.",
        "summary": "Longer summary.",
        **kw,
    }


TOPICS = [
    {"id": 0, "label": "NMR relaxation", "keywords": ["nmr", "t2"]},
    {"id": 1, "label": "NMR  relaxation!", "keywords": ["pore"]},  # slugs the same as 0
]


def test_topic_files_are_unique():
    assert llms.topic_files(TOPICS) == {0: "nmr-relaxation.txt", 1: "nmr-relaxation-1.txt"}


def test_groups_largest_topic_first_and_pagerank_order():
    papers = [_paper(1, 1), _paper(2, 0), _paper(3, 0)]
    groups = llms.by_topic(papers, TOPICS)
    assert [t["id"] for t, _ in groups] == [0, 1]
    assert [p["id"] for p in groups[0][1]] == ["SCA2014-003", "SCA2014-002"]


def test_full_line_has_all_authors_but_no_summary():
    line = llms.full_line(_paper(7, 0))
    assert line.startswith("- [Paper \\[7\\]](https://www.jgmaas.com/SCA/2014/SCA2014-007.pdf)")
    assert "A. One, B. Two." in line and "Method: laboratory experiment." in line
    assert "Short line." in line and "Longer summary" not in line
    assert "\n" not in line


def test_topic_page_and_index_link_each_other():
    papers = [_paper(1, 0), _paper(2, 1)]
    groups = llms.by_topic(papers, TOPICS)
    files = llms.topic_files(TOPICS)
    page = llms.topic_page(*groups[0])
    assert "Longer summary." in page and f"{llms.SITE_URL}#SCA2014-001" in page
    idx = llms.index(papers, groups, files)
    assert idx.startswith("# SCA Papers Explorer\n\n> ")
    assert f"({llms.SITE_URL}llms/nmr-relaxation-1.txt): 1 papers" in idx
