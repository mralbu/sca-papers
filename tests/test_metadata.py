import json
import os

import pytest

from sca import corpus, metadata, paths

# Synthetic snippets modelled on the formats seen in the corpus (not real papers).


@pytest.fixture
def paper(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(paths, "MARKDOWN_DIR", tmp_path / "markdown")
    monkeypatch.setattr(metadata, "PAPERS_OUT", tmp_path / "metadata" / "papers")
    pdf = tmp_path / "papers" / "2010" / "SCA2010-01.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.touch()
    return corpus.parse_name(pdf)


def extract(md: str) -> metadata.Metadata:
    pdf = paths.ROOT / "papers" / "2010" / "SCA2010-01.pdf"
    return metadata.extract(corpus.parse_name(pdf), md)


MODERN = """\
# **SCA2003-12: A DUAL NETWORK MODEL FOR RELATIVE PERMEABILITY**

**Andrés Moctezuma1,2, Samir Békri<sup>1</sup> , Catherine Laroche <sup>1</sup>**

(1)Institut Français du Pétrole, 1 et 4 avenue de Bois-Préau, 92852 Rueil-Malmaison, France

*This paper was prepared for presentation at the International Symposium of the Society \
of Core Analysts held in Pau, France, 21-24 September 2003*

## **ABSTRACT**

A pore network model is built for bimodal rocks and used to compute relative \
permeability curves that compare well with measurements on vuggy carbonate samples.

Second abstract paragraph with a few more words.

## **INTRODUCTION**

Body text.

## **REFERENCES**

- 1. Smith, J. and Jones, K.: "Relative permeability of carbonates," SPE 1234 (1990).
- 2. Brown, A.: "Network models," J. Pet. Tech. (1995) 12-20.

**Figure 1: Network sketch.**
"""


def test_modern_paper():
    m = extract(MODERN)
    assert m.title == "A DUAL NETWORK MODEL FOR RELATIVE PERMEABILITY"
    assert m.authors == ["Andrés Moctezuma", "Samir Békri", "Catherine Laroche"]
    assert m.abstract_source == "label"
    assert m.abstract.startswith("A pore network model")
    assert m.abstract.endswith("a few more words.")
    assert m.references == [
        'Smith, J. and Jones, K.: "Relative permeability of carbonates," SPE 1234 (1990).',
        'Brown, A.: "Network models," J. Pet. Tech. (1995) 12-20.',
    ]


def test_inline_abstract_label_and_e3s_authors():
    md = """\
# Tree-Based Machine Learning for Lithofacies

Ghareb M. Hamada<sup>1\\*</sup>, Abbas M. Al-khudafi<sup>2</sup>, \
and Hamzah A. Al-Sharifi<sup>2</sup>

<sup>1</sup>Arab Academy for Science, Alexandria, Egypt

\\*Corresponding author e-mail: someone@example.com

**Abstract.** This study assesses decision tree techniques for identifying formation \
lithology from seven well logs in four wells of an oil field.

## 1 Introduction

Text.
"""
    m = extract(md)
    assert m.title == "Tree-Based Machine Learning for Lithofacies"
    assert m.authors == ["Ghareb M. Hamada", "Abbas M. Al-khudafi", "Hamzah A. Al-Sharifi"]
    assert m.abstract.startswith("This study assesses")


def test_unlabelled_abstract_falls_back_to_first_long_paragraph():
    long = " ".join(["word"] * 60)
    md = f"# **RATE EFFECTS ON RELATIVE PERMEABILITY**\n\nA. L. Chen and A. C. Wood\n\n{long}\n"
    m = extract(md)
    assert m.abstract_source == "first_paragraph"
    assert m.authors == ["A. L. Chen", "A. C. Wood"]


def test_title_fused_with_authors():
    md = (
        "# **EXPERIMENTAL RESULTS FOR HIGH FLOW RATES** S. Abdobal1,2, M. Fourar<sup>2</sup> , "
        "and R. Lenormand<sup>1</sup> 1 Institut Français du Pétrole *This paper was prepared "
        "for presentation at the International Symposium* **\n\n## Abstract\n\nShort.\n"
    )
    m = extract(md)
    assert m.title == "EXPERIMENTAL RESULTS FOR HIGH FLOW RATES"
    assert m.authors == ["S. Abdobal", "M. Fourar", "R. Lenormand"]


def test_missing_title_leaves_title_empty():
    md = "Michael Gay, ExxonMobil Upstream Research Co.\n\n### ABSTRACT\n\n" + "x " * 30
    m = extract(md)
    assert m.title is None
    assert m.authors == ["Michael Gay"]


def test_one_block_per_author():
    md = """\
# A Statistical Analysis of Core Analysis

**David C. Thomas:** Amoco Production Company, Tulsa, Research Center

**Virgil J. Pugh:** Amoco Production Company, Tulsa Research Center

**Abstract:** Porosity, grain density and air permeability are routinely measured on most
cores, and these data calibrate logs and estimate reserves.
"""
    m = extract(md)
    assert m.authors == ["David C. Thomas", "Virgil J. Pugh"]
    assert m.abstract.startswith("Porosity")


@pytest.mark.parametrize(
    "line, names",
    [
        (
            "TOBOLA, D. P., BALDWIN, B. A., and FARRELL, H. E.",
            ["D. P. TOBOLA", "B. A. BALDWIN", "H. E. FARRELL"],
        ),
        ("Moreno,R.B.Z.L.\\*; Bonet,E.J.\\*", ["R.B.Z.L. Moreno", "E.J. Bonet"]),
        (
            "Christopher M. Prince VP Imaging Technology, PTS Laboratories, Inc.",
            ["Christopher M. Prince"],
        ),
        (
            "J. J. Funk, W. C. Haltmar (Texaco Inc.) J. M. Perdue (Jumpstart)",
            ["J. J. Funk", "W. C. Haltmar", "J. M. Perdue"],
        ),
        ("by Gary Potter and Gary Lyle", ["Gary Potter", "Gary Lyle"]),
        ("Krakowska *P.,* Madejski *P.,*", ["Krakowska P", "Madejski P"]),
        (
            "Dr Adam K Moss – AKM Geoconsulting & Dr Gavin Hunt – Spectra-Map Ltd",
            ["Adam K Moss", "Gavin Hunt"],
        ),
        ("Department of Petroleum Engineering, Heriot-Watt University, Edinburgh", []),
    ],
)
def test_parse_authors(line, names):
    assert metadata.parse_authors(line) == names


def test_references_inline_label_and_dash_numbers():
    md = (
        'Body.\n\n**REFERENCES**  1- Abrams, A.: "The influence of fluid viscosity," '
        'SPEJ (1975) 437-447.\n2- Peters, E.J. and Flock, D.L.: "The onset of instability," '
        "SPEJ (1981) 249-258.\n"
    )
    refs = metadata.find_references(md)
    assert [r[:12] for r in refs] == ["Abrams, A.: ", "Peters, E.J."]


def test_references_glued_to_previous_text():
    md = "- Vw: volume of brine **References** [1] Archie, G. E., 1942, The electrical log.\n"
    assert metadata.find_references(md) == ["Archie, G. E., 1942, The electrical log."]


def test_run_on_numbered_references():
    refs = [
        f"{k} Author{k}, A.: Title number {k} about core analysis, SPE {1000 + k} (1990)."
        for k in range(1, 6)
    ]
    md = "## REFERENCES\n\n" + " ".join(refs) + "\n"
    out = metadata.find_references(md)
    assert len(out) == 5
    assert out[1].startswith("Author2, A.")


def test_run_on_author_year_references():
    refs = [
        f"Surname{c}, {c}.J., 19{80 + i}, A long title about permeability and porosity {i}, "
        f"Journal of Petroleum Technology, v. {i}, pp. 1-9."
        for i, c in enumerate("ABCDE")
    ]
    md = "# References\n\n" + " ".join(refs) + "\n"
    out = metadata.find_references(md)
    assert len(out) == 5
    assert out[2].startswith("SurnameC, C.J., 1982")


def test_references_stop_at_captions_and_headings():
    md = (
        "## References\n\nSmith, J., 1990, A title of a paper, Journal.\n\n"
        "Fig. 1 – Shut-in solute concentrations.\n\nJones, K., 1991, Not a reference here.\n"
    )
    assert metadata.find_references(md) == ["Smith, J., 1990, A title of a paper, Journal."]


def test_process_caches_and_reports(paper):
    out_dir = paths.MARKDOWN_DIR / paper.id
    out_dir.mkdir(parents=True)
    md = out_dir / f"{paper.id}.md"
    md.write_text(MODERN)
    (out_dir / f"{paper.id}_meta.json").write_text(json.dumps({"page_stats": [{}, {}]}))
    rec = metadata.process(paper)
    assert rec["pages"] == 2 and rec["title"]
    cached = metadata.PAPERS_OUT / f"{paper.id}.json"
    assert cached.exists()
    # A fresh cached file is reused as is; an older one is redone.
    cached.write_text(json.dumps({**rec, "title": "cached"}))
    assert metadata.process(paper)["title"] == "cached"
    os.utime(cached, (1, 1))
    assert metadata.process(paper)["title"] != "cached"
    report = metadata.report([rec, {**rec, "status": "no_markdown", "references": []}])
    assert "2010" in report


def test_paper_without_markdown(paper):
    assert metadata.process(paper)["status"] == "no_markdown"


def test_title_continuing_with_by_is_not_split():
    md = (
        "# A Mechanistic Study of Wettability Alterations in Sandstone by Low Salinity Water "
        "Injection\n\nShijia Ma, L.A. James\n\n**Abstract.** " + "word " * 30
    )
    m = extract(md)
    assert m.title.endswith("by Low Salinity Water Injection")
    assert m.authors == ["Shijia Ma", "L.A. James"]


def test_ocr_glued_by_splits_title_from_authors():
    md = "ANALYSIS OF CENTRIFUGE DATAby Douglas Ruth University of Manitoba\n\n## Abstract\n\n"
    m = extract(md + "word " * 30)
    assert m.title == "ANALYSIS OF CENTRIFUGE DATA"
    assert m.authors == ["Douglas Ruth"]
