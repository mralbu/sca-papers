import pytest

from sca.site import display_title


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("NMR T2 OF CO2-BRINE IN CARBONATES", "NMR T2 of CO2-Brine in Carbonates"),
        ("X-RAY CT IMAGING OF THE DRAINAGE PROCESS", "X-Ray CT Imaging of the Drainage Process"),
        ("THE EFFECT OF SALINITY AND PH", "The Effect of Salinity and pH"),
        ("SCAL FOR GAS RESERVOIRS: A CONTRIBUTION", "SCAL for Gas Reservoirs: A Contribution"),
        ("Magnetic SCAL Techniques", "Magnetic SCAL Techniques"),
    ],
)
def test_display_title(raw, shown):
    assert display_title(raw) == shown


def _record(checks=None):
    res = {"tldr": "t", "summary": "s", "keywords": ["k"], "method": "m", "figures": []}
    res |= {"title": "T", "authors": ["A. One", "B. Two"], "abstract": "Abs."}
    checks = checks or {"title": True, "authors": [True, False], "abstract": True}
    return {"result": res, "checks": checks}


def test_llm_fields_fill_only_empty_checked_fields():
    from sca.site import llm_fields

    r = {"title": "Rule title", "authors": [], "abstract": None}
    published, fills = llm_fields(r, _record())
    assert published == {"tldr": "t", "summary": "s", "keywords": ["k"], "method": "m"}
    assert fills == {"authors": ["A. One"], "abstract": "Abs."}  # title kept, B. Two failed


def test_llm_fields_skip_failed_checks_and_missing_records():
    from sca.site import llm_fields

    r = {"title": None, "authors": ["X"], "abstract": None}
    checks = {"title": False, "authors": [True, True], "abstract": False}
    assert llm_fields(r, _record(checks=checks))[1] == {}
    assert llm_fields(r, None) == ({}, {})


def test_display_title_leaves_math_alone():
    assert display_title(r"$^{13}\text{C}$ NMR OF SHALES") == r"$^{13}\text{C}$ NMR of Shales"
