import json
from types import SimpleNamespace

import pytest

from sca import metadata, summarize

MD = """# A Title

Intro text.

## References

1. Smith, J., 2001, Some paper.
2. Doe, A., 2003, Another paper.

## Appendix A

Appendix text.
"""


def test_without_references_keeps_text_after_the_list():
    out = metadata.without_references(MD)
    assert "Smith" not in out and "Doe" not in out and "## References" not in out
    assert "Intro text." in out and "## Appendix A" in out and "Appendix text." in out


def test_without_references_leaves_text_without_a_list_alone():
    assert metadata.without_references("# T\n\nNo refs here.\n") == "# T\n\nNo refs here.\n"


def test_prepare_text_drops_images_and_spans_and_truncates(monkeypatch):
    md = 'Text <span id="p1"></span>here.\n\n![](_page_1_Figure_1.jpeg)\n\nMore.'
    text, truncated = summarize.prepare_text(md)
    assert text == "Text here.\n\nMore." and not truncated
    monkeypatch.setattr(summarize, "MAX_INPUT_CHARS", 5)
    text, truncated = summarize.prepare_text(md)
    assert truncated and text.startswith("Text ")


@pytest.mark.parametrize("n", [0, 1, 25, 26, 27, 51, 52, 701, 702])
def test_labels_round_trip(n):
    assert summarize.index_of(summarize.label(n)) == n


def test_label_values():
    assert [summarize.label(n) for n in (0, 25, 26, 27)] == ["A", "Z", "AA", "AB"]
    assert summarize.index_of("[b]") == 1
    assert summarize.index_of("3") is None


def _message(result: dict, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=json.dumps(result))],
    )


def test_parse_response_maps_labels_to_files_and_drops_bad_ones():
    candidates = [{"file": "a.jpeg", "caption": "Fig. 1"}, {"file": "b.jpeg", "caption": "Fig. 2"}]
    result = {
        "figures": [
            {"label": "B", "reason": "main result"},
            {"label": "Q", "reason": "not listed"},
        ]
    }
    out = summarize.parse_response(_message(result), candidates)
    assert out["figures"] == [
        {"label": "B", "reason": "main result", "file": "b.jpeg", "caption": "Fig. 2"}
    ]


def test_parse_response_raises_on_refusal_and_truncation():
    for reason in ("refusal", "max_tokens"):
        with pytest.raises(RuntimeError):
            summarize.parse_response(_message({"figures": []}, reason), [])


FRONT = """# **Derivation of A Representative Elementary Volume (REV) for Upscaled Two-Phase
Flow in Porous Media.**

*James E.* McClure1,\\* , *Ming* Fan1,2 , *Steffen* Berg<sup>3</sup>

## Abstract

We study the effect of wettability on electrical resistivity and membrane potential of
terrigenous rocks from West Siberia using contact angles and Amott indices in core plugs.
"""


def test_verify_title_accepts_printed_title_split_over_lines():
    title = "Derivation of a Representative Elementary Volume (REV) for Upscaled Two-Phase Flow"
    assert summarize.verify_title(title + " in Porous Media", FRONT)


def test_verify_title_rejects_title_composed_from_abstract():
    made_up = "Effect of Wettability on Electrical Resistivity and Membrane Potential"
    assert summarize.verify_title(made_up, FRONT) is False
    assert summarize.verify_title(None, FRONT) is None


def test_verify_authors_by_surname():
    names = ["James E. McClure", "Ming Fan", "Steffen Berg, Jr.", "Qingjie Lu"]
    assert summarize.verify_authors(names, FRONT) == [True, True, True, False]


def test_verify_abstract_needs_copied_text():
    copied = "the effect of wettability on electrical resistivity and membrane potential of"
    assert summarize.verify_abstract(copied + " terrigenous rocks from West Siberia", FRONT)
    reworded = "Resistivity and membrane potential change as rocks become more oil-wet in Siberia."
    assert summarize.verify_abstract(reworded, FRONT) is False


def test_verify_title_accepts_title_fused_with_following_text():
    md = "# **RESERVOIR WATER SATURATION MEASURED ON CORES J.K. Ringen, Statoil** formation\n"
    assert summarize.verify_title("Reservoir Water Saturation Measured on Cores", md)
