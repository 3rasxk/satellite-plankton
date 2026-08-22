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
index value alone (see `b2_b3_ratio` below for the one partial exception,
itself explicitly secondary/lower-confidence).

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

    B5 (705 nm, red-edge) responds to chlorophyll fluorescence/absorption;
    B4 (665 nm, red) is the reference. Standard published formulation
    (Mishra & Mishra 2012) for turbid/coastal chlorophyll retrieval.

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

    A simpler ratio than NDCI (no normalization), more sensitive to
    absolute reflectance scale but computationally trivial and widely
    used as a baseline comparison in ocean-colour literature.

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
    §2 rationale for why this is likely the best-performing index near
    river mouths (Tha Chin, Chao Phraya, Mae Klong, Bang Pakong), which is
    precisely where several of the 14 validation events are located.

    Raises:
        Returns math.inf if B4 == 0 or B5 == 0 (degenerate reading),
        same reasoning as `two_bda`.
    """
    b4, b5, b6 = bands["B4"], bands["B5"], bands["B6"]
    if b4 == 0 or b5 == 0:
        return math.inf
    return (1.0 / b4 - 1.0 / b5) * b6


def b2_b3_ratio(bands: dict) -> float:
    """B2/B3 ratio -- green *Noctiluca* discrimination. SECONDARY,
    LOWER-CONFIDENCE signal (per `.claude/agents/bloom-detection.md` §1
    and `docs/DETECTION_PLAN.md` §2) -- do not treat this as equally
    established as NDCI.

    Green *Noctiluca scintillans* carries a photosynthetic endosymbiont
    that shows elevated reflectance across ~440-550 nm (roughly Sentinel-2
    B2/blue through B3/green) relative to diatom blooms or non-bloom
    water. This ratio is a coarse proxy for that elevation, not a
    validated species classifier.

    Species scope (per `data/validation/CALIBRATION_NOTES.md` §2): this
    feature is *Noctiluca*-specific. It is not expected to behave
    consistently, or fire at all, for the other 7 taxa in the validation
    set (Ceratium furca, Karenia sp., Leptocylindrus sp. [a diatom],
    Trichodesmium erythraeum [a cyanobacterium], Protogonyaulax sp.,
    unknown, or the mixed Noctiluca miliaris/Ceratium furca event).
    Callers must not report a miss on a non-Noctiluca event as if it
    reflects on this feature's validity.

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
