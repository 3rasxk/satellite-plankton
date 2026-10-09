"""
Spectral indices for chlorophyll / bloom detection, Sentinel-2 bands.

Data source: Sentinel-2 L2A surface reflectance bands (B2, B3, B4, B5, B6)
as returned by `data-pipeline`'s `get_sentinel2_bands(lat, lng, date)` —
see `detection/src/_data_pipeline.py` for how that cross-project call is
wired up, and `data-pipeline/src/sentinel2.py` for cloud/land masking.
Resolution: 10 m (B2/B3/B4) / 20 m (B5/B6), Sentinel-2, ~5-day revisit.
Limitation: these are standard published water-colour indices, not a
fitted model — no coefficients here are learned from data (CLAUDE.md
"Non-negotiable rules": no supervised ML anywhere). They detect an
optical chlorophyll/turbidity signature at pixel resolution; they do not
resolve individual organisms and cannot distinguish bloom species from
index value alone. The exploratory `b2_b3_ratio` is not a validated
species classifier.

Scale-factor decision (per this module's callers -- documented here since
`data-pipeline/src/sentinel2.py`'s docstring flags it as a caller
decision): `get_sentinel2_bands` returns *raw* S2_SR_HARMONIZED digital
numbers (typically 0-10000+ for reflectance x10000), not yet divided by
10000. Every index below (NDCI, 2BDA, 3BDA, B2/B3) is a pure ratio of
bands, so the /10000 scale factor is present in numerator and denominator
alike and cancels exactly -- dividing or not dividing changes no computed
index value. This module is deliberate about NOT applying the /10000
scale (see `SCALE_FACTOR` and `to_reflectance` below, provided for any
future non-ratio use, e.g. displaying a single band's physical
reflectance for debugging) so indices are computed directly on raw
digital numbers. This choice is documented once, here, rather than left
implicit.
"""

from __future__ import annotations

import math

# S2_SR_HARMONIZED stores reflectance x10000 (digital number). Provided for
# any future non-ratio use; NOT applied by the ratio-based index functions
# below (see module docstring -- it would cancel out anyway).
SCALE_FACTOR = 10000.0


def to_reflectance(digital_number: float) -> float:
    """Convert a raw S2_SR_HARMONIZED digital number to physical
    reflectance (0-1 fraction). Not used by the ratio indices below
    (the scale factor cancels); provided for diagnostics/display only."""
    return digital_number / SCALE_FACTOR


def ndci(bands: dict) -> float:
    """Normalized Difference Chlorophyll Index -- primary index.

    NDCI = (B5 - B4) / (B5 + B4)

    B5 (705 nm, red-edge) and B4 (665 nm, red) form the project's
    Sentinel-2 surface-reflectance proxy. Mishra & Mishra (2012) introduced
    NDCI using water-leaving reflectance near 708 and 665 nm; that study's
    fitted values are not calibration for this different product.

    Raises:
        ZeroDivisionError-safe: returns 0.0 if B5+B4 == 0 (degenerate
        all-zero reading) rather than raising, since a caller iterating
        many dates should not crash on one bad sample -- treat as "no
        signal" rather than blow up the batch.
    """
    b4, b5 = bands["B4"], bands["B5"]
    denom = b5 + b4
    if denom == 0:
        return 0.0
    return (b5 - b4) / denom


def two_bda(bands: dict) -> float:
    """2-Band Algorithm (2BDA) -- simple alternate index.

    2BDA = B5 / B4

    This is algebraically tied to NDCI: for r=B5/B4,
    NDCI=(r-1)/(r+1). It must not be treated as an independent confirming
    signal.

    Raises:
        Returns math.inf if B4 == 0 (rather than raising ZeroDivisionError)
        -- an all-zero red band is itself a degenerate/invalid reading a
        caller should treat as unusable, so inf is a visible sentinel
        rather than a silent crash.
    """
    b4, b5 = bands["B4"], bands["B5"]
    if b4 == 0:
        return math.inf
    return b5 / b4


def three_bda(bands: dict) -> float:
    """3-Band Algorithm (3BDA) -- turbid-water variant.

    3BDA = (1/B4 - 1/B5) * B6

    Adds a third band (B6, 740 nm) to correct for backscatter dominated
    by suspended sediment rather than chlorophyll -- the DETECTION_PLAN.md
    rationale for why it may be useful near turbid river mouths (Tha Chin,
    Chao Phraya, Mae Klong, Bang Pakong).

    Raises:
        Returns math.inf if B4 == 0 or B5 == 0 (degenerate reading),
        same reasoning as `two_bda`.
    """
    b4, b5, b6 = bands["B4"], bands["B5"], bands["B6"]
    if b4 == 0 or b5 == 0:
        return math.inf
    return (1.0 / b4 - 1.0 / b5) * b6


def b2_b3_ratio(bands: dict) -> float:
    """Exploratory B2/B3 blue-to-green context ratio.

    This project has not calibrated this raw Sentinel-2 surface-reflectance
    ratio against field observations. It is not a *Noctiluca* discriminator,
    a species classifier, or an independent bloom decision.

    Raises:
        Returns math.inf if B3 == 0.
    """
    b2, b3 = bands["B2"], bands["B3"]
    if b3 == 0:
        return math.inf
    return b2 / b3


# Index registry -- config.yaml's `indices.primary`/`indices.compare`
# entries reference these names; keep in sync with any addition above.
INDEX_FUNCTIONS = {
    "ndci": ndci,
    "2bda": two_bda,
    "3bda": three_bda,
    "b2_b3_ratio": b2_b3_ratio,
}


# What each registered index is, for display (backend `GET /methods`). Static
# text only -- every value is computed by the function above, never from here.
# Formula strings are tested to evaluate to exactly what the functions return
# (tests/test_indices_metadata.py); notes restate the functions' docstrings.
#   role: "primary"     -- config.yaml `indices.primary`, the index readings use
#         "derived"     -- a transformation of another index, not independent
#         "comparison"  -- config.yaml `indices.compare`, reported beside NDCI;
#                          no decision in this repository reads it
#         "exploratory" -- config.yaml `indices.secondary_discrimination`
INDEX_ROLES = ("primary", "derived", "comparison", "exploratory")

INDEX_METADATA = {
    "ndci": {
        "name": "Normalized Difference Chlorophyll Index",
        "formula": "(B5 - B4) / (B5 + B4)",
        "bands": ("B5", "B4"),
        "role": "primary",
        "note": (
            "Primary index. B5 (705 nm, red-edge) and B4 (665 nm, red) form the "
            "project's Sentinel-2 surface-reflectance proxy. Mishra & Mishra (2012) "
            "introduced NDCI using water-leaving reflectance near 708 and 665 nm; "
            "that study's fitted values are not calibration for this different product."
        ),
    },
    "2bda": {
        "name": "2-Band Algorithm (2BDA)",
        "formula": "B5 / B4",
        "bands": ("B5", "B4"),
        "role": "derived",
        "note": (
            "Algebraically tied to NDCI: for r = B5/B4, NDCI = (r - 1)/(r + 1). "
            "It must not be treated as an independent confirming signal."
        ),
    },
    "3bda": {
        "name": "3-Band Algorithm (3BDA)",
        "formula": "(1/B4 - 1/B5) * B6",
        "bands": ("B4", "B5", "B6"),
        "role": "comparison",
        "note": (
            "Turbid-water variant: adds B6 (740 nm) to correct for backscatter "
            "dominated by suspended sediment rather than chlorophyll, which may help "
            "near turbid river mouths. Reported beside NDCI for comparison; no "
            "decision in this system reads it."
        ),
    },
    "b2_b3_ratio": {
        "name": "B2/B3 blue-to-green context ratio",
        "formula": "B2 / B3",
        "bands": ("B2", "B3"),
        "role": "exploratory",
        "note": (
            "Exploratory context ratio, not calibrated by this project against field "
            "observations. It is not a Noctiluca discriminator, not a species "
            "classifier, and not an independent bloom decision."
        ),
    },
}

# Centre wavelengths, only where this module's docstrings already state one
# (B4 665 nm, B5 705 nm, B6 740 nm). B2 and B3 are omitted on purpose: no
# centre wavelength for them is stated here, in LIMITATIONS.md or in
# docs/DETECTION_PLAN.md, and a display table must not supply one.
BAND_WAVELENGTHS_NM = {"B4": 665, "B5": 705, "B6": 740}

# Native Sentinel-2 resolution per band, as the module docstring states it.
BAND_NATIVE_RESOLUTION_M = {"B2": 10, "B3": 10, "B4": 10, "B5": 20, "B6": 20}


def compute_all_indices(bands: dict) -> dict:
    """Compute every registered index for one band reading.

    Args:
        bands: {'B2', 'B3', 'B4', 'B5', 'B6', ...} as returned by
            `get_sentinel2_bands` (extra keys like 'cloud_fraction' and
            'actual_date' are ignored).

    Returns:
        {'ndci': float, '2bda': float, '3bda': float, 'b2_b3_ratio': float}
    """
    return {name: fn(bands) for name, fn in INDEX_FUNCTIONS.items()}
