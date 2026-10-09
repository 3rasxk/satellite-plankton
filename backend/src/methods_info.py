"""Static text for ``GET /methods`` that no computing module already holds.

Data sources: ``LIMITATIONS.md`` §"Scientific references and transfer
limits" (the two references below are copied from it verbatim -- citation,
DOI and transfer-limit sentences; tests/test_methods.py checks each against
that section) and the Sentinel-2 revisit figure stated in
``detection/src/indices.py``'s module docstring. Everything else
``/methods`` serves -- formulas, roles, wavelengths, constants, thresholds,
gate states -- is read from the module that uses it at request time, not
from here (routers/methods.py).

Limitations: no reference is added beyond those LIMITATIONS.md already
verified; none is supplied from memory. The worked-example bands are
illustrative digital numbers, not an observation.
"""

from __future__ import annotations

# Fixed sample bands for each index's worked example. Raw S2_SR_HARMONIZED
# digital numbers (reflectance x 10000, the scale indices.py computes on).
# Chosen so no index has a zero denominator (B5 + B4 = 1300, B4 = 600,
# B5 = 700, B3 = 900) and so every value is easy to recompute by hand:
#   NDCI  = (700 - 600) / (700 + 600)
#   2BDA  = 700 / 600
#   3BDA  = (1/600 - 1/700) * 650
#   B2/B3 = 800 / 900
WORKED_EXAMPLE_BANDS: dict[str, int] = {"B2": 800, "B3": 900, "B4": 600, "B5": 700, "B6": 650}
WORKED_EXAMPLE_NOTE = (
    "Illustrative digital numbers chosen for easy hand arithmetic, not an "
    "observation; the value is the server's own index function applied to them."
)

# "~5-day revisit" -- detection/src/indices.py module docstring (two
# satellites; data-pipeline/src/sentinel2.py says the same). Approximate.
SENTINEL2_REVISIT_DAYS = 5

# detection/'s index keys -> the raster's stored band names. data-pipeline's
# raster names them without a leading digit (GEE band names must be valid
# identifiers); its comment says the mapping is "one rename at whichever
# layer joins them". /methods joins them, so the rename lives here, once.
RASTER_BAND_FOR_INDEX: dict[str, str] = {
    "ndci": "ndci",
    "2bda": "bda2",
    "3bda": "bda3",
    "b2_b3_ratio": "b2_b3",
}

WAVELENGTHS_NOTE = (
    "Centre wavelengths are listed only where the project's own documentation "
    "states them; B2 and B3 are omitted rather than supplied from elsewhere."
)

MODIS_NOTE = (
    "Level-3 mapped product sampled on its ~4.6 km grid (the instrument's ~1 km "
    "figure is before Level-3 binning). chlor_a is compared only with a chlor_a "
    "climatology; it is never merged with Sentinel-2 indices."
)

SIGNAL_ANOMALY_NOTE = (
    "Its z=2 and z=3 boundaries are provisional engineering thresholds, not "
    "validated Noctiluca thresholds."
)

# Copied verbatim from LIMITATIONS.md §"Scientific references and transfer
# limits" (line breaks joined). `note` is that section's own statement of
# what the reference does NOT license in this project.
REFERENCES: tuple[dict[str, str], ...] = (
    {
        "id": "mishra2012",
        "citation": (
            "Mishra, S. and Mishra, D.R. (2012), “Normalized difference chlorophyll index: "
            "A novel model for remote estimation of chlorophyll-a concentration in turbid "
            "productive waters,”"
        ),
        "doi": "10.1016/j.rse.2011.10.016",
        "note": (
            "This project uses Sentinel-2 B4/B5 surface reflectance. Similar wavelengths "
            "and formula do not make fitted values or raw thresholds interchangeable."
        ),
    },
    {
        "id": "luangon2023",
        "citation": (
            "Luang-on et al. (2023), “MODIS-derived green Noctiluca blooms in the upper Gulf "
            "of Thailand: Algorithm development and seasonal variation mapping,”"
        ),
        "doi": "10.3389/fmars.2023.1031901",
        "note": (
            "Those are chlorophyll-a observations and MODIS/in-situ classifications. They "
            "are not Sentinel-2 NDCI thresholds and are not inserted into this raster or API."
        ),
    },
)
