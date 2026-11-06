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
